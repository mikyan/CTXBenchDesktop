import assert from 'node:assert/strict';
import test from 'node:test';
import { consoleStream } from './console-stream.mjs';

test('console redaction holds split credentials and UTF-8 at every byte boundary', () => {
  const secret = 'fixture-密钥\\"secret';
  const json = JSON.stringify(secret).slice(1, -1);
  for (const value of [secret, json, json.replace(/[\u007f-\uffff]/g, (char) => '\\u' + char.charCodeAt(0).toString(16).padStart(4, '0'))]) {
    const raw = Buffer.from(`开始🙂 ${value} done\n`);
    for (let i = 0; i <= raw.length; i++) {
      let output = '';
      const stream = consoleStream([secret], (text) => { output += text; });
      stream.write(raw.subarray(0, i)); stream.write(raw.subarray(i)); stream.end();
      assert.equal(output, '开始🙂 [REDACTED] done\n', `split ${i}`);
    }
  }
});

test('console emits before end and hides incomplete credentials on shutdown', () => {
  let output = '';
  const stream = consoleStream(['fixture-secret'], (text) => { output += text; });
  stream.write(Buffer.from('READY fixture-'));
  assert.equal(output, 'READY ');
  stream.end();
  assert.equal(output, 'READY [REDACTED]');
});

test('overlapping prefixes and regex metacharacters never expose credentials', () => {
  for (const values of [['aaab', 'ab'], ['abc', 'bcd'], ['x.*[0]'], ['a', 'abcdef']]) {
    const raw = Buffer.from(`before ${values.join(' ')} after\n`);
    for (let size = 1; size <= raw.length; size++) {
      let output = '';
      const stream = consoleStream(values, (text) => { output += text; });
      for (let index = 0; index < raw.length; index += size) stream.write(raw.subarray(index, index + size));
      stream.end();
      for (const value of values) assert(!output.includes(value));
    }
  }
});
