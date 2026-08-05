import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ApiClient } from "../api/client";
import type {
  MarketConnection,
  MarketHome,
  QuoteCard,
} from "../api/market-contracts";
import { OverviewPage } from "./OverviewPage";

const baseConnection: MarketConnection = {
  provider_id: "eastmoney",
  sdk_configured: true,
  token_configured: true,
  state: "LIVE",
  connected_at: "2026-08-05T02:30:00Z",
  last_event_at: "2026-08-05T02:30:03Z",
  error_code: null,
  instrument_count: 6,
  parse_error_count: 0,
  reconnect_count: 0,
};

function quote(
  instrument_id: string,
  name: string,
  last_price: string | null = "3560.12",
): QuoteCard {
  return {
    instrument_id,
    name,
    kind: "index",
    state: "LIVE",
    event_time: last_price === null ? null : "2026-08-05T02:30:03Z",
    last_price,
    change: last_price === null ? null : "20.12",
    change_percent: last_price === null ? null : "0.5684",
    turnover: last_price === null ? null : "4300000",
    source_id: last_price === null ? null : "eastmoney",
  };
}

const coreIndices = [
  quote("000001.SSE", "上证指数"),
  quote("399001.SZSE", "深证成指"),
  quote("399006.SZSE", "创业板指"),
  quote("000688.SSE", "科创50"),
  quote("000300.SSE", "沪深300"),
  quote("399852.SZSE", "中证1000"),
];

function homeFixture(
  overrides: Partial<MarketHome> = {},
): MarketHome {
  return {
    connection: baseConnection,
    core_indices: coreIndices,
    watchlist: [],
    selected_instrument: null,
    breadth: {
      status: "UNAVAILABLE",
      reason: "当前东财免费行情不提供全市场宽度",
    },
    intelligence: {
      status: "UNAVAILABLE",
      reason: "AI 情报尚未接入真实证据链",
    },
    candidates: [],
    as_of: "2026-08-05T02:30:03Z",
    ...overrides,
  };
}

function renderMarketHome(home: MarketHome, connection = home.connection) {
  const client = {
    getMarketConnection: vi.fn().mockResolvedValue(connection),
    getMarketHome: vi.fn().mockResolvedValue(home),
    getMarketIntraday: vi.fn().mockResolvedValue([]),
    searchMarketInstruments: vi.fn().mockResolvedValue([]),
    addWatchlistInstrument: vi.fn().mockResolvedValue(home),
    removeWatchlistInstrument: vi.fn().mockResolvedValue(home),
  } as unknown as ApiClient;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <OverviewPage client={client} />
    </QueryClientProvider>,
  );
  return client;
}

function renderMarketError() {
  const connection = { ...baseConnection, state: "UNAVAILABLE" as const };
  const client = {
    getMarketConnection: vi.fn().mockResolvedValue(connection),
    getMarketHome: vi.fn().mockRejectedValue(new Error("market unavailable")),
  } as unknown as ApiClient;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <OverviewPage client={client} />
    </QueryClientProvider>,
  );
}

it("renders six real core indices from the local API", async () => {
  renderMarketHome(homeFixture());

  expect(await screen.findAllByTestId("core-index")).toHaveLength(6);
  expect(screen.getByText("东财掘金实时行情")).toBeVisible();
  expect(screen.getByText("上证指数")).toBeVisible();
  expect(screen.queryByText(/模拟行情|模拟盘口|全市场扫描/)).not.toBeInTheDocument();
});

it("never invents numbers when Eastmoney is unavailable", async () => {
  const connection = {
    ...baseConnection,
    sdk_configured: false,
    token_configured: false,
    state: "UNAVAILABLE" as const,
    last_event_at: null,
    error_code: "missing_sdk",
  };
  renderMarketHome(
    homeFixture({
      connection,
      core_indices: coreIndices.map((item) => ({
        ...item,
        state: "UNAVAILABLE",
        event_time: null,
        last_price: null,
        change: null,
        change_percent: null,
        turnover: null,
        source_id: null,
      })),
      as_of: null,
    }),
    connection,
  );

  expect(await screen.findByText("尚未连接东财行情")).toBeVisible();
  expect(screen.queryByText("3,421.68")).not.toBeInTheDocument();
  expect(screen.getByText("当前东财免费行情不提供全市场宽度")).toBeVisible();
  expect(screen.getAllByText("暂无真实数据").length).toBeGreaterThan(0);
});

it("marks cached real data as stale instead of realtime", async () => {
  const connection = { ...baseConnection, state: "STALE" as const };
  renderMarketHome(homeFixture({ connection }), connection);

  expect(await screen.findByText("行情已延迟")).toBeVisible();
  expect(screen.getByText("最后真实快照")).toBeVisible();
});

it("explains closed markets and empty quant candidates honestly", async () => {
  const connection = { ...baseConnection, state: "CLOSED" as const };
  renderMarketHome(homeFixture({ connection }), connection);

  expect(await screen.findByText("市场已收盘")).toBeVisible();
  expect(screen.getByText("量化候选将在实时策略链路接入后生成")).toBeVisible();
});

it("keeps six named index slots without inventing values when the API fails", async () => {
  renderMarketError();

  expect(await screen.findAllByTestId("core-index")).toHaveLength(6);
  expect(screen.getByText("上证指数")).toBeVisible();
  expect(screen.getAllByText("暂无真实数据")).toHaveLength(6);
  expect(screen.queryByText("3,421.68")).not.toBeInTheDocument();
});

it("searches the real catalog and adds the selected instrument", async () => {
  const user = userEvent.setup();
  const client = renderMarketHome(homeFixture());
  vi.mocked(client.searchMarketInstruments).mockResolvedValue([
    { instrument_id: "600000.SSE", name: "浦发银行", kind: "equity" },
  ]);

  await user.type(await screen.findByRole("searchbox", { name: "搜索证券" }), "600000");
  await user.click(await screen.findByRole("button", { name: /浦发银行.*加入自选/ }));

  expect(client.searchMarketInstruments).toHaveBeenCalledWith("600000");
  expect(client.addWatchlistInstrument).toHaveBeenCalledWith("600000.SSE");
});

it("shows a visible error when the real catalog search fails", async () => {
  const user = userEvent.setup();
  const client = renderMarketHome(homeFixture());
  vi.mocked(client.searchMarketInstruments).mockRejectedValue(
    new Error("Eastmoney SDK call failed"),
  );

  await user.type(await screen.findByRole("searchbox", { name: "搜索证券" }), "600000");

  expect(await screen.findByText("证券目录搜索失败，请稍后重试")).toBeVisible();
});
