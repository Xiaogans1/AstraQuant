import { render, screen } from "@testing-library/react";

import type { Task } from "../api/contracts";
import { TasksPage } from "./TasksPage";

const baseTask: Task = {
  task_id: "task-1",
  task_type: "demo.self_check",
  status: "RUNNING",
  progress: 40,
  current_step: "checking",
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

it("offers cancel only for active tasks", () => {
  const succeededTask: Task = {
    ...baseTask,
    task_id: "succeeded-1",
    status: "SUCCEEDED",
    progress: 100,
    finished_at: "2026-07-27T00:00:03Z",
  };

  render(
    <TasksPage
      tasks={[baseTask, succeededTask]}
      isStale={false}
      cancelingTaskId={null}
      onCancelTask={vi.fn()}
    />,
  );

  expect(
    screen.getAllByRole("button", { name: "取消任务" }),
  ).toHaveLength(1);
});

it("shows interrupted recovery reason without treating it as failure", () => {
  const interruptedTask: Task = {
    ...baseTask,
    status: "INTERRUPTED",
    current_step: "interrupted",
    finished_at: "2026-07-27T00:00:03Z",
  };

  render(
    <TasksPage
      tasks={[interruptedTask]}
      isStale={false}
      cancelingTaskId={null}
      onCancelTask={vi.fn()}
    />,
  );

  expect(screen.getByText("服务重启时中断")).toBeVisible();
  expect(screen.queryByText("任务失败")).not.toBeInTheDocument();
});
