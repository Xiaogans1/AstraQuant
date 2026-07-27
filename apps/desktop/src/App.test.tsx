import { render, screen } from "@testing-library/react";

import { App } from "./App";

vi.mock("./runtime/tauri", () => ({
  getRuntimeConnection: vi.fn().mockResolvedValue({
    base_url: "http://127.0.0.1:43127",
    protocol_version: 1,
    session_token: "session-token",
  }),
  openLogDirectory: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("./api/client", () => ({
  ApiClient: class {
    getHealth = vi.fn().mockResolvedValue({
      status: "ok",
      protocol_version: 1,
      service_version: "0.1.0",
    });
    getRuntime = vi.fn().mockResolvedValue({
      active_workers: 0,
      database_size_bytes: 0,
      shutting_down: false,
    });
    listTasks = vi.fn().mockResolvedValue([]);
    listActivity = vi.fn().mockResolvedValue([]);
    getSettings = vi.fn().mockResolvedValue({
      theme: "astra-minimal",
      reduced_motion: false,
      sidebar_collapsed: false,
      background_effect: "nebula",
    });
  },
}));

it("renders the responsive workspace shell", async () => {
  render(<App />);
  expect(
    await screen.findByRole("banner", { name: "AstraQuant 状态栏" }),
  ).toHaveTextContent("AstraQuant");
  expect(
    screen.getByRole("navigation", { name: "工作区导航" }),
  ).toBeVisible();
  expect(screen.getByRole("button", { name: "总览" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});
