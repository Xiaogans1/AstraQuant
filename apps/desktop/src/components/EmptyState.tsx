import type { ReactNode } from "react";

interface EmptyStateProps {
  title: string;
  description: string;
  action?: ReactNode;
}

export function EmptyState({
  title,
  description,
  action,
}: EmptyStateProps) {
  return (
    <div className="empty-state">
      <div className="empty-state__orbit" aria-hidden="true">
        <span />
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      {action !== undefined ? (
        <div className="empty-state__action">{action}</div>
      ) : null}
    </div>
  );
}
