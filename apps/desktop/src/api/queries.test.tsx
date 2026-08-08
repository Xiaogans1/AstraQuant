import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

import type { ApiClient } from "./client";
import type { MarketHome } from "./market-contracts";
import { useMarketHomeQuery } from "./queries";

const home: MarketHome = {
  connection: {
    provider_id: "eastmoney",
    sdk_configured: true,
    token_configured: true,
    state: "LIVE",
    connected_at: "2026-08-06T09:30:00+08:00",
    last_event_at: "2026-08-06T10:02:00+08:00",
    error_code: null,
    instrument_count: 7,
    parse_error_count: 0,
    reconnect_count: 0,
  },
  core_indices: [],
  watchlist: [],
  selected_instrument: null,
  breadth: { status: "UNAVAILABLE", reason: "not connected" },
  intelligence: { status: "UNAVAILABLE", reason: "not connected" },
  candidates: [],
  as_of: "2026-08-06T10:02:00+08:00",
};

it("refreshes the live in-memory market snapshot after about one second", async () => {
  const getMarketHome = vi.fn().mockResolvedValue(home);
  const client = { getMarketHome } as unknown as ApiClient;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  renderHook(() => useMarketHomeQuery(client, "LIVE"), {
    wrapper: ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    ),
  });

  await waitFor(() => expect(getMarketHome).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(getMarketHome.mock.calls.length).toBeGreaterThanOrEqual(2), {
    timeout: 1_800,
  });
});
