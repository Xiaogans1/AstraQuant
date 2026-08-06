import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { MarketPeriod } from "../api/market-contracts";
import {
  MarketChartToolbar,
  type MarketIndicator,
} from "./MarketChartToolbar";

function ToolbarFixture() {
  const [period, setPeriod] = useState<MarketPeriod>("intraday");
  const [indicator, setIndicator] = useState<MarketIndicator>("MA");
  const [fullscreen, setFullscreen] = useState(false);
  return (
    <MarketChartToolbar
      period={period}
      indicator={indicator}
      fullscreen={fullscreen}
      onPeriodChange={setPeriod}
      onIndicatorChange={setIndicator}
      onToggleFullscreen={() => setFullscreen((value) => !value)}
    />
  );
}

it("keeps minute periods inside a secondary menu", async () => {
  const user = userEvent.setup();
  render(<ToolbarFixture />);

  for (const label of ["分时", "日K", "周K", "月K", "年K"]) {
    expect(screen.getByRole("button", { name: label })).toBeVisible();
  }
  expect(screen.queryByRole("button", { name: "5分" })).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "周期" }));
  await user.click(screen.getByRole("menuitem", { name: "5分" }));

  expect(screen.getByRole("button", { name: "周期：5分" })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
  expect(screen.getByRole("button", { name: "周期：5分" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

it("offers indicators and fullscreen without crowding the primary periods", async () => {
  const user = userEvent.setup();
  render(<ToolbarFixture />);

  await user.click(screen.getByRole("button", { name: "指标：MA" }));
  for (const label of ["MA", "BOLL", "MACD", "KDJ", "RSI"]) {
    expect(screen.getByRole("menuitem", { name: label })).toBeVisible();
  }
  await user.click(screen.getByRole("menuitem", { name: "MACD" }));
  expect(screen.getByRole("button", { name: "指标：MACD" })).toBeVisible();

  await user.click(screen.getByRole("button", { name: "进入图表全屏" }));
  expect(screen.getByRole("button", { name: "退出图表全屏" })).toBeVisible();
});

it("closes an open menu with Escape", async () => {
  const user = userEvent.setup();
  render(<ToolbarFixture />);

  await user.click(screen.getByRole("button", { name: "周期" }));
  expect(screen.getByRole("menuitem", { name: "1分" })).toBeVisible();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("menuitem", { name: "1分" })).not.toBeInTheDocument();
});
