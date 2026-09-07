export function agentArgsError(args: readonly string[]): string | undefined {
  if (args.length > 128) return "Use at most 128 agent startup arguments.";
  if (args.some((arg) => [...arg].length > 4096 || /[\u0000-\u001f\u007f-\u009f]|\p{Surrogate}/u.test(arg))) return "Arguments must be at most 4096 characters each, without control characters.";
  if (args.reduce((size, arg) => size + [...arg].length, 0) > 32768) return "Agent startup arguments must total at most 32768 characters.";
  if (args.some((arg) => /^--?(?:api[-_]?key|(?:access[-_]?|auth[-_]?|bearer[-_]?)?token|password|secret|client[-_]?secret|credential)s?(?:=|$)/i.test(arg))) return "Pass credentials through selected environment variables, not agent startup arguments.";
}

export function moveAgentArg(args: readonly string[], index: number, direction: -1 | 1): string[] {
  const next = [...args];
  const target = index + direction;
  if (index >= 0 && index < args.length && target >= 0 && target < args.length) [next[index], next[target]] = [next[target], next[index]];
  return next;
}
