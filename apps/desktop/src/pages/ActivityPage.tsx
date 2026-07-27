import type { ActivityItem } from "../api/contracts";
import { ActivityFeed } from "../components/ActivityFeed";
import { Panel } from "../components/Panel";

export function ActivityPage({
  activity,
  onOpenLogs,
}: {
  activity: ActivityItem[];
  onOpenLogs: () => void;
}) {
  return (
    <Panel
      title="结构化活动"
      eyebrow="LOCAL / REDACTED"
      action={
        <button className="button" type="button" onClick={onOpenLogs}>
          打开日志目录
        </button>
      }
    >
      <ActivityFeed items={activity} />
    </Panel>
  );
}
