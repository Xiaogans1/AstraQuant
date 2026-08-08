interface StatusRailProps {
  status?: "starting" | "online" | "offline";
  protocolVersion?: number;
}

const statusLabels = {
  starting: "正在连接",
  online: "本地服务在线",
  offline: "本地服务离线",
} as const;

export function StatusRail({
  status = "starting",
  protocolVersion,
}: StatusRailProps) {
  return (
    <header className="status-rail" aria-label="AstraQuant 状态栏">
      <div className="brand-lockup">
        <span className="brand-mark" aria-hidden="true">
          <span className="brand-mark__core" />
        </span>
        <span className="brand-name">AstraQuant</span>
        <span className="brand-edition">LOCAL DESK</span>
      </div>

      <div className="stellar-scale" aria-hidden="true">
        <span>09:30</span>
        <i />
        <span>11:30</span>
        <i />
        <span>15:00</span>
      </div>

      <div className="runtime-badge" data-status={status}>
        <span className="runtime-badge__dot" aria-hidden="true" />
        <span>{statusLabels[status]}</span>
        {protocolVersion !== undefined ? (
          <span className="runtime-badge__protocol">P{protocolVersion}</span>
        ) : null}
      </div>
    </header>
  );
}
