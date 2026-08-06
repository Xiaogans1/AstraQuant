import { buildCrosshairQuote } from "./crosshairQuote";

it("formats the hovered price together with its gain from previous close", () => {
  expect(buildCrosshairQuote(0.703, 0.698, 4)).toEqual({
    priceText: "0.7030",
    changeText: "+0.72%",
    direction: "up",
  });
});

it("marks a hovered price below previous close as a loss", () => {
  expect(buildCrosshairQuote(9.8, 10, 2)).toEqual({
    priceText: "9.80",
    changeText: "-2.00%",
    direction: "down",
  });
});

it("keeps the price but omits change when previous close is unavailable", () => {
  expect(buildCrosshairQuote(12.345, null, 3)).toEqual({
    priceText: "12.345",
    changeText: null,
    direction: "flat",
  });
  expect(buildCrosshairQuote(12.345, 0, 3).changeText).toBeNull();
});

it("rejects a non-finite hovered price", () => {
  expect(() => buildCrosshairQuote(Number.NaN, 10, 2)).toThrow(
    "Crosshair price must be finite",
  );
});
