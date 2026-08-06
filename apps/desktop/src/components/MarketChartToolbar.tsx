import { useEffect, useState } from "react";

import type { MarketPeriod } from "../api/market-contracts";

export type MarketIndicator = "MA" | "BOLL" | "MACD" | "KDJ" | "RSI";

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

const indicators: MarketIndicator[] = ["MA", "BOLL", "MACD", "KDJ", "RSI"];

interface MarketChartToolbarProps {
  period: MarketPeriod;
  indicator: MarketIndicator;
  fullscreen: boolean;
  onPeriodChange: (period: MarketPeriod) => void;
  onIndicatorChange: (indicator: MarketIndicator) => void;
  onToggleFullscreen: () => void;
}

export function MarketChartToolbar({
  period,
  indicator,
  fullscreen,
  onPeriodChange,
  onIndicatorChange,
  onToggleFullscreen,
}: MarketChartToolbarProps) {
  const [openMenu, setOpenMenu] = useState<"period" | "indicator" | null>(null);
  const selectedMinute = minutePeriods.find((item) => item.period === period);

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
            aria-expanded={openMenu === "indicator"}
            onClick={() =>
              setOpenMenu((value) => value === "indicator" ? null : "indicator")
            }
          >
            指标：{indicator}
          </button>
          {openMenu === "indicator" ? (
            <div className="market-chart-menu__popover" role="menu" aria-label="技术指标">
              {indicators.map((item) => (
                <button
                  key={item}
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    onIndicatorChange(item);
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
          aria-label={fullscreen ? "退出图表全屏" : "进入图表全屏"}
          onClick={onToggleFullscreen}
        >
          {fullscreen ? "退出全屏" : "全屏"}
        </button>
      </div>
    </div>
  );
}
