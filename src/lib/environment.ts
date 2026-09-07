export interface RuntimeVariable {
  name: string;
  value: string;
}

const environmentName = /^[A-Z][A-Z0-9_]{1,127}$/;

export function parseEnvironmentNames(text: string): string[] {
  return [...new Set(text.split(/[\s,，;；]+/).filter(Boolean))];
}

export function environmentNamesError(text: string): string | undefined {
  if (text.includes("=")) return "Enter variable names only; save values in Infrastructure.";
  if (parseEnvironmentNames(text).some((name) => !environmentName.test(name))) {
    return "Variable names must be 2–128 uppercase letters, digits or underscores, starting with a letter.";
  }
}

export function runtimeVariablesPayload(rows: RuntimeVariable[]): { variables: RuntimeVariable[] } {
  const variables = rows.map(({ name, value }) => ({ name: name.trim(), value }))
    .filter(({ name, value }) => name || value);
  if (!variables.length || variables.length > 100) throw new Error("Enter between 1 and 100 environment variables.");
  if (variables.some(({ name }) => !environmentName.test(name))) {
    throw new Error("Variable names must be 2–128 uppercase letters, digits or underscores, starting with a letter.");
  }
  if (variables.some(({ value }) => !value || value.includes("\0"))) {
    throw new Error("Each variable needs a non-empty value without NUL characters.");
  }
  if (new Set(variables.map(({ name }) => name)).size !== variables.length) {
    throw new Error("Each environment variable name must be unique.");
  }
  return { variables };
}
