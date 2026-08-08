import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ApiClient } from "../api/client";
import { InstrumentSearchPicker, type InstrumentSelection } from "./InstrumentSearchPicker";

function renderPicker(
  client: ApiClient,
  value: InstrumentSelection | null = null,
  onChange = vi.fn(),
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <InstrumentSearchPicker client={client} value={value} onChange={onChange} />
    </QueryClientProvider>,
  );
  return { onChange };
}

test("searches the real catalog and picks a normalized instrument", async () => {
  const user = userEvent.setup();
  const searchMarketInstruments = vi.fn().mockResolvedValue([
    { instrument_id: "159516.SZSE", name: "半导体设备ETF", kind: "etf" },
    { instrument_id: "588200.SSE", name: "半导体ETF", kind: "etf" },
  ]);
  const client = { searchMarketInstruments } as unknown as ApiClient;
  const { onChange } = renderPicker(client);

  await user.type(await screen.findByRole("searchbox", { name: "搜索证券" }), "159516");
  expect(searchMarketInstruments).toHaveBeenCalledWith("159516");
  await user.click(
    await screen.findByRole("button", { name: /半导体设备ETF.*159516\.SZSE.*选择/ }),
  );

  expect(onChange).toHaveBeenCalledWith({
    instrument_id: "159516.SZSE",
    name: "半导体设备ETF",
    kind: "etf",
  });
});

test("does not search or show results for a one-character query", async () => {
  const user = userEvent.setup();
  const searchMarketInstruments = vi.fn();
  const client = { searchMarketInstruments } as unknown as ApiClient;
  renderPicker(client);

  await user.type(await screen.findByRole("searchbox", { name: "搜索证券" }), "半");

  expect(searchMarketInstruments).not.toHaveBeenCalled();
  expect(screen.queryByText("选择")).not.toBeInTheDocument();
});

test("shows the selected instrument and offers changing it", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  const client = { searchMarketInstruments: vi.fn() } as unknown as ApiClient;
  renderPicker(
    client,
    { instrument_id: "600000.SSE", name: "浦发银行", kind: "equity" },
    onChange,
  );

  expect(screen.getByText("浦发银行")).toBeVisible();
  expect(screen.getByText("600000.SSE")).toBeVisible();
  expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "更换" }));
  expect(onChange).toHaveBeenCalledWith(null);
});

test("shows a Chinese error message when the catalog search fails", async () => {
  const user = userEvent.setup();
  const client = {
    searchMarketInstruments: vi.fn().mockRejectedValue(new Error("SDK call failed")),
  } as unknown as ApiClient;
  renderPicker(client);

  await user.type(await screen.findByRole("searchbox", { name: "搜索证券" }), "半导体");

  expect(await screen.findByText("证券目录搜索失败，请稍后重试")).toBeVisible();
  expect(screen.queryByText("SDK call failed")).not.toBeInTheDocument();
});

test("shows an honest empty state when nothing matches", async () => {
  const user = userEvent.setup();
  const client = {
    searchMarketInstruments: vi.fn().mockResolvedValue([]),
  } as unknown as ApiClient;
  renderPicker(client);

  await user.type(await screen.findByRole("searchbox", { name: "搜索证券" }), "zzz");

  expect(await screen.findByText("没有找到可订阅证券")).toBeVisible();
});
