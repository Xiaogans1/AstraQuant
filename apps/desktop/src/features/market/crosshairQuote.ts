export interface CrosshairQuote {
  priceText: string;
  changeText: string | null;
  direction: "up" | "down" | "flat";
}

export function buildCrosshairQuote(
  price: number,
  previousClose: number | null,
  precision: number,
): CrosshairQuote {
  if (!Number.isFinite(price)) {
    throw new Error("Crosshair price must be finite");
  }
  const priceText = price.toFixed(precision);
  if (
    previousClose === null
    || !Number.isFinite(previousClose)
    || previousClose <= 0
  ) {
    return { priceText, changeText: null, direction: "flat" };
  }
  const changePercent = ((price / previousClose) - 1) * 100;
  const direction =
    changePercent > 0 ? "up" : changePercent < 0 ? "down" : "flat";
  return {
    priceText,
    changeText: `${changePercent >= 0 ? "+" : ""}${changePercent.toFixed(2)}%`,
    direction,
  };
}
