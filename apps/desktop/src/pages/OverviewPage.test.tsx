import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type {
  Runtime,
  Task,
} from "../api/contracts";
import { OverviewPage } from "./OverviewPage";

const runtimeFixture: Runtime = {
  active_workers: 0,
  database_size_bytes: 4096,
  shutting_down: false,
};

const runningTask: Task = {
  task_id: "running-1",
  task_type: "demo.self_check",
  status: "RUNNING",
  progress: 40,
  current_step: "checking_storage",
  correlation_id: "correlation-1",
  worker_pid: 4242,
  created_at: "2026-07-27T00:00:00Z",
  started_at: "2026-07-27T00:00:01Z",
  finished_at: null,
  result: null,
  error_code: null,
  error_message: null,
  revision: 2,
};

it("creates a demo task and exposes progress", async () => {
  const createDemoTask = vi.fn();
  render(
    <OverviewPage
      runtime={runtimeFixture}
      tasks={[runningTask]}
      activity={[]}
      isStale={false}
      creating={false}
      cancelingTaskId={null}
      onCreateDemoTask={createDemoTask}
      onCancelTask={vi.fn()}
    />,
  );

  await userEvent.click(
    screen.getByRole("button", { name: "运行示例任务" }),
  );

  expect(createDemoTask).toHaveBeenCalledTimes(1);
  expect(screen.getByText("40%")).toBeVisible();
  expect(screen.getByText("checking_storage")).toBeVisible();
});

it("disables mutations while service data is stale", () => {
  render(
    <OverviewPage
      runtime={runtimeFixture}
      tasks={[]}
      activity={[]}
      isStale
      creating={false}
      cancelingTaskId={null}
      onCreateDemoTask={vi.fn()}
      onCancelTask={vi.fn()}
    />,
  );

  expect(
    screen.getByRole("button", { name: "运行示例任务" }),
  ).toBeDisabled();
  expect(screen.getByText("本地服务连接已过期")).toBeVisible();
});
