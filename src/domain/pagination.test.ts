import { expect, it } from "vitest";
import { pageWindow } from "./pagination";

it("clamps pages when live results or filters shrink and handles empty data", () => {
  expect(pageWindow(2552, 51)).toEqual({ page: 51, pages: 52, start: 2550, end: 2552 });
  expect(pageWindow(12, 51)).toEqual({ page: 0, pages: 1, start: 0, end: 12 });
  expect(pageWindow(0, -1)).toEqual({ page: 0, pages: 1, start: 0, end: 0 });
  expect(() => pageWindow(10, 0, 0)).toThrow();
});
