import { StringDecoder } from 'node:string_decoder';

/** Hold credential prefixes across writes, including unterminated output. */
export function consoleStream(secrets, emit = () => {}) {
  const values = [...new Set(secrets.filter(Boolean).flatMap((value) => {
    const json = JSON.stringify(value).slice(1, -1);
    const ascii = json.replace(/[\u007f-\uffff]/g, (char) => '\\u' + char.charCodeAt(0).toString(16).padStart(4, '0'));
    return [value, json, ascii];
  }))].sort((a, b) => b.length - a.length);
  const escape = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = values.length ? new RegExp(values.map(escape).join('|'), 'g') : null;
  const decoder = new StringDecoder('utf8');
  let pending = '';
  const process = (chunk, final) => {
    const text = pending + (final ? decoder.end() : decoder.write(chunk));
    let cut = text.length;
    for (const secret of values) {
      for (let size = Math.min(text.length, secret.length - 1); size > 0; size--) {
        if (text.endsWith(secret.slice(0, size))) { cut = Math.min(cut, text.length - size); break; }
      }
    }
    if (pattern) for (const match of text.matchAll(pattern)) {
      if (match.index < cut && match.index + match[0].length > cut) { cut = match.index; break; }
    }
    pending = text.slice(cut);
    const clean = pattern ? text.slice(0, cut).replace(pattern, '[REDACTED]') : text.slice(0, cut);
    if (clean) emit(clean);
    if (final && pending) { emit('[REDACTED]'); pending = ''; }
  };
  return { write: (chunk) => process(chunk, false), end: () => process(null, true) };
}
