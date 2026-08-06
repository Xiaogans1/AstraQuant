import { useEffect, useState } from "react";

import type { MarketPeriod } from "../api/market-contracts";

export type MainChartIndicator = "AVG" | "MA" | "BOLL" | "NONE";
export type SecondaryChartIndicator = "VOL" | "MACD" | "KDJ" | "RSI";

const primaryPeriods: { period: MarketPeriod; label: string }[] = [
  { period: "intraday", label: "分时" },
  { period: "1d", label: "日K" },
  { period: "1w", label: "周K" },
  { period: "1mo", label: "月K" },
  { period: "1y", label: "年K" },
];

const minutePeriods: { period: MarketPeriod; label: string }[] = [
  { period: "1m", label: "1分" },
  { period: "5m", label: "5分" },
  { period: "15m", label: "15分" },
  { period: "30m", label: "30分" },
  { period: "60m", label: "60分" },
];

const intradayMainIndicators: MainChartIndicator[] = ["AVG", "NONE"];
const candleMainIndicators: MainChartIndicator[] = ["MA", "BOLL", "NONE"];
const secondaryIndicators: SecondaryChartIndicator[] = ["VOL", "MACD", "KDJ", "RSI"];
const mainIndicatorLabels: Record<MainChartIndicator, string> = {
  AVG: "均价",
  MA: "MA",
  BOLL: "BOLL",
  NONE: "无",
};

interface MarketChartToolbarProps {
  period: MarketPeriod;
  mainIndicator: MainChartIndicator;
  secondaryIndicator: SecondaryChartIndicator;
  showQuantSignals: boolean;
  fullscreen: boolean;
  onPeriodChange: (period: MarketPeriod) => void;
  onMainIndicatorChange: (indicator: MainChartIndicator) => void;
  onSecondaryIndicatorChange: (indicator: SecondaryChartIndicator) => void;
  onToggleQuantSignals: () => void;
  onToggleFullscreen: () => void;
}

export function MarketChartToolbar({
  period,
  mainIndicator,
  secondaryIndicator,
  showQuantSignals,
  fullscreen,
  onPeriodChange,
  onMainIndicatorChange,
  onSecondaryIndicatorChange,
  onToggleQuantSignals,
  onToggleFullscreen,
}: MarketChartToolbarProps) {
  const [openMenu, setOpenMenu] =
    useState<"period" | "main-indicator" | "secondary-indicator" | null>(null);
  const selectedMinute = minutePeriods.find((item) => item.period === period);
  const mainIndicators =
    period === "intraday" ? intradayMainIndicators : candleMainIndicators;

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpenMenu(null);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, []);

  return (
    <div className="market-chart-toolbar" aria-label="行情图表控制">
      <div className="market-chart-toolbar__primary">
        {primaryPeriods.map((item) => (
          <button
            key={item.period}
            type="button"
            aria-pressed={period === item.period}
            onClick={() => {
              onPeriodChange(item.period);
              setOpenMenu(null);
            }}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="market-chart-toolbar__secondary">
        <div className="market-chart-menu">
          <button
            type="button"
            aria-expanded={openMenu === "period"}
            aria-pressed={selectedMinute !== undefined}
            onClick={() => setOpenMenu((value) => value === "period" ? null : "period")}
          >
            {selectedMinute ? `周期：${selectedMinute.label}` : "周期"}
          </button>
          {openMenu === "period" ? (
            <div className="market-chart-menu__popover" role="menu" aria-label="分钟周期">
              {minutePeriods.map((item) => (
                <button
                  key={item.period}
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    onPeriodChange(item.period);
                    setOpenMenu(null);
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>
        <div className="market-chart-menu">
          <button
            type="button"
            aria-expanded={openMenu === "main-indicator"}
            onClick={() =>
              setOpenMenu((value) =>
                value === "main-indicator" ? null : "main-indicator"
              )
            }
          >
            主图：{mainIndicatorLabels[mainIndicator]}
          </button>
          {openMenu === "main-indicator" ? (
            <div className="market-chart-menu__popover" role="menu" aria-label="主图指标">
              {mainIndicators.map((item) => (
                <button
                  key={item}
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    onMainIndicatorChange(item);
                    setOpenMenu(null);
                  }}
                >
                  {mainIndicatorLabels[item]}
                </button>
              ))}
            </div>
          ) : null}
        </div>
        <div className="market-chart-menu">
          <button
            type="button"
            aria-expanded={openMenu === "secondary-indicator"}
            onClick={() =>
              setOpenMenu((value) =>
                value === "secondary-indicator" ? null : "secondary-indicator"
              )
            }
          >
            副图：{secondaryIndicator}
          </button>
          {openMenu === "secondary-indicator" ? (
            <div className="market-chart-menu__popover" role="menu" aria-label="副图指标">
              {secondaryIndicators.map((item) => (
                <button
                  key={item}
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    onSecondaryIndicatorChange(item);
                    setOpenMenu(null);
                  }}
                >
                  {item}
                </button>
              ))}
            </div>
          ) : null}
        </div>
        <button
          type="button"
          aria-pressed={showQuantSignals}
          onClick={onToggleQuantSignals}
        >
          量化图层
        </button>
        <button
          type="button"
          aria-label={fullscreen ? "退出图表全屏" : "进入图表全屏"}
          onClick={onToggleFullscreen}
        >
          {fullscreen ? "退出全屏" : "全屏"}
        </button>
      </div>
    </div>
  );
}
