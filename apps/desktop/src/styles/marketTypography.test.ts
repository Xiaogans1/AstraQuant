// @vitest-environment node
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const tokens = readFileSync(new URL("../theme/tokens.css", import.meta.url), "utf8");
const css = readFileSync(new URL("./app.css", import.meta.url), "utf8");
const marketCss = css.slice(css.indexOf(".market-terminal"));

describe("market typography", () => {
  it("does not force geometric precision in WebView2", () => {
    expect(tokens).not.toContain("text-rendering: geometricPrecision");
  });

  it("keeps readable market content at twelve pixels or larger", () => {
    expect(marketCss).not.toMatch(/font-size:\s*(8|9|10|11)px/);
  });

  it("keeps Chinese UI and numeric fonts separate", () => {
    expect(tokens).toContain('--font-ui: "Microsoft YaHei UI"');
    expect(tokens).toContain('--font-numeric: "Cascadia Mono"');
  });
});
