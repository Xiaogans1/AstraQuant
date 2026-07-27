import type {
  BackgroundEffect,
  ThemeName as ContractThemeName,
} from "../api/contracts";

export type ThemeName = ContractThemeName;

export const SUPPORTED_THEMES = [
  "astra-minimal",
  "astra-light",
] as const satisfies readonly ThemeName[];

export const SAFETY_TOKEN_NAMES = [
  "--safety-live",
  "--safety-paper",
  "--safety-risk",
  "--safety-buy",
  "--safety-sell",
  "--safety-emergency",
] as const;

export function applyTheme(theme: ThemeName): void {
  if (!(SUPPORTED_THEMES as readonly string[]).includes(theme)) {
    throw new Error(`Unsupported theme: ${theme}`);
  }
  document.documentElement.dataset.theme = theme;
}

export function applyReducedMotion(reducedMotion: boolean): void {
  document.documentElement.dataset.reducedMotion = String(reducedMotion);
}

export function applyBackgroundEffect(effect: BackgroundEffect): void {
  document.documentElement.dataset.backgroundEffect = effect;
}
