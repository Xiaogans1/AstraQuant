import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ApiClient } from "../api/client";
import { ApiError } from "../api/client";
import type {
  PaperAccountDetail,
  PaperAccountSummary,
} from "../api/paper-contracts";
import { PaperPage } from "./PaperPage";

vi.mock("../components/MarketWorkspace", () => ({
  MarketWorkspace: ({ quote }: { quote: { name: string; instrument_id: string } }) => (
    <div data-testid="paper-market-workspace">
      {quote.name} · {quote.instrument_id} · 持仓买卖点图
    </div>
  ),
}));

const summary: PaperAccountSummary = {
  account_id: "account-1",
  name: "主模拟账户",
  mode: "PAPER",
  initial_cash: "100000",
  cash: "99279.99",
  created_at: "2026-08-06T06:30:00Z",
  updated_at: "2026-08-06T06:31:00Z",
  initial_equity: "100000",
  total_equity: "100240.50",
  total_pnl: "240.50",
};

const detail: PaperAccountDetail = {
  account: summary,
  positions: [
    {
      instrument_id: "159516.SZSE",
      name: "半导体设备ETF",
      quantity: 1000,
      available_quantity: 800,
      average_cost: "0.6800",
      last_price: "0.7140",
      previous_close: "0.7010",
      market_value: "714.00",
      unrealized_pnl: "34.00",
      unrealized_pnl_percent: "5.0000",
      marked_at: "2026-08-06T06:31:00Z",
    },
  ],
  latest_equity: {
    snapshot_id: "snapshot-1",
    cash: "99279.99",
    market_value: "960.51",
    total_equity: "100240.50",
    initial_equity: "100000",
    total_pnl: "240.50",
    total_pnl_percent: "0.2405",
    as_of: "2026-08-06T06:31:00Z",
  },
};

function renderPage(client: ApiClient) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <PaperPage client={client} />
    </QueryClientProvider>,
  );
}

test("first visit creates and opens the default local paper account", async () => {
  const client = {
    ensureDefaultPaperAccount: vi.fn().mockResolvedValue(detail),
    listPaperAccounts: vi.fn().mockResolvedValue([summary]),
    getPaperAccount: vi.fn().mockResolvedValue(detail),
    listPaperOrders: vi.fn().mockResolvedValue([]),
    listPaperFills: vi.fn().mockResolvedValue([]),
    listPaperEquity: vi.fn().mockResolvedValue([detail.latest_equity]),
    listPaperStrategyRuns: vi.fn().mockResolvedValue([]),
  } as unknown as ApiClient;

  renderPage(client);

  expect(await screen.findByText("100,240.50")).toBeVisible();
  expect(client.ensureDefaultPaperAccount).toHaveBeenCalledTimes(1);
  expect(screen.queryByText("建立第一本模拟账本")).not.toBeInTheDocument();
});

test("account workspace shows real portfolio metrics and holdings", async () => {
  const client = {
    ensureDefaultPaperAccount: vi.fn().mockResolvedValue(detail),
    listPaperAccounts: vi.fn().mockResolvedValue([summary]),
    getPaperAccount: vi.fn().mockResolvedValue(detail),
    listPaperOrders: vi.fn().mockResolvedValue([]),
    listPaperFills: vi.fn().mockResolvedValue([]),
    listPaperEquity: vi.fn().mockResolvedValue([detail.latest_equity]),
    listPaperStrategyRuns: vi.fn().mockResolvedValue([]),
  } as unknown as ApiClient;

  renderPage(client);

  expect(await screen.findByText("100,240.50")).toBeVisible();
  expect(screen.getByText("+240.50")).toBeVisible();
  expect(screen.getAllByText("半导体设备ETF").length).toBeGreaterThan(0);
  expect(screen.getByText("+5.00%")).toBeVisible();
  expect(screen.getByText("真实行情盯市")).toBeVisible();
  expect(screen.getByTestId("paper-market-workspace")).toHaveTextContent(
    "半导体设备ETF · 159516.SZSE · 持仓买卖点图",
  );
  expect(screen.queryByRole("button", { name: "买卖" })).not.toBeInTheDocument();
});

test("account discovery does not poll or replace the workspace with onboarding", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const client = {
    ensureDefaultPaperAccount: vi.fn().mockResolvedValue(detail),
    listPaperAccounts: vi.fn().mockResolvedValue([summary]),
    getPaperAccount: vi.fn().mockResolvedValue(detail),
    listPaperOrders: vi.fn().mockResolvedValue([]),
    listPaperFills: vi.fn().mockResolvedValue([]),
    listPaperEquity: vi.fn().mockResolvedValue([detail.latest_equity]),
    listPaperStrategyRuns: vi.fn().mockResolvedValue([]),
  } as unknown as ApiClient;
  renderPage(client);

  expect(await screen.findByText("100,240.50")).toBeVisible();
  await vi.advanceTimersByTimeAsync(10_000);

  expect(client.listPaperAccounts).toHaveBeenCalledTimes(1);
  expect(screen.getByText("100,240.50")).toBeVisible();
  vi.useRealTimers();
});

test("cash editor persists the remaining cash outside current holdings", async () => {
  const updatePaperCash = vi.fn().mockResolvedValue({
    ...detail,
    account: { ...detail.account, cash: "80000" },
  });
  const client = {
    ensureDefaultPaperAccount: vi.fn().mockResolvedValue(detail),
    listPaperAccounts: vi.fn().mockResolvedValue([summary]),
    getPaperAccount: vi.fn().mockResolvedValue(detail),
    listPaperOrders: vi.fn().mockResolvedValue([]),
    listPaperFills: vi.fn().mockResolvedValue([]),
    listPaperEquity: vi.fn().mockResolvedValue([detail.latest_equity]),
    updatePaperCash,
    listPaperStrategyRuns: vi.fn().mockResolvedValue([]),
  } as unknown as ApiClient;
  renderPage(client);
  const user = userEvent.setup();

  const cashInput = await screen.findByRole("spinbutton", {
    name: "剩余现金（不含持仓）",
  });
  await user.clear(cashInput);
  await user.type(cashInput, "80000");
  await user.click(screen.getByRole("button", { name: "保存资金" }));

  expect(updatePaperCash).toHaveBeenCalledWith("account-1", { cash: "80000" });
});

test("strategy console scans all holdings concurrently and hides engineering parameters", async () => {
  const runPaperStrategyScan = vi.fn().mockResolvedValue([
    {
      outcome: "HOLD",
      proposed_side: null,
      proposed_quantity: 100,
      risk_reason: null,
      decision_id: "decision-audit-1",
      advisory_checks: ["MARKET_LIVE", "FEATURES_WARMING_UP"],
      signal: {
        signal_id: "signal-audit-1",
        instrument_id: "159516.SZSE",
        action: "HOLD",
        state: "WARMING_UP",
        reference_price: null,
        confidence: "0",
        strategy_id: "intraday-momentum-volume",
        strategy_version: "baseline-v1",
        feature_version: "realtime-v1",
        reason_codes: ["INSUFFICIENT_COMPLETED_BARS"],
        event_time: "2026-08-06T06:31:00Z",
        decision_time: "2026-08-06T06:31:00Z",
        expires_at: "2026-08-06T06:32:00Z",
      },
      order: null,
      fill: null,
    },
    {
      outcome: "BLOCKED",
      proposed_side: "BUY",
      proposed_quantity: 100,
      risk_reason: "max_position_value_exceeded",
      decision_id: "decision-audit-2",
      advisory_checks: ["MARKET_LIVE"],
      signal: {
        signal_id: "signal-audit-2",
        instrument_id: "600000.SSE",
        action: "BUY",
        state: "ACTIVE",
        reference_price: "9.26",
        confidence: "0.62",
        strategy_id: "intraday-momentum-volume",
        strategy_version: "baseline-v1",
        feature_version: "realtime-v1",
        reason_codes: ["MOMENTUM_UP"],
        event_time: "2026-08-06T06:31:00Z",
        decision_time: "2026-08-06T06:31:00Z",
        expires_at: "2026-08-06T06:32:00Z",
      },
      order: null,
      fill: null,
    },
  ]);
  const client = {
    ensureDefaultPaperAccount: vi.fn().mockResolvedValue({
      ...detail,
      positions: [
        ...detail.positions,
        {
          instrument_id: "600000.SSE",
          name: "浦发银行",
          quantity: 500,
          available_quantity: 500,
          average_cost: "9.00",
          last_price: "9.26",
          market_value: "4630.00",
          unrealized_pnl: "130.00",
          unrealized_pnl_percent: "2.8889",
          marked_at: "2026-08-06T06:31:00Z",
        },
      ],
    }),
    listPaperAccounts: vi.fn().mockResolvedValue([summary]),
    getPaperAccount: vi.fn().mockResolvedValue({
      ...detail,
      positions: [
        ...detail.positions,
        {
          instrument_id: "600000.SSE",
          name: "浦发银行",
          quantity: 500,
          available_quantity: 500,
          average_cost: "9.00",
          last_price: "9.26",
          market_value: "4630.00",
          unrealized_pnl: "130.00",
          unrealized_pnl_percent: "2.8889",
          marked_at: "2026-08-06T06:31:00Z",
        },
      ],
    }),
    listPaperOrders: vi.fn().mockResolvedValue([]),
    listPaperFills: vi.fn().mockResolvedValue([]),
    listPaperEquity: vi.fn().mockResolvedValue([detail.latest_equity]),
    runPaperStrategyScan,
    listPaperStrategyRuns: vi.fn().mockResolvedValue([]),
  } as unknown as ApiClient;
  renderPage(client);
  const user = userEvent.setup();

  expect(await screen.findByText("全部持仓 · 2 只（并发检查）")).toBeVisible();
  await user.click(await screen.findByRole("button", { name: "检查全部持仓" }));

  expect(runPaperStrategyScan).toHaveBeenCalledWith("account-1", {
    instrument_id: "159516.SZSE",
    quantity: 100,
    auto_execute: true,
    max_position_percent: "20",
  });
  expect(screen.queryByText("建议数量")).not.toBeInTheDocument();
  expect(screen.queryByText("单标的仓位上限")).not.toBeInTheDocument();
  expect(screen.queryByText("允许自动执行模拟成交")).not.toBeInTheDocument();
  expect(await screen.findByText("HOLD")).toBeVisible();
  expect(screen.getByText("BLOCKED")).toBeVisible();
  expect(screen.getAllByText("半导体设备ETF").length).toBeGreaterThan(0);
  expect(screen.getAllByText("浦发银行").length).toBeGreaterThan(0);
  expect(screen.getByText("max_position_value_exceeded")).toBeVisible();
  expect(screen.getByText("decision-audit-1")).toBeVisible();
  expect(screen.getByText("decision-audit-2")).toBeVisible();
});

test("strategy panel restores the latest persisted scan after refresh", async () => {
  const persisted = [
    {
      outcome: "HOLD",
      proposed_side: null,
      proposed_quantity: 100,
      risk_reason: null,
      decision_id: "decision-persisted-1",
      advisory_checks: ["MARKET_LIVE", "FEATURES_WARMING_UP"],
      signal: {
        signal_id: "signal-persisted-1",
        instrument_id: "159516.SZSE",
        action: "HOLD",
        state: "WARMING_UP",
        reference_price: null,
        confidence: "0",
        strategy_id: "intraday-momentum-volume",
        strategy_version: "baseline-v1",
        feature_version: "realtime-v1",
        reason_codes: ["INSUFFICIENT_COMPLETED_BARS"],
        event_time: "2026-08-06T06:31:00Z",
        decision_time: "2026-08-06T06:31:00Z",
        expires_at: "2026-08-06T06:32:00Z",
      },
      order: null,
      fill: null,
    },
  ];
  const client = {
    ensureDefaultPaperAccount: vi.fn().mockResolvedValue(detail),
    listPaperAccounts: vi.fn().mockResolvedValue([summary]),
    getPaperAccount: vi.fn().mockResolvedValue(detail),
    listPaperOrders: vi.fn().mockResolvedValue([]),
    listPaperFills: vi.fn().mockResolvedValue([]),
    listPaperEquity: vi.fn().mockResolvedValue([detail.latest_equity]),
    listPaperStrategyRuns: vi.fn().mockResolvedValue(persisted),
  } as unknown as ApiClient;
  renderPage(client);

  expect(await screen.findByText(/最近检查/)).toBeVisible();
  expect(screen.getByText("decision-persisted-1")).toBeVisible();
  expect(screen.getByText("1 分钟 K 线不足 20 根，特征热身中")).toBeVisible();
  expect(client.listPaperStrategyRuns).toHaveBeenCalledWith("account-1");
});

test("account rail shows today's pnl from last close for historical cost holdings", async () => {
  const client = {
    ensureDefaultPaperAccount: vi.fn().mockResolvedValue({
      ...detail,
      positions: [
        {
          ...detail.positions[0],
          last_price: "0.7200",
          previous_close: "0.7000",
          market_value: "720.00",
          unrealized_pnl: "40.00",
          unrealized_pnl_percent: "5.8824",
        },
      ],
    }),
    listPaperAccounts: vi.fn().mockResolvedValue([summary]),
    getPaperAccount: vi.fn().mockResolvedValue({
      ...detail,
      positions: [
        {
          ...detail.positions[0],
          last_price: "0.7200",
          previous_close: "0.7000",
          market_value: "720.00",
          unrealized_pnl: "40.00",
          unrealized_pnl_percent: "5.8824",
        },
      ],
    }),
    listPaperOrders: vi.fn().mockResolvedValue([]),
    listPaperFills: vi.fn().mockResolvedValue([]),
    listPaperEquity: vi.fn().mockResolvedValue([detail.latest_equity]),
    listPaperStrategyRuns: vi.fn().mockResolvedValue([]),
  } as unknown as ApiClient;
  renderPage(client);

  expect(await screen.findByText("当日盈亏")).toBeVisible();
  expect(screen.getByText("+20.00")).toBeVisible();
  expect(screen.getByText(/今日 \+2\.86%（相对昨收）/)).toBeVisible();
});

test("opening position form searches the real catalog and requires a selected instrument", async () => {
  const addPaperOpeningPosition = vi.fn().mockResolvedValue(detail);
  const client = {
    ensureDefaultPaperAccount: vi.fn().mockResolvedValue(detail),
    listPaperAccounts: vi.fn().mockResolvedValue([summary]),
    getPaperAccount: vi.fn().mockResolvedValue(detail),
    listPaperOrders: vi.fn().mockResolvedValue([]),
    listPaperFills: vi.fn().mockResolvedValue([]),
    listPaperEquity: vi.fn().mockResolvedValue([detail.latest_equity]),
    searchMarketInstruments: vi.fn().mockResolvedValue([
      { instrument_id: "159516.SZSE", name: "半导体设备ETF", kind: "etf" },
      { instrument_id: "588200.SSE", name: "半导体ETF", kind: "etf" },
    ]),
    addPaperOpeningPosition,
    listPaperStrategyRuns: vi.fn().mockResolvedValue([]),
  } as unknown as ApiClient;
  renderPage(client);
  const user = userEvent.setup();

  const submit = await screen.findByRole("button", { name: "添加到初始持仓" });
  expect(submit).toBeDisabled();

  await user.type(
    await screen.findByRole("searchbox", { name: "搜索期初持仓证券" }),
    "159516",
  );
  expect(client.searchMarketInstruments).toHaveBeenCalledWith("159516");
  await user.click(
    await screen.findByRole("button", { name: /半导体设备ETF.*159516\.SZSE.*选择/ }),
  );

  expect(
    screen.getByText("半导体设备ETF", { selector: ".instrument-picker--selected strong" }),
  ).toBeVisible();
  expect(
    screen.getByText("159516.SZSE", { selector: ".instrument-picker--selected span" }),
  ).toBeVisible();
  expect(submit).toBeEnabled();
  expect(screen.queryByRole("searchbox", { name: "搜索期初持仓证券" })).not.toBeInTheDocument();

  await user.type(screen.getByLabelText("持有数量"), "500");
  const availableInput = screen.getByLabelText("可用数量");
  await user.clear(availableInput);
  await user.type(availableInput, "500");
  await user.type(screen.getByLabelText("平均成本"), "9");
  await user.click(submit);

  expect(addPaperOpeningPosition).toHaveBeenCalledWith("account-1", {
    instrument_id: "159516.SZSE",
    name: "半导体设备ETF",
    quantity: 500,
    available_quantity: 500,
    average_cost: "9",
  });
});

test("opening position form resets after save and supports continuous additions", async () => {
  const addPaperOpeningPosition = vi.fn().mockResolvedValue(detail);
  const client = {
    ensureDefaultPaperAccount: vi.fn().mockResolvedValue(detail),
    listPaperAccounts: vi.fn().mockResolvedValue([summary]),
    getPaperAccount: vi.fn().mockResolvedValue(detail),
    listPaperOrders: vi.fn().mockResolvedValue([]),
    listPaperFills: vi.fn().mockResolvedValue([]),
    listPaperEquity: vi.fn().mockResolvedValue([detail.latest_equity]),
    searchMarketInstruments: vi.fn().mockResolvedValue([
      { instrument_id: "600000.SSE", name: "浦发银行", kind: "equity" },
    ]),
    addPaperOpeningPosition,
    listPaperStrategyRuns: vi.fn().mockResolvedValue([]),
  } as unknown as ApiClient;
  renderPage(client);
  const user = userEvent.setup();

  await user.type(
    await screen.findByRole("searchbox", { name: "搜索期初持仓证券" }),
    "600000",
  );
  await user.click(await screen.findByRole("button", { name: /浦发银行.*选择/ }));
  await user.type(screen.getByLabelText("持有数量"), "300");
  await user.type(screen.getByLabelText("可用数量"), "300");
  await user.type(screen.getByLabelText("平均成本"), "9.5");
  await user.click(screen.getByRole("button", { name: "添加到初始持仓" }));

  expect(addPaperOpeningPosition).toHaveBeenCalledTimes(1);
  expect(await screen.findByRole("searchbox", { name: "搜索期初持仓证券" })).toBeVisible();
  expect(screen.getByLabelText("持有数量")).toHaveValue(null);
  expect(screen.getByLabelText("可用数量")).toHaveValue(null);
  expect(screen.getByLabelText("平均成本")).toHaveValue(null);
  expect(screen.getByText("可连续添加")).toBeVisible();
});

test("opening position form explains duplicate holdings in Chinese", async () => {
  const addPaperOpeningPosition = vi.fn().mockRejectedValue(
    new ApiError(
      { code: "opening_position_conflict", message: "opening position already exists" },
      409,
    ),
  );
  const client = {
    ensureDefaultPaperAccount: vi.fn().mockResolvedValue(detail),
    listPaperAccounts: vi.fn().mockResolvedValue([summary]),
    getPaperAccount: vi.fn().mockResolvedValue(detail),
    listPaperOrders: vi.fn().mockResolvedValue([]),
    listPaperFills: vi.fn().mockResolvedValue([]),
    listPaperEquity: vi.fn().mockResolvedValue([detail.latest_equity]),
    searchMarketInstruments: vi.fn().mockResolvedValue([
      { instrument_id: "159516.SZSE", name: "半导体设备ETF", kind: "etf" },
    ]),
    addPaperOpeningPosition,
    listPaperStrategyRuns: vi.fn().mockResolvedValue([]),
  } as unknown as ApiClient;
  renderPage(client);
  const user = userEvent.setup();

  await user.type(
    await screen.findByRole("searchbox", { name: "搜索期初持仓证券" }),
    "159516",
  );
  await user.click(await screen.findByRole("button", { name: /半导体设备ETF.*选择/ }));
  await user.type(screen.getByLabelText("持有数量"), "100");
  await user.type(screen.getByLabelText("可用数量"), "100");
  await user.type(screen.getByLabelText("平均成本"), "0.68");
  await user.click(screen.getByRole("button", { name: "添加到初始持仓" }));

  expect(await screen.findByText("该证券已在期初持仓中，请勿重复添加")).toBeVisible();
  expect(screen.queryByText("opening position already exists")).not.toBeInTheDocument();
});
