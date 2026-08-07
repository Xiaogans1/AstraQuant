import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

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
    listDatasets = vi.fn().mockResolvedValue([]);
    listSnapshots = vi.fn().mockResolvedValue([]);
    listBars = vi.fn().mockResolvedValue([]);
    listPaperAccounts = vi.fn().mockResolvedValue([]);
    ensureDefaultPaperAccount = vi.fn().mockResolvedValue({
      account: {
        account_id: "default-paper-account",
        name: "主模拟账户",
        mode: "PAPER",
        initial_cash: "100000",
        cash: "100000",
        created_at: "2026-08-06T06:30:00Z",
        updated_at: "2026-08-06T06:30:00Z",
      },
      positions: [],
      latest_equity: null,
    });
    createDataImport = vi.fn();
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
  expect(screen.getByRole("button", { name: "市场首页" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(screen.getByRole("button", { name: "策略实验室" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Paper 模拟" })).toBeEnabled();
});

it("opens the Paper account workspace", async () => {
  render(<App />);

  await userEvent.click(
    await screen.findByRole("button", { name: "Paper 模拟" }),
  );

  expect(await screen.findByText("主模拟账户")).toBeVisible();
});

it("opens the enabled local data center", async () => {
  render(<App />);

  const dataButton = await screen.findByRole("button", { name: "数据与连接" });
  expect(dataButton).toBeEnabled();
  await userEvent.click(dataButton);

  expect(
    await screen.findByRole("heading", { name: "数据只保存在本机" }),
  ).toBeVisible();
  expect(screen.getByText("不包含账户或下单连接")).toBeVisible();
});

it("keeps local operations pages reachable after the market-first navigation change", async () => {
  const user = userEvent.setup();
  render(<App />);

  await user.click(await screen.findByRole("button", { name: "任务" }));
  expect(screen.getByRole("heading", { name: "任务中心" })).toBeVisible();

  await user.click(screen.getByRole("button", { name: "本地活动" }));
  expect(screen.getByRole("heading", { name: "本地活动" })).toBeVisible();

  await user.click(screen.getByRole("button", { name: "设置" }));
  expect(screen.getByRole("heading", { name: "设置" })).toBeVisible();
});
