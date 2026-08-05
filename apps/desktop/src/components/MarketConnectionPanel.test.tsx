import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";

import type { ApiClient } from "../api/client";
import type { ConnectionState, MarketConnection } from "../api/market-contracts";
import { MarketConnectionPanel } from "./MarketConnectionPanel";

function renderPanel(state: ConnectionState, sdk = true, token = true) {
  const connection: MarketConnection = {
    provider_id: "eastmoney",
    sdk_configured: sdk,
    token_configured: token,
    state,
    connected_at: null,
    last_event_at: null,
    error_code: state === "ERROR" ? "provider_call_failed" : null,
    instrument_count: 0,
    parse_error_count: 0,
    reconnect_count: 0,
  };
  const client = {
    getMarketConnection: vi.fn().mockResolvedValue(connection),
    configureEastmoney: vi.fn(),
    startMarketConnection: vi.fn().mockResolvedValue(connection),
    stopMarketConnection: vi.fn().mockResolvedValue(connection),
  } as unknown as ApiClient;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MarketConnectionPanel client={client} />
    </QueryClientProvider>,
  );
}

it("keeps the token masked and explains local credential storage", async () => {
  renderPanel("UNAVAILABLE", false, false);

  expect(await screen.findByText("尚未配置东财行情")).toBeVisible();
  expect(screen.getByLabelText("东财 Token")).toHaveAttribute("type", "password");
  expect(screen.getByText(/Windows 凭据管理器/)).toBeVisible();
});

it.each([
  ["CONNECTING", "正在连接东财行情"],
  ["LIVE", "东财实时行情已连接"],
  ["STALE", "行情连接延迟"],
  ["CLOSED", "市场已收盘"],
  ["ERROR", "东财行情连接异常"],
] as const)("renders %s without exposing a token", async (state, label) => {
  renderPanel(state);
  expect(await screen.findByText(label)).toBeVisible();
  expect(screen.queryByDisplayValue(/token/i)).not.toBeInTheDocument();
});
