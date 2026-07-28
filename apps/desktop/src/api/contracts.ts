export type TaskStatus =
  | "PENDING"
  | "RUNNING"
  | "CANCEL_REQUESTED"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELED"
  | "INTERRUPTED";

export const ACTIVE_TASK_STATUSES = [
  "PENDING",
  "RUNNING",
  "CANCEL_REQUESTED",
] as const satisfies readonly TaskStatus[];

export interface RuntimeConnection {
  base_url: string;
  protocol_version: number;
  session_token: string;
}

export interface Health {
  status: "ok";
  protocol_version: 1;
  service_version: string;
}

export interface Runtime {
  active_workers: number;
  database_size_bytes: number;
  shutting_down: boolean;
}

export interface Task {
  task_id: string;
  task_type: "demo.self_check" | "data.import";
  status: TaskStatus;
  progress: number;
  current_step: string;
  correlation_id: string;
  worker_pid: number | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  result: Record<string, unknown> | null;
  error_code: string | null;
  error_message: string | null;
  revision: number;
}

export interface ActivityItem {
  timestamp: string;
  level: string;
  event: string;
  component: string | null;
  correlation_id: string | null;
  task_id: string | null;
}

export type ThemeName = "astra-minimal" | "astra-light";
export type BackgroundEffect = "none" | "nebula" | "grid";

export interface Settings {
  theme: ThemeName;
  reduced_motion: boolean;
  sidebar_collapsed: boolean;
  background_effect: BackgroundEffect;
}

export interface ApiProblem {
  code: string;
  message: string;
}

export function isTaskActive(task: Task): boolean {
  return (ACTIVE_TASK_STATUSES as readonly TaskStatus[]).includes(task.status);
}
