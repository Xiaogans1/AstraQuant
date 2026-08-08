import {
  SAFETY_TOKEN_NAMES,
  applyTheme,
} from "./theme";
import type { ThemeName } from "./theme";

it("applies only supported themes", () => {
  applyTheme("astra-light");
  expect(document.documentElement.dataset.theme).toBe("astra-light");
  expect(() => applyTheme("unknown" as ThemeName)).toThrow("Unsupported theme");
});

it("keeps safety tokens outside theme overrides", () => {
  expect(SAFETY_TOKEN_NAMES).toEqual([
    "--safety-live",
    "--safety-paper",
    "--safety-risk",
    "--safety-buy",
    "--safety-sell",
    "--safety-emergency",
  ]);
});
