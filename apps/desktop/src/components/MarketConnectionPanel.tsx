import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { ApiClient } from "../api/client";
import type { ConnectionState } from "../api/market-contracts";
import {
  queryKeys,
  useMarketConnectionQuery,
  useStartMarketMutation,
  useStopMarketMutation,
} from "../api/queries";

const stateCopy: Record<ConnectionState, string> = {
  DISCONNECTED: "东财行情已停止",
  CONNECTING: "正在连接东财行情",
  LIVE: "东财实时行情已连接",
  STALE: "行情连接延迟",
  CLOSED: "市场已收盘",
  UNAVAILABLE: "尚未配置东财行情",
  ERROR: "东财行情连接异常",
};

export function MarketConnectionPanel({
  client,
  compact = false,
}: {
  client: ApiClient;
  compact?: boolean;
}) {
  const queryClient = useQueryClient();
  const connectionQuery = useMarketConnectionQuery(client);
  const start = useStartMarketMutation(client);
  const stop = useStopMarketMutation(client);
  const [sdkPythonPath, setSdkPythonPath] = useState(
    "D:\\AstraQuantData\\Eastmoney\\PythonSDK\\Scripts\\python.exe",
  );
  const [token, setToken] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const connection = connectionQuery.data;
  const state = connection?.state ?? "UNAVAILABLE";

  async function saveConfiguration() {
    setSaving(true);
    setMessage(null);
    try {
      await client.configureEastmoney({ sdk_python_path: sdkPythonPath, token });
      setToken("");
      await queryClient.invalidateQueries({ queryKey: queryKeys.marketConnection });
      await start.mutateAsync();
      setMessage("配置已安全保存，正在建立行情连接。\n");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "东财行情配置失败");
    } finally {
      setSaving(false);
    }
  }

  if (compact) {
    const compactLabel = state === "UNAVAILABLE"
      ? "尚未连接东财行情"
      : state === "STALE"
        ? "行情已延迟"
        : stateCopy[state];
    return (
      <div className="market-connection market-connection--compact" data-state={state}>
        <span className="market-connection__pulse" aria-hidden="true" />
        <strong>{compactLabel}</strong>
        {state !== "LIVE" && connection?.sdk_configured && connection.token_configured ? (
          <button type="button" className="button" onClick={() => start.mutate()}>
            重新连接
          </button>
        ) : null}
      </div>
    );
  }

  return (
    <section className="market-connection" data-state={state} aria-label="东财行情连接">
      <div className="market-connection__summary">
        <span className="market-connection__pulse" aria-hidden="true" />
        <div>
          <p className="panel__eyebrow">EASTMONEY / LOCAL BRIDGE</p>
          <h2>{stateCopy[state]}</h2>
          <p>
            {connection?.last_event_at
              ? `最近行情 ${formatTime(connection.last_event_at)}`
              : "只读行情，不连接或操作实盘账户"}
          </p>
        </div>
        {connection?.sdk_configured && connection.token_configured ? (
          state === "LIVE" || state === "CONNECTING" ? (
            <button type="button" className="button" onClick={() => stop.mutate()}>
              停止行情
            </button>
          ) : (
            <button type="button" className="button button--primary" onClick={() => start.mutate()}>
              连接行情
            </button>
          )
        ) : null}
      </div>

      {!connection?.sdk_configured || !connection.token_configured ? (
        <form
          className="market-connection__form"
          onSubmit={(event) => {
            event.preventDefault();
            void saveConfiguration();
          }}
        >
          <label>
            <span>SDK Python</span>
            <input
              value={sdkPythonPath}
              onChange={(event) => setSdkPythonPath(event.target.value)}
              autoComplete="off"
            />
          </label>
          <label>
            <span>东财 Token</span>
            <input
              aria-label="东财 Token"
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              autoComplete="off"
            />
          </label>
          <button className="button button--primary" type="submit" disabled={saving || token.length === 0}>
            {saving ? "正在验证…" : "保存并连接"}
          </button>
          <small>Token 仅写入 Windows 凭据管理器，不进入项目、日志或前端缓存。</small>
        </form>
      ) : null}
      {message ? <p className="form-message" role="status">{message}</p> : null}
    </section>
  );
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}
