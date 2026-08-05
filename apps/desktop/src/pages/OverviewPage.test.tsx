import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { OverviewPage } from "./OverviewPage";

function renderMarketHome() {
  render(<OverviewPage />);
}

it("presents the homepage as a simulated read-only market terminal", () => {
  renderMarketHome();

  expect(screen.getByRole("heading", { name: "市场首页" })).toBeVisible();
  expect(screen.getByText("开发模拟行情")).toBeVisible();
  expect(screen.getByText("只读观察 · 不连接实盘账户")).toBeVisible();
  expect(screen.getByText("AI 情报未接入")).toBeVisible();
  expect(screen.getByText("模拟盘口")).toBeVisible();
  expect(screen.getByText("上证指数")).toBeVisible();
  expect(screen.getByRole("table", { name: "我的自选" })).toBeVisible();
});

it("switches the intraday workspace when a watchlist instrument is selected", async () => {
  const user = userEvent.setup();
  renderMarketHome();

  await user.click(screen.getByRole("button", { name: /查看科创50ETF/ }));

  expect(
    screen.getByRole("heading", { name: "科创50ETF · 588000.SSE" }),
  ).toBeVisible();
  expect(screen.getByRole("button", { name: /查看科创50ETF/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(
    screen.getByRole("img", { name: "科创50ETF分时图" }),
  ).toBeVisible();
  expect(screen.getAllByText("等待确认")).not.toHaveLength(0);
});

it("adds a domestic future from the catalog to the session watchlist", async () => {
  const user = userEvent.setup();
  renderMarketHome();

  await user.type(screen.getByRole("searchbox", { name: "添加自选" }), "IF");
  await user.click(screen.getByRole("button", { name: "添加沪深300股指" }));

  expect(screen.getByRole("button", { name: /查看沪深300股指/ })).toBeVisible();
  expect(screen.getByText("已加入本次会话的自选列表")).toBeVisible();
});
