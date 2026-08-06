import type { MarketBar, QuoteCard } from "../../api/market-contracts";

const minuteFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

const dateFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

export function mergeLiveQuoteIntoIntradayBars(
  bars: MarketBar[],
  quote: QuoteCard,
): MarketBar[] {
  const lastBar = bars.at(-1);
  const price = Number(quote.last_price);
  const eventTime = quote.event_time === null ? null : new Date(quote.event_time);
  if (
    lastBar === undefined
    || !Number.isFinite(price)
    || price <= 0
    || eventTime === null
    || !Number.isFinite(eventTime.getTime())
    || !isTradingMinute(eventTime)
  ) {
    return bars;
  }

  const lastTimestamp = new Date(lastBar.timestamp);
  if (
    !Number.isFinite(lastTimestamp.getTime())
    || dateFormatter.format(lastTimestamp) !== dateFormatter.format(eventTime)
  ) {
    return bars;
  }

  const quoteMinute = floorToMinute(eventTime.getTime());
  const lastMinute = floorToMinute(lastTimestamp.getTime());
  if (quoteMinute < lastMinute) {
    return bars;
  }
  if (quoteMinute === lastMinute) {
    const nextHigh = Math.max(lastBar.high, price);
    const nextLow = Math.min(lastBar.low, price);
    if (lastBar.close === price && lastBar.high === nextHigh && lastBar.low === nextLow) {
      return bars;
    }
    return [
      ...bars.slice(0, -1),
      {
        ...lastBar,
        high: nextHigh,
        low: nextLow,
        close: price,
      },
    ];
  }

  return [
    ...bars,
    {
      timestamp: new Date(quoteMinute).toISOString(),
      open: price,
      high: price,
      low: price,
      close: price,
      volume: 0,
      turnover: 0,
      previous_close: positiveNumber(quote.previous_close) ?? lastBar.previous_close,
    },
  ];
}

function floorToMinute(timestamp: number): number {
  return Math.floor(timestamp / 60_000) * 60_000;
}

function positiveNumber(value: string | null): number | null {
  if (value === null) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function isTradingMinute(value: Date): boolean {
  const parts = minuteFormatter.formatToParts(value);
  const hour = Number(parts.find((part) => part.type === "hour")?.value);
  const minute = Number(parts.find((part) => part.type === "minute")?.value);
  if (!Number.isInteger(hour) || !Number.isInteger(minute)) return false;
  const minuteOfDay = hour * 60 + minute;
  return (
    (minuteOfDay >= 9 * 60 + 30 && minuteOfDay <= 11 * 60 + 30)
    || (minuteOfDay >= 13 * 60 && minuteOfDay <= 15 * 60)
  );
}
