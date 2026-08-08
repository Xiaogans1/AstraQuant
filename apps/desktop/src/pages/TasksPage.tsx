import { useState } from "react";

import type {
  Task,
  TaskStatus,
} from "../api/contracts";
import { isTaskActive } from "../api/contracts";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";
import { TaskProgress } from "../components/TaskProgress";

type TaskFilter = "all" | "active" | "terminal";

interface TasksPageProps {
  tasks: Task[];
  isStale: boolean;
  cancelingTaskId: string | null;
  onCancelTask: (taskId: string) => void;
}

export function TasksPage({
  tasks,
  isStale,
  cancelingTaskId,
  onCancelTask,
}: TasksPageProps) {
  const [filter, setFilter] = useState<TaskFilter>("all");
  const filteredTasks = tasks.filter((task) => {
    if (filter === "active") {
      return isTaskActive(task);
    }
    if (filter === "terminal") {
      return !isTaskActive(task);
    }
    return true;
  });

  return (
    <Panel
      title="任务记录"
      eyebrow={`${tasks.length} TOTAL`}
      action={
        <div className="segmented-control" aria-label="任务状态筛选">
          {(["all", "active", "terminal"] as const).map((value) => (
            <button
              type="button"
              key={value}
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
            >
              {{ all: "全部", active: "活动", terminal: "已结束" }[value]}
            </button>
          ))}
        </div>
      }
    >
      {filteredTasks.length === 0 ? (
        <EmptyState
          title="没有符合条件的任务"
          description="调整筛选条件，或从总览运行一个示例任务。"
        />
      ) : (
        <div className="task-list">
          {filteredTasks.map((task) => (
            <TaskRow
              key={task.task_id}
              task={task}
              isStale={isStale}
              canceling={cancelingTaskId === task.task_id}
              onCancelTask={onCancelTask}
            />
          ))}
        </div>
      )}
    </Panel>
  );
}

function TaskRow({
  task,
  isStale,
  canceling,
  onCancelTask,
}: {
  task: Task;
  isStale: boolean;
  canceling: boolean;
  onCancelTask: (taskId: string) => void;
}) {
  const cancelable = task.status === "PENDING" || task.status === "RUNNING";
  return (
    <details className="task-row">
      <summary>
        <span className="status-chip" data-status={task.status}>
          {taskStatusLabel(task.status)}
        </span>
        <span className="task-row__main">
          <strong>示例自检任务</strong>
          <code>{task.task_id}</code>
        </span>
        <span className="task-row__progress">{task.progress}%</span>
        <time dateTime={task.created_at}>{formatDate(task.created_at)}</time>
      </summary>
      <div className="task-row__details">
        <TaskProgress task={task} />
        <dl className="task-metadata">
          <div>
            <dt>Task ID</dt>
            <dd><code>{task.task_id}</code></dd>
          </div>
          <div>
            <dt>Correlation ID</dt>
            <dd><code>{task.correlation_id}</code></dd>
          </div>
          <div>
            <dt>Worker PID</dt>
            <dd>{task.worker_pid ?? "—"}</dd>
          </div>
          <div>
            <dt>Revision</dt>
            <dd>{task.revision}</dd>
          </div>
        </dl>
        {task.result !== null ? (
          <p className="task-result">
            自检完成：{String(task.result.checks ?? "—")} 项检查通过
          </p>
        ) : null}
        {task.status === "FAILED" ? (
          <p className="task-error">任务失败：{task.error_message ?? "请查看本地日志"}</p>
        ) : null}
        {cancelable ? (
          <button
            className="button button--danger"
            type="button"
            disabled={isStale || canceling}
            onClick={() => onCancelTask(task.task_id)}
          >
            {canceling ? "正在取消…" : "取消任务"}
          </button>
        ) : null}
      </div>
    </details>
  );
}

function taskStatusLabel(status: TaskStatus): string {
  return {
    PENDING: "等待",
    RUNNING: "运行中",
    CANCEL_REQUESTED: "正在取消",
    SUCCEEDED: "已完成",
    FAILED: "任务失败",
    CANCELED: "已取消",
    INTERRUPTED: "服务重启时中断",
  }[status];
}

function formatDate(timestamp: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(timestamp));
}
