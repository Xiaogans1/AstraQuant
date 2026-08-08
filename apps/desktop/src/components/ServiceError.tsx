interface ServiceErrorProps {
  title?: string;
  message: string;
  onRetry: () => void;
  onOpenLogs: () => void;
}

export function ServiceError({
  title = "本地服务暂时不可用",
  message,
  onRetry,
  onOpenLogs,
}: ServiceErrorProps) {
  return (
    <main className="service-error">
      <div className="service-error__signal" aria-hidden="true">
        !
      </div>
      <p className="panel__eyebrow">LOCAL RUNTIME</p>
      <h1>{title}</h1>
      <p>{message}</p>
      <div className="service-error__actions">
        <button className="button button--primary" type="button" onClick={onRetry}>
          重新连接
        </button>
        <button className="button" type="button" onClick={onOpenLogs}>
          打开日志目录
        </button>
      </div>
    </main>
  );
}
