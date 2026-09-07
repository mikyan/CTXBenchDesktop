import { createHash } from "node:crypto";

const switches = new Set(["--verbose", "--no-tools", "-nt", "--no-builtin-tools", "-nbt", "--no-themes", "--no-context-files", "-nc"]);
const values = new Set(["--tools", "-t", "--exclude-tools", "-xt"]);

export function piAgentArgs(value = []) {
  if (!Array.isArray(value) || value.length > 128) throw new Error("Invalid agent startup arguments array.");
  if (value.some((arg) => typeof arg !== "string" || [...arg].length > 4096 || /[\u0000-\u001f\u007f-\u009f]|\p{Surrogate}/u.test(arg))
      || value.reduce((size, arg) => size + [...arg].length, 0) > 32768) throw new Error("Invalid agent startup argument text.");
  for (let index = 0; index < value.length; index++) {
    if (values.has(value[index])) {
      const next = value[++index];
      if (!next?.trim() || /^[-@]/.test(next)) throw new Error("Pi tool options require a separate, non-empty tool-list argument.");
    } else if (!switches.has(value[index])) {
      throw new Error("Unsupported Pi startup argument. Model, prompt, RPC, session and discovery settings are controlled by the benchmark; see the adapter documentation for supported options.");
    }
  }
  return [...value];
}

export function agentArgsReceipt(args) {
  return { agentArgsProtocolVersion: 1, agentArgsHash: createHash("sha256").update(JSON.stringify(args)).digest("hex") };
}
