import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import { agentArgsError, moveAgentArg } from "./agent-args";
import { AgentArgsField } from "../components/AgentArgsField";
import { translate, I18nProvider } from "../i18n";

describe("literal agent argv", () => {
  it("accepts ordered values without splitting, trimming or expanding them", () => {
    const args = ["--config", "/opt/company agent/config.json", "", "中文", "$HOME", "$(echo no); --model=not-a-flag"];
    expect(agentArgsError(args)).toBeUndefined();
    expect(moveAgentArg(args, 1, -1)).toEqual([args[1], args[0], ...args.slice(2)]);
    expect(args[0]).toBe("--config");
    expect(moveAgentArg(args, 0, -1)).toEqual(args);
  });
  it("bounds input and rejects controls and credential flags without echoing values", () => {
    for (const args of [Array(129).fill("a"), ["x".repeat(4097)], Array(9).fill("x".repeat(4096)), ["\n"], ["\0"], ["\ud800"], ["--api-key=fixture-secret"], ["--token", "fixture-secret"]]) {
      expect(agentArgsError(args)).toBeDefined();
      expect(agentArgsError(args)).not.toContain("fixture-secret");
    }
    expect(agentArgsError([])).toBeUndefined();
    expect(agentArgsError(["😀".repeat(4096)])).toBeUndefined();
  });
  it("renders individually labeled literal arguments and controls", () => {
    const html = renderToStaticMarkup(createElement(I18nProvider, null, createElement(AgentArgsField, {
      value: ["--tools", "read, bash"], onChange: () => {},
    })));
    expect(html).toContain('value="read, bash"');
    expect(html.match(/<input /g)).toHaveLength(2);
    expect(html).toContain('type="button"');
  });
  it("localizes labels and safety instructions", () => {
    expect(translate("zh-CN", "Agent startup arguments")).toBe("Agent 启动参数");
    expect(translate("zh-CN", "Remove argument {index}", { index: 2 })).toBe("移除参数 2");
    expect(translate("zh-CN", "Pass credentials through selected environment variables, not agent startup arguments.")).toContain("环境变量");
  });
});
