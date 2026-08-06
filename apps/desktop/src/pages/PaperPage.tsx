import { useEffect, useMemo, useState } from "react";

import type { ApiClient } from "../api/client";
import {
  useAddPaperPositionMutation,
  useDefaultPaperAccountQuery,
  usePaperAccountQuery,
  usePaperAccountsQuery,
  usePaperEquityQuery,
  usePaperFillsQuery,
  usePaperOrdersQuery,
  useRunPaperStrategyMutation,
  useSubmitPaperOrderMutation,
} from "../api/queries";
import type {
  PaperAccountDetail,
  PaperAccountSummary,
  PaperEquity,
  PaperOrderSide,
} from "../api/paper-contracts";
import { Panel } from "../components/Panel";

export function PaperPage({ client }: { client: ApiClient }) {
  const defaultAccountQuery = useDefaultPaperAccountQuery(client);
  const accountsQuery = usePaperAccountsQuery(client, defaultAccountQuery.isSuccess);
  const fallbackAccount = defaultAccountQuery.data === undefined
    ? undefined
    : summarizeAccount(defaultAccountQuery.data);
  const accounts = accountsQuery.data !== undefined && accountsQuery.data.length > 0
    ? accountsQuery.data
    : fallbackAccount === undefined
      ? []
      : [fallbackAccount];
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null);

  useEffect(() => {
    if (selectedAccountId === null && accounts[0] !== undefined) {
      setSelectedAccountId(accounts[0].account_id);
    }
  }, [accounts, selectedAccountId]);

  if (defaultAccountQuery.isPending) {
    return <div className="paper-loading">正在读取本地模拟账本…</div>;
  }
  if (defaultAccountQuery.isError || accounts.length === 0) {
    return (
      <div className="paper-loading paper-loading--error">
        <strong>模拟账户暂时无法打开</strong>
        <span>{defaultAccountQuery.error instanceof Error ? defaultAccountQuery.error.message : "本地账本不可用"}</span>
        <button type="button" onClick={() => void defaultAccountQuery.refetch()}>重新读取</button>
      </div>
    );
  }
  return (
    <AccountWorkspace
      client={client}
      accountId={selectedAccountId ?? accounts[0].account_id}
      accounts={accounts}
      onSelect={setSelectedAccountId}
    />
  );
}

function summarizeAccount(detail: PaperAccountDetail): PaperAccountSummary {
  const initialEquity = detail.latest_equity?.initial_equity ?? detail.account.initial_cash;
  const totalEquity = detail.latest_equity?.total_equity ?? initialEquity;
  return {
    ...detail.account,
    initial_equity: initialEquity,
    total_equity: totalEquity,
    total_pnl: detail.latest_equity?.total_pnl ?? "0",
  };
}

function AccountWorkspace({
  client,
  accountId,
  accounts,
  onSelect,
}: {
  client: ApiClient;
  accountId: string;
  accounts: ReturnType<typeof usePaperAccountsQuery>["data"] extends infer T
    ? NonNullable<T>
    : never;
  onSelect: (accountId: string) => void;
}) {
  const accountQuery = usePaperAccountQuery(client, accountId);
  const ordersQuery = usePaperOrdersQuery(client, accountId);
  const fillsQuery = usePaperFillsQuery(client, accountId);
  const equityQuery = usePaperEquityQuery(client, accountId);
  const selectedSummary = accounts.find((item) => item.account_id === accountId) ?? accounts[0];
  const detail = accountQuery.data;
  const equity = detail?.latest_equity;
  const totalEquity = equity?.total_equity ?? selectedSummary.total_equity;
  const totalPnl = equity?.total_pnl ?? selectedSummary.total_pnl;
  const marketValue = equity?.market_value ?? "0";
  const cash = equity?.cash ?? detail?.account.cash ?? selectedSummary.cash;

  return (
    <div className="paper-workspace">
      <div className="paper-account-bar">
        <div>
          <p className="panel__eyebrow">SHADOW PORTFOLIO / REAL QUOTES</p>
          <select
            aria-label="模拟账户"
            value={accountId}
            onChange={(event) => onSelect(event.target.value)}
          >
            {accounts.map((account) => (
              <option key={account.account_id} value={account.account_id}>
                {account.name}
              </option>
            ))}
          </select>
        </div>
        <span className="paper-live-badge">真实行情盯市</span>
        <span className="paper-virtual-badge">不发送券商委托</span>
      </div>

      <section className="paper-equity-rail" aria-label="账户权益摘要">
        <Metric label="总资产" value={formatMoney(totalEquity)} primary />
        <Metric label="累计盈亏" value={formatSignedMoney(totalPnl)} trend={Number(totalPnl)} />
        <Metric label="持仓市值" value={formatMoney(marketValue)} />
        <Metric label="可用现金" value={formatMoney(cash)} />
        <Metric
          label="权益基线"
          value={formatMoney(selectedSummary.initial_equity)}
        />
      </section>

      <EquityPulse equity={equityQuery.data ?? []} baseline={selectedSummary.initial_equity} />

      <StrategyConsole
        client={client}
        accountId={accountId}
        defaultInstrument={detail?.positions[0]?.instrument_id ?? "159516.SZSE"}
      />

      <div className="paper-grid">
        <Panel title="当前持仓" eyebrow="POSITIONS / MARKED">
          {detail === undefined || detail.positions.length === 0 ? (
            <p className="paper-empty">先录入当前持仓，真实行情到达后会自动计算盈亏。</p>
          ) : (
            <div className="paper-table-wrap">
              <table className="paper-table">
                <thead>
                  <tr><th>证券</th><th>数量 / 可用</th><th>成本 / 最新</th><th>市值</th><th>浮动盈亏</th></tr>
                </thead>
                <tbody>
                  {detail.positions.map((position) => (
                    <tr key={position.instrument_id}>
                      <td><strong>{position.name ?? position.instrument_id}</strong><small>{position.instrument_id}</small></td>
                      <td>{position.quantity.toLocaleString()}<small>可用 {position.available_quantity.toLocaleString()}</small></td>
                      <td>{position.average_cost}<small>{position.last_price ?? "等待行情"}</small></td>
                      <td>{formatMoney(position.market_value)}</td>
                      <td className={trendClass(Number(position.unrealized_pnl))}>{formatSignedMoney(position.unrealized_pnl)}<small>{formatPercent(position.unrealized_pnl_percent)}</small></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        <TradingDock client={client} accountId={accountId} />
      </div>

      <div className="paper-grid paper-grid--history">
        <Panel title="订单与风控结果" eyebrow="ORDERS / AUDIT">
          <AuditList
            rows={(ordersQuery.data ?? []).map((order) => ({
              id: order.order_id,
              title: `${order.side === "BUY" ? "买入" : "卖出"} ${order.instrument_id} · ${order.quantity}`,
              meta: `${order.status}${order.reject_reason === null ? "" : ` · ${order.reject_reason}`} · ${formatTime(order.submitted_at)}`,
              trend: order.status === "REJECTED" ? -1 : 0,
            }))}
            empty="还没有虚拟订单。"
          />
        </Panel>
        <Panel title="虚拟成交" eyebrow="FILLS / LOCAL LEDGER">
          <AuditList
            rows={(fillsQuery.data ?? []).map((fill) => ({
              id: fill.fill_id,
              title: `${fill.side === "BUY" ? "买入" : "卖出"} ${fill.instrument_id} @ ${fill.price}`,
              meta: `${fill.quantity} 份 · 费用 ${fill.total_fee} · ${formatTime(fill.occurred_at)}`,
              trend: fill.side === "SELL" ? 1 : 0,
            }))}
            empty="订单成交后会在这里留下不可变记录。"
          />
        </Panel>
      </div>
    </div>
  );
}

function StrategyConsole({
  client,
  accountId,
  defaultInstrument,
}: {
  client: ApiClient;
  accountId: string;
  defaultInstrument: string;
}) {
  const runStrategy = useRunPaperStrategyMutation(client);
  const [instrument, setInstrument] = useState(defaultInstrument);
  const [quantity, setQuantity] = useState("100");
  const [maxPosition, setMaxPosition] = useState("20");
  const [autoExecute, setAutoExecute] = useState(false);

  useEffect(() => setInstrument(defaultInstrument), [defaultInstrument]);
  const result = runStrategy.data;
  return (
    <Panel
      title="策略执行台"
      eyebrow="QUANT / AUDITABLE BASELINE"
      className="paper-strategy"
      action={<span className="paper-strategy__version">baseline-v1</span>}
    >
      <div className="paper-strategy__layout">
        <form
          className="paper-strategy__controls"
          onSubmit={(event) => {
            event.preventDefault();
            runStrategy.mutate({
              accountId,
              request: {
                instrument_id: instrument,
                quantity: Number(quantity),
                auto_execute: autoExecute,
                max_position_percent: maxPosition,
              },
            });
          }}
        >
          <label>证券代码<input value={instrument} onChange={(event) => setInstrument(event.target.value.toUpperCase())} /></label>
          <label>建议数量<input inputMode="numeric" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label>
          <label>单标的仓位上限<input inputMode="decimal" value={maxPosition} onChange={(event) => setMaxPosition(event.target.value)} /><span>%</span></label>
          <label className="paper-strategy__switch"><input type="checkbox" checked={autoExecute} onChange={(event) => setAutoExecute(event.target.checked)} /><span>允许自动执行模拟成交</span></label>
          <button type="submit" disabled={runStrategy.isPending}>{runStrategy.isPending ? "正在读取真实行情…" : "运行 baseline-v1"}</button>
        </form>
        <div className="paper-strategy__result" aria-live="polite">
          {result === undefined ? (
            <><strong>默认只生成建议</strong><p>策略、信号、风控和结果都有确定版本与审计编号。即使开启自动执行，也只写入本地模拟账本。</p></>
          ) : (
            <>
              <div className="paper-strategy__outcome" data-outcome={result.outcome}>{result.outcome} · {result.signal.state}</div>
              <strong>{result.signal.action} · 置信度 {(Number(result.signal.confidence) * 100).toFixed(0)}%</strong>
              <p>{result.risk_reason ?? result.signal.reason_codes.join(" · ")}</p>
              <code>{result.decision_id}</code>
              {result.fill !== null ? <small>已按真实快照价 {result.fill.price} 虚拟成交 {result.fill.quantity} 份</small> : null}
            </>
          )}
          {runStrategy.error instanceof Error ? <p className="paper-form__error">{runStrategy.error.message}</p> : null}
        </div>
      </div>
    </Panel>
  );
}

function TradingDock({ client, accountId }: { client: ApiClient; accountId: string }) {
  const addPosition = useAddPaperPositionMutation(client);
  const submitOrder = useSubmitPaperOrderMutation(client);
  const [mode, setMode] = useState<"position" | "order">("position");
  const [instrument, setInstrument] = useState("159516.SZSE");
  const [name, setName] = useState("半导体设备ETF");
  const [quantity, setQuantity] = useState("100");
  const [available, setAvailable] = useState("100");
  const [cost, setCost] = useState("0.6800");
  const [side, setSide] = useState<PaperOrderSide>("BUY");
  const activeMutation = mode === "position" ? addPosition : submitOrder;
  return (
    <Panel
      title={mode === "position" ? "录入当前持仓" : "提交虚拟订单"}
      eyebrow="CONTROL / LOCAL ONLY"
      className="paper-dock"
      action={
        <div className="paper-segmented">
          <button type="button" data-active={mode === "position"} onClick={() => setMode("position")}>持仓</button>
          <button type="button" data-active={mode === "order"} onClick={() => setMode("order")}>买卖</button>
        </div>
      }
    >
      <form
        className="paper-form paper-form--compact"
        onSubmit={(event) => {
          event.preventDefault();
          if (mode === "position") {
            addPosition.mutate({
              accountId,
              request: {
                instrument_id: instrument,
                name: name || null,
                quantity: Number(quantity),
                available_quantity: Number(available),
                average_cost: cost,
              },
            });
          } else {
            submitOrder.mutate({
              accountId,
              idempotencyKey: `paper-${Date.now()}-${crypto.randomUUID()}`,
              request: {
                instrument_id: instrument,
                name: name || null,
                side,
                quantity: Number(quantity),
                stamp_duty_exempt: /ETF/i.test(name),
              },
            });
          }
        }}
      >
        <label>证券代码<input value={instrument} onChange={(event) => setInstrument(event.target.value.toUpperCase())} /></label>
        <label>证券名称<input value={name} onChange={(event) => setName(event.target.value)} /></label>
        {mode === "order" ? (
          <label>方向<select value={side} onChange={(event) => setSide(event.target.value as PaperOrderSide)}><option value="BUY">买入</option><option value="SELL">卖出</option></select></label>
        ) : null}
        <label>数量<input inputMode="numeric" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label>
        {mode === "position" ? <><label>可用数量<input inputMode="numeric" value={available} onChange={(event) => setAvailable(event.target.value)} /></label><label>平均成本<input inputMode="decimal" value={cost} onChange={(event) => setCost(event.target.value)} /></label></> : null}
        <button type="submit" disabled={activeMutation.isPending}>{mode === "position" ? "保存期初持仓" : "按真实行情虚拟成交"}</button>
        {activeMutation.error instanceof Error ? <p className="paper-form__error">{activeMutation.error.message}</p> : null}
      </form>
    </Panel>
  );
}

function Metric({ label, value, primary = false, trend }: { label: string; value: string; primary?: boolean; trend?: number }) {
  return <div className="paper-metric" data-primary={primary} data-trend={trend === undefined ? "neutral" : trend >= 0 ? "up" : "down"}><span>{label}</span><strong>{value}</strong></div>;
}

function EquityPulse({ equity, baseline }: { equity: PaperEquity[]; baseline: string }) {
  const points = useMemo(() => {
    if (equity.length < 2) return "0,54 100,54";
    const values = equity.map((item) => Number(item.total_equity));
    const min = Math.min(...values, Number(baseline));
    const max = Math.max(...values, Number(baseline));
    const range = Math.max(max - min, 1);
    return values.map((value, index) => `${(index / (values.length - 1)) * 100},${96 - ((value - min) / range) * 84}`).join(" ");
  }, [baseline, equity]);
  return <section className="paper-pulse" aria-label="权益脉冲轨"><div><span>权益脉冲轨</span><small>{equity.length === 0 ? "等待第一笔真实行情快照" : `${equity.length} 个本地快照`}</small></div><svg viewBox="0 0 100 108" preserveAspectRatio="none" role="img" aria-label="账户权益曲线"><line x1="0" y1="54" x2="100" y2="54" /><polyline points={points} /></svg></section>;
}

function AuditList({ rows, empty }: { rows: { id: string; title: string; meta: string; trend: number }[]; empty: string }) {
  if (rows.length === 0) return <p className="paper-empty">{empty}</p>;
  return <ul className="paper-audit">{rows.map((row) => <li key={row.id} data-trend={row.trend}><strong>{row.title}</strong><span>{row.meta}</span></li>)}</ul>;
}

function formatMoney(value: string): string { return Number(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function formatSignedMoney(value: string): string { const amount = Number(value); return `${amount >= 0 ? "+" : ""}${formatMoney(value)}`; }
function formatPercent(value: string | null): string { if (value === null) return "—"; const amount = Number(value); return `${amount >= 0 ? "+" : ""}${amount.toFixed(2)}%`; }
function formatTime(value: string): string { return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(value)); }
function trendClass(value: number): string { return value >= 0 ? "paper-trend-up" : "paper-trend-down"; }
