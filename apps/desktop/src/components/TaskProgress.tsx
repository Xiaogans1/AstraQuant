import type { Task } from "../api/contracts";

export function TaskProgress({ task }: { task: Task }) {
  return (
    <div className="task-progress">
      <div className="task-progress__header">
        <span>{task.current_step || "等待 Worker"}</span>
        <strong>{task.progress}%</strong>
      </div>
      <div
        className="task-progress__track"
        role="progressbar"
        aria-label="任务进度"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={task.progress}
      >
        <span style={{ width: `${task.progress}%` }} />
      </div>
    </div>
  );
}
