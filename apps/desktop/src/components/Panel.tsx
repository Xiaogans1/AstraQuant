import type {
  HTMLAttributes,
  ReactNode,
} from "react";

interface PanelProps extends HTMLAttributes<HTMLElement> {
  title?: string;
  eyebrow?: string;
  action?: ReactNode;
  children: ReactNode;
}

export function Panel({
  title,
  eyebrow,
  action,
  children,
  className = "",
  ...props
}: PanelProps) {
  return (
    <section className={`panel ${className}`.trim()} {...props}>
      {title !== undefined || eyebrow !== undefined || action !== undefined ? (
        <header className="panel__header">
          <div>
            {eyebrow !== undefined ? (
              <p className="panel__eyebrow">{eyebrow}</p>
            ) : null}
            {title !== undefined ? <h2 className="panel__title">{title}</h2> : null}
          </div>
          {action !== undefined ? (
            <div className="panel__action">{action}</div>
          ) : null}
        </header>
      ) : null}
      <div className="panel__body">{children}</div>
    </section>
  );
}
