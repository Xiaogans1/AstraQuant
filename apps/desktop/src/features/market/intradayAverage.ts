import type { IndicatorTemplate, KLineData } from "klinecharts";

export interface IntradayAverageValue {
  average?: number;
}

export function calculateIntradayAverage(
  bars: KLineData[],
): IntradayAverageValue[] {
  let cumulativeTurnover = 0;
  let cumulativeVolume = 0;
  return bars.map((bar) => {
    const volume = finitePositive(bar.volume) ?? 0;
    if (volume > 0) {
      const typicalPrice = (bar.high + bar.low + bar.close) / 3;
      cumulativeTurnover += finitePositive(bar.turnover) ?? typicalPrice * volume;
      cumulativeVolume += volume;
    }
    return cumulativeVolume > 0
      ? { average: cumulativeTurnover / cumulativeVolume }
      : {};
  });
}

export const intradayAverageIndicator: IndicatorTemplate<IntradayAverageValue> = {
  name: "AVG",
  shortName: "均价",
  series: "price",
  precision: 4,
  shouldOhlc: true,
  figures: [{
    key: "average",
    title: "均价: ",
    type: "line",
    styles: () => ({
      color: "#d6a11d",
      size: 1.5,
    }),
  }],
  calc: calculateIntradayAverage,
};

function finitePositive(value: number | undefined): number | null {
  return value !== undefined && Number.isFinite(value) && value > 0
    ? value
    : null;
}

