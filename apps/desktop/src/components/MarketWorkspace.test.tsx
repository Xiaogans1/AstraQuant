import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ApiClient } from "../api/client";
import type { MarketBar, QuoteCard } from "../api/market-contracts";
import { MarketWorkspace } from "./MarketWorkspace";

vi.mock("./ProfessionalMarketChart", () => ({
  ProfessionalMarketChart: ({
    period,
    bars: chartBars,
  }: {
    period: string;
    bars: MarketBar[];
  }) => (
    <div data-testid="professional-chart">
      <span>{period}</span>
      <span data-testid="chart-latest-close">{chartBars.at(-1)?.close}</span>
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
  expect(screen.getAllByText("0.712")[0]).toBeVisible();
  expect(screen.getByText("+1.57%")).toBeVisible();
  expect(screen.getByText("0.701")).toBeVisible();
  expect(screen.getByText("09:30")).toBeVisible();
  expect(screen.getByText("15:00")).toBeVisible();
  expect(screen.getByTestId("chart-latest-close")).toHaveTextContent("0.712");
  expect(client.getMarketBars).toHaveBeenCalledWith("159516.SZSE", "intraday", 240);
});

it("loads real daily bars and supports chart fullscreen", async () => {
  const user = userEvent.setup();
  const client = renderWorkspace();

  await user.click(await screen.findByRole("button", { name: "日K" }));
  expect(await screen.findByTestId("professional-chart")).toHaveTextContent("1d");
  expect(screen.getByTestId("chart-latest-close")).toHaveTextContent("0.685");
  expect(client.getMarketBars).toHaveBeenCalledWith("159516.SZSE", "1d", 500);

  await user.click(screen.getByRole("button", { name: "进入图表全屏" }));
  expect(screen.getByTestId("market-workspace")).toHaveAttribute("data-fullscreen", "true");
  await user.keyboard("{Escape}");
  expect(screen.getByTestId("market-workspace")).toHaveAttribute("data-fullscreen", "false");
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
