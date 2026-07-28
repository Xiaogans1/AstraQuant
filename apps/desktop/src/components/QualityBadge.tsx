import type { QualityIssue } from "../api/data-contracts";

export function QualityBadge({ issue }: { issue: QualityIssue }) {
  const isError = issue.severity === "ERROR";
  return (
    <span className="quality-badge" data-severity={issue.severity}>
      {isError ? "× 错误" : "△ 警告"}
    </span>
  );
}
