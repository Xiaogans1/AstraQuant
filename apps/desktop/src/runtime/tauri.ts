import { invoke } from "@tauri-apps/api/core";

import type { RuntimeConnection } from "../api/contracts";

export function getRuntimeConnection(): Promise<RuntimeConnection> {
  return invoke<RuntimeConnection>("runtime_connection");
}

export function openLogDirectory(): Promise<void> {
  return invoke<void>("open_log_directory");
}
