import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { MarketPeriod } from "../api/market-contracts";
import {
  MarketChartToolbar,
  type MainChartIndicator,
  type SecondaryChartIndicator,
} from "./MarketChartToolbar";

function ToolbarFixture() {
  const [period, setPeriod] = useState<MarketPeriod>("intraday");
  const [mainIndicator, setMainIndicator] = useState<MainChartIndicator>("AVG");
  const [secondaryIndicator, setSecondaryIndicator] =
    useState<SecondaryChartIndicator>("VOL");
  const [showQuantSignals, setShowQuantSignals] = useState(true);
  const [fullscreen, setFullscreen] = useState(false);
  const changePeriod = (nextPeriod: MarketPeriod) => {
    setPeriod(nextPeriod);
    setMainIndicator(nextPeriod === "intraday" ? "AVG" : "MA");
  };
  return (
    <MarketChartToolbar
      period={period}
      mainIndicator={mainIndicator}
      secondaryIndicator={secondaryIndicator}
      showQuantSignals={showQuantSignals}
      fullscreen={fullscreen}
      onPeriodChange={changePeriod}
      onMainIndicatorChange={setMainIndicator}
      onSecondaryIndicatorChange={setSecondaryIndicator}
      onToggleQuantSignals={() => setShowQuantSignals((value) => !value)}
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

it("separates intraday main, secondary and quant layers", async () => {
  const user = userEvent.setup();
  render(<ToolbarFixture />);

  expect(screen.getByRole("button", { name: "主图：均价" })).toBeVisible();
  expect(screen.getByRole("button", { name: "副图：VOL" })).toBeVisible();
  expect(screen.getByRole("button", { name: "量化图层" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  await user.click(screen.getByRole("button", { name: "主图：均价" }));
  for (const label of ["均价", "无"]) {
    expect(screen.getByRole("menuitem", { name: label })).toBeVisible();
  }
  expect(screen.queryByRole("menuitem", { name: "BOLL" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("menuitem", { name: "无" }));
  expect(screen.getByRole("button", { name: "主图：无" })).toBeVisible();

  await user.click(screen.getByRole("button", { name: "副图：VOL" }));
  for (const label of ["VOL", "MACD", "KDJ", "RSI"]) {
    expect(screen.getByRole("menuitem", { name: label })).toBeVisible();
  }
  await user.click(screen.getByRole("menuitem", { name: "MACD" }));
  expect(screen.getByRole("button", { name: "副图：MACD" })).toBeVisible();

  await user.click(screen.getByRole("button", { name: "量化图层" }));
  expect(screen.getByRole("button", { name: "量化图层" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  await user.click(screen.getByRole("button", { name: "进入图表全屏" }));
  expect(screen.getByRole("button", { name: "退出图表全屏" })).toBeVisible();
});

it("offers MA and BOLL only for candle periods", async () => {
  const user = userEvent.setup();
  render(<ToolbarFixture />);

  await user.click(screen.getByRole("button", { name: "日K" }));
  expect(screen.getByRole("button", { name: "主图：MA" })).toBeVisible();
  await user.click(screen.getByRole("button", { name: "主图：MA" }));

  for (const label of ["MA", "BOLL", "无"]) {
    expect(screen.getByRole("menuitem", { name: label })).toBeVisible();
  }
  expect(screen.queryByRole("menuitem", { name: "均价" })).not.toBeInTheDocument();
});

it("closes an open menu with Escape", async () => {
  const user = userEvent.setup();
  render(<ToolbarFixture />);

  await user.click(screen.getByRole("button", { name: "周期" }));
  expect(screen.getByRole("menuitem", { name: "1分" })).toBeVisible();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("menuitem", { name: "1分" })).not.toBeInTheDocument();
});
