import type {
  ActivityItem,
  Runtime,
  Task,
} from "../api/contracts";
import { isTaskActive } from "../api/contracts";
import { ActivityFeed } from "../components/ActivityFeed";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";
import { RuntimeCard } from "../components/RuntimeCard";
import { TaskProgress } from "../components/TaskProgress";

interface OverviewPageProps {
  runtime: Runtime;
  tasks: Task[];
  activity: ActivityItem[];
  isStale: boolean;
  creating: boolean;
  cancelingTaskId: string | null;
  onCreateDemoTask: (idempotencyKey: string) => void;
  onCancelTask: (taskId: string) => void;
}

export function OverviewPage({
  runtime,
  tasks,
  activity,
  isStale,
  creating,
  cancelingTaskId,
  onCreateDemoTask,
  onCancelTask,
}: OverviewPageProps) {
  const activeTask = tasks.find(isTaskActive);
  const today = new Date().toLocaleDateString("sv-SE");
  const todayTaskCount = tasks.filter((task) =>
    task.created_at.startsWith(today),
  ).length;

  return (
    <div className="page-stack">
      {isStale ? (
        <div className="stale-banner" role="status">
          <strong>本地服务连接已过期</strong>
          <span>当前画面仅供查看。</span>
        </div>
      ) : null}
      <div className="runtime-grid">
        <RuntimeCard
          label="本地服务"
          value={runtime.shutting_down ? "正在关闭" : "在线"}
          detail="127.0.0.1 / 当前会话"
          tone={runtime.shutting_down ? "warning" : "accent"}
        />
        <RuntimeCard
          label="活动 Worker"
          value={String(runtime.active_workers)}
          detail="独立进程执行"
        />
        <RuntimeCard
          label="今日任务"
          value={String(todayTaskCount)}
          detail={`历史共 ${tasks.length} 项`}
        />
        <RuntimeCard
          label="状态库"
          value={formatBytes(runtime.database_size_bytes)}
          detail="SQLite / 仅本机"
        />
      </div>

      <div className="overview-grid">
        <Panel
          title="当前任务"
          eyebrow="EXECUTION"
          action={
            <button
              className="button button--primary"
              type="button"
              disabled={isStale || creating || runtime.shutting_down}
              onClick={() => onCreateDemoTask(crypto.randomUUID())}
            >
              {creating ? "正在创建…" : "运行示例任务"}
            </button>
          }
        >
          {activeTask === undefined ? (
            <EmptyState
              title="执行通道空闲"
              description="运行示例任务，验证桌面、API、Worker 与 SQLite 的完整本地闭环。"
            />
          ) : (
            <div className="active-task">
              <div className="active-task__identity">
                <span className="status-chip" data-status={activeTask.status}>
                  {statusLabel(activeTask.status)}
                </span>
                <code>{activeTask.task_id}</code>
              </div>
              <TaskProgress task={activeTask} />
              <button
                className="button button--danger"
                type="button"
                disabled={isStale || cancelingTaskId === activeTask.task_id}
                onClick={() => onCancelTask(activeTask.task_id)}
              >
                {cancelingTaskId === activeTask.task_id ? "正在取消…" : "取消任务"}
              </button>
            </div>
          )}
        </Panel>
        <Panel title="最近活动" eyebrow="ACTIVITY / 05">
          <ActivityFeed items={activity} limit={5} />
        </Panel>
      </div>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function statusLabel(status: Task["status"]): string {
  const labels: Record<Task["status"], string> = {
    PENDING: "等待",
    RUNNING: "运行中",
    CANCEL_REQUESTED: "正在取消",
    SUCCEEDED: "已完成",
    FAILED: "任务失败",
    CANCELED: "已取消",
    INTERRUPTED: "已中断",
  };
  return labels[status];
}
