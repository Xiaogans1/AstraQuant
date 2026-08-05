import {
  developmentMarketSnapshot,
  searchMarketCatalog,
} from "./developmentMarket";

describe("development market snapshot", () => {
  it("cannot be mistaken for a realtime provider", () => {
    expect(developmentMarketSnapshot.sourceMode).toBe("simulation");
    expect(developmentMarketSnapshot.sourceLabel).toBe("开发模拟行情");
    expect(
      new Set(developmentMarketSnapshot.watchlist.map((item) => item.kind)),
    ).toEqual(new Set(["stock", "etf", "future"]));
  });

  it("searches the instrument catalog by code or name", () => {
    expect(searchMarketCatalog("510300").map((item) => item.name)).toContain(
      "沪深300ETF",
    );
    expect(searchMarketCatalog("黄金").map((item) => item.symbol)).toContain(
      "518880.SSE",
    );
    expect(searchMarketCatalog("IF").map((item) => item.symbol)).toContain(
      "IF0.CFFEX",
    );
    expect(
      developmentMarketSnapshot.watchlist.map((item) => item.symbol),
    ).not.toContain("IF0.CFFEX");
    expect(searchMarketCatalog("  ")).toEqual([]);
  });
});
