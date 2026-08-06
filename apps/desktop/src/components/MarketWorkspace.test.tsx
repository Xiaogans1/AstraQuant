import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ApiClient } from "../api/client";
import type { MarketBar, QuoteCard } from "../api/market-contracts";
import { MarketWorkspace } from "./MarketWorkspace";

vi.mock("./ProfessionalMarketChart", () => ({
  ProfessionalMarketChart: ({
    period,
    mainIndicator,
    secondaryIndicator,
    showQuantSignals,
    bars: chartBars,
    signals,
    onCrosshairBarChange,
  }: {
    period: string;
    mainIndicator: string;
    secondaryIndicator: string;
    showQuantSignals: boolean;
    bars: MarketBar[];
    signals: Array<{ id: string; side: string }>;
    onCrosshairBarChange?: (bar: MarketBar | null) => void;
  }) => (
    <div data-testid="professional-chart">
      <span>{period}</span>
      <span data-testid="chart-main-indicator">{mainIndicator}</span>
      <span data-testid="chart-secondary-indicator">{secondaryIndicator}</span>
      <span data-testid="chart-quant-visible">{String(showQuantSignals)}</span>
      <span data-testid="chart-latest-close">{chartBars.at(-1)?.close}</span>
      <span data-testid="chart-signals">{(signals ?? []).map((signal) => signal.id).join(",")}</span>
      <button
        type="button"
        onClick={() =>
          onCrosshairBarChange?.({
            timestamp: "2026-08-06T10:01:00+08:00",
            open: 0.702,
            high: 0.706,
            low: 0.7,
            close: 0.703,
            volume: 120,
            turnover: 84.36,
            previous_close: null,
          })
        }
      >
        移动十字光标
      </button>
      <button type="button" onClick={() => onCrosshairBarChange?.(null)}>
        离开行情图
      </button>
    </div>
  ),
}));

const quote: QuoteCard = {
  instrument_id: "159516.SZSE",
  name: "半导体设备ETF",
  kind: "fund",
  state: "LIVE",
  event_time: "2026-08-06T10:02:00+08:00",
  last_price: "0.712",
  change: "0.011",
  change_percent: "1.5692",
  previous_close: "0.701",
  open: "0.680",
  high: "0.716",
  low: "0.677",
  volume: "481900",
  turnover: "34260000",
  source_id: "eastmoney",
};

const bars: MarketBar[] = [
  {
    timestamp: "2026-08-06T09:30:00+08:00",
    open: 0.68,
    high: 0.69,
    low: 0.677,
    close: 0.685,
    volume: 100,
    turnover: 68.5,
    previous_close: 0.701,
  },
];

function renderWorkspace() {
  const client = {
    getMarketBars: vi.fn().mockResolvedValue(bars),
    getMarketSignal: vi.fn().mockResolvedValue({
      features: {
        feature_snapshot_id: "feature-1",
        status: "READY",
        completed_bar_count: 30,
        reason_codes: [],
      },
      signal: {
        signal_id: "signal-1",
        instrument_id: quote.instrument_id,
        event_time: quote.event_time,
        decision_time: quote.event_time,
        expires_at: "2026-08-06T10:04:00+08:00",
        action: "BUY",
        state: "ACTIVE",
        reference_price: quote.last_price,
        confidence: "0.68",
        strategy_id: "intraday-momentum-volume",
        strategy_version: "baseline-v1",
        feature_version: "realtime-v1",
        reason_codes: ["MOMENTUM_VOLUME_BREAKOUT"],
      },
      decision_record: {
        decision_id: "decision-1",
        feature_snapshot_id: "feature-1",
        signal_id: "signal-1",
        strategy_id: "intraday-momentum-volume",
        strategy_version: "baseline-v1",
        market_event_time: quote.event_time,
        decision_time: quote.event_time,
        advisory_checks: ["READ_ONLY_ADVISORY"],
      },
    }),
  } as unknown as ApiClient;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MarketWorkspace client={client} quote={quote} state="LIVE" />
    </QueryClientProvider>,
  );
  return client;
}

it("shows truthful broker-style quote stats and a full-width chart", async () => {
  const client = renderWorkspace();

  expect(await screen.findByTestId("professional-chart")).toHaveTextContent("intraday");
  expect(screen.getByTestId("chart-main-indicator")).toHaveTextContent("AVG");
  expect(screen.getByTestId("chart-secondary-indicator")).toHaveTextContent("VOL");
  expect(screen.getAllByText("0.712")[0]).toBeVisible();
  expect(screen.getByText("+1.57%")).toBeVisible();
  expect(screen.getByText("0.701")).toBeVisible();
  expect(screen.getByText("09:30")).toBeVisible();
  expect(screen.getByText("15:00")).toBeVisible();
  expect(screen.getByTestId("chart-latest-close")).toHaveTextContent("0.712");
  expect(client.getMarketBars).toHaveBeenCalledWith("159516.SZSE", "intraday", 240);
  expect(await screen.findByText("买入观察 · 68%")).toBeVisible();
  expect(screen.getByTestId("chart-signals")).toHaveTextContent("signal-1");
  expect(client.getMarketSignal).toHaveBeenCalledWith("159516.SZSE");
});

it("loads real daily bars and supports chart fullscreen", async () => {
  const user = userEvent.setup();
  const client = renderWorkspace();

  await user.click(await screen.findByRole("button", { name: "日K" }));
  expect(await screen.findByTestId("professional-chart")).toHaveTextContent("1d");
  expect(screen.getByTestId("chart-main-indicator")).toHaveTextContent("MA");
  expect(screen.getByTestId("chart-latest-close")).toHaveTextContent("0.685");
  expect(client.getMarketBars).toHaveBeenCalledWith("159516.SZSE", "1d", 500);

  await user.click(screen.getByRole("button", { name: "主图：MA" }));
  await user.click(screen.getByRole("menuitem", { name: "BOLL" }));
  expect(screen.getByTestId("chart-main-indicator")).toHaveTextContent("BOLL");

  await user.click(screen.getByRole("button", { name: "副图：VOL" }));
  await user.click(screen.getByRole("menuitem", { name: "MACD" }));
  expect(screen.getByTestId("chart-secondary-indicator")).toHaveTextContent("MACD");

  await user.click(screen.getByRole("button", { name: "量化图层" }));
  expect(screen.getByTestId("chart-quant-visible")).toHaveTextContent("false");

  await user.click(screen.getByRole("button", { name: "进入图表全屏" }));
  expect(screen.getByTestId("market-workspace")).toHaveAttribute("data-fullscreen", "true");
  await user.keyboard("{Escape}");
  expect(screen.getByTestId("market-workspace")).toHaveAttribute("data-fullscreen", "false");
});

it("shows an honest quant error while keeping successful market bars visible", async () => {
  const client = {
    getMarketBars: vi.fn().mockResolvedValue(bars),
    getMarketSignal: vi.fn().mockRejectedValue(new Error("signal route failed")),
  } as unknown as ApiClient;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MarketWorkspace client={client} quote={quote} state="LIVE" />
    </QueryClientProvider>,
  );

  expect(await screen.findByTestId("professional-chart")).toBeVisible();
  expect(await screen.findByText("量化服务暂不可用")).toBeVisible();
  expect(screen.getByText("行情图仍可正常使用")).toBeVisible();
});

it("updates the main quote from the crosshair bar and restores realtime quote on leave", async () => {
  const user = userEvent.setup();
  renderWorkspace();

  await user.click(await screen.findByRole("button", { name: "移动十字光标" }));
  expect(screen.getByText("0.703")).toBeVisible();
  expect(screen.getByText("+0.29%")).toBeVisible();
  expect(screen.getByText("+0.0020")).toBeVisible();

  await user.click(screen.getByRole("button", { name: "离开行情图" }));
  expect(screen.getAllByText("0.712")[0]).toBeVisible();
  expect(screen.getByText("+1.57%")).toBeVisible();
});

it("keeps the last successful chart visible when a background refresh fails", async () => {
  const getMarketBars = vi.fn()
    .mockResolvedValueOnce(bars)
    .mockRejectedValue(new Error("temporary Eastmoney failure"));
  const client = { getMarketBars } as unknown as ApiClient;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MarketWorkspace client={client} quote={quote} state="LIVE" />
    </QueryClientProvider>,
  );

  expect(await screen.findByTestId("professional-chart")).toBeVisible();
  await act(async () => {
    await queryClient.invalidateQueries({
      queryKey: ["market", "bars", "159516.SZSE", "intraday"],
    });
  });

  expect(await screen.findByText("行情更新暂时失败，继续显示上次成功数据")).toBeVisible();
  expect(screen.getByTestId("professional-chart")).toBeVisible();
});

it("shows a full error only when no chart data has ever loaded", async () => {
  const client = {
    getMarketBars: vi.fn().mockRejectedValue(new Error("Eastmoney unavailable")),
    getMarketSignal: vi.fn().mockRejectedValue(new Error("Eastmoney unavailable")),
  } as unknown as ApiClient;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MarketWorkspace client={client} quote={quote} state="LIVE" />
    </QueryClientProvider>,
  );

  expect(await screen.findByText("行情图加载失败")).toBeVisible();
  expect(screen.queryByTestId("professional-chart")).not.toBeInTheDocument();
});
