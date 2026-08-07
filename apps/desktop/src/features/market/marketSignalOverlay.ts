export interface MarketSignalMarker {
  id: string;
  timestamp: number;
  side: "BUY" | "SELL";
  price: number;
  label: string;
  source: "QUANT" | "PAPER_FILL";
}

export interface MarketSignalOverlay {
  id: string;
  timestamp: number;
  price: number;
  tag: "B" | "S";
  label: string;
  side: "BUY" | "SELL";
}

export function toSignalOverlays(
  signals: MarketSignalMarker[],
): MarketSignalOverlay[] {
  return signals.map((signal) => ({
    id: signal.id,
    timestamp: signal.timestamp,
    price: signal.price,
    tag: signal.side === "BUY" ? "B" : "S",
    label: signal.label,
    side: signal.side,
  }));
}
