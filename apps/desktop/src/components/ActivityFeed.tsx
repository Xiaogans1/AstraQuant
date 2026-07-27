import type { ActivityItem } from "../api/contracts";
import { EmptyState } from "./EmptyState";

export function ActivityFeed({
  items,
  limit,
}: {
  items: ActivityItem[];
  limit?: number;
}) {
  const visibleItems = limit === undefined ? items : items.slice(0, limit);
  if (visibleItems.length === 0) {
    return (
      <EmptyState
        title="还没有本地活动"
        description="服务和任务事件出现后，会以脱敏摘要显示在这里。"
      />
    );
  }

  return (
    <ol className="activity-feed">
      {visibleItems.map((item, index) => (
        <li key={`${item.timestamp}-${item.event}-${index}`}>
          <time dateTime={item.timestamp}>{formatTime(item.timestamp)}</time>
          <span className="activity-feed__event">{item.event}</span>
          <span className="activity-feed__meta">
            {item.component ?? "runtime"}
            {item.task_id !== null ? ` · ${shortId(item.task_id)}` : ""}
          </span>
        </li>
      ))}
    </ol>
  );
}

function formatTime(timestamp: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(timestamp));
}

function shortId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 8)}…` : value;
}
