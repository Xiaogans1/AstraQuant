import { useEffect, useMemo, useState } from "react";

import type { ApiClient } from "../api/client";
import {
  useAddPaperPositionMutation,
  useDefaultPaperAccountQuery,
  useMarketConnectionQuery,
  usePaperAccountQuery,
  usePaperAccountsQuery,
  usePaperEquityQuery,
  usePaperFeeConfigQuery,
  usePaperFillsQuery,
  usePaperOrdersQuery,
  usePaperStrategyRunsQuery,
  usePaperStrategyStatusQuery,
  useResetPaperAccountMutation,
  useRunPaperStrategyScanMutation,
  useUpdatePaperCashMutation,
  useUpdatePaperFeeConfigMutation,
} from "../api/queries";
import type {
  PaperAccountDetail,
  PaperAccountSummary,
  PaperEquity,
  PaperPosition,
} from "../api/paper-contracts";
import type { ConnectionState, QuoteCard } from "../api/market-contracts";
import type { MarketSignalMarker } from "../features/market/marketSignalOverlay";
import { ApiError } from "../api/client";
import { InstrumentSearchPicker, type InstrumentSelection } from "../components/InstrumentSearchPicker";
import { MarketWorkspace } from "../components/MarketWorkspace";
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
  const connectionQuery = useMarketConnectionQuery(client);
  const selectedSummary = accounts.find((item) => item.account_id === accountId) ?? accounts[0];
  const detail = accountQuery.data;
  const equity = detail?.latest_equity;
  const totalEquity = equity?.total_equity ?? selectedSummary.total_equity;
  const totalPnl = equity?.total_pnl ?? selectedSummary.total_pnl;
  const marketValue = equity?.market_value ?? "0";
  const cash = equity?.cash ?? detail?.account.cash ?? selectedSummary.cash;
  const positions = detail?.positions ?? [];
  const dayPnl = useMemo(() => calculateDayPnl(positions), [positions]);
  const resetAccount = useResetPaperAccountMutation(client);
  const [selectedInstrumentId, setSelectedInstrumentId] = useState<string | null>(null);

  useEffect(() => {
    if (
      positions.length > 0
      && !positions.some((item) => item.instrument_id === selectedInstrumentId)
    ) {
      setSelectedInstrumentId(positions[0].instrument_id);
    }
  }, [positions, selectedInstrumentId]);

  const selectedPosition = positions.find(
    (item) => item.instrument_id === selectedInstrumentId,
  ) ?? positions[0];
  const selectedQuote = selectedPosition === undefined
    ? null
    : positionQuote(selectedPosition, connectionQuery.data?.state ?? "UNAVAILABLE");
  const paperMarkers = useMemo<MarketSignalMarker[]>(
    () => (fillsQuery.data ?? [])
      .filter((fill) => fill.instrument_id === selectedPosition?.instrument_id)
      .map((fill) => ({
        id: fill.fill_id,
        timestamp: Date.parse(fill.occurred_at),
        side: fill.side,
        price: Number(fill.price),
        label: `模拟成交 · ${fill.quantity} 份 @ ${fill.price}`,
        source: "PAPER_FILL" as const,
      }))
      .filter((item) => Number.isFinite(item.timestamp) && Number.isFinite(item.price)),
    [fillsQuery.data, selectedPosition?.instrument_id],
  );

  return (
    <div className="paper-workspace">
      <div className="paper-account-bar">
        <div className="paper-account-bar__identity">
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
        <div className="paper-account-bar__status">
          <span className="paper-live-badge">真实行情盯市</span>
          <span className="paper-virtual-badge">仅虚拟成交</span>
        </div>
        <CashEditor client={client} accountId={accountId} cash={cash} />
        <button
          type="button"
          className="paper-reset-button"
          disabled={resetAccount.isPending}
          onClick={() => {
            if (window.confirm("重置将删除全部订单、成交、持仓和策略记录并重建模拟账户。确定继续？")) {
              resetAccount.mutate(accountId);
            }
          }}
        >
          {resetAccount.isPending ? "重置中…" : "重置模拟账户"}
        </button>
      </div>

      <section className="paper-equity-rail" aria-label="账户权益摘要">
        <Metric label="总资产" value={formatMoney(totalEquity)} primary />
        <Metric
          label="当日盈亏"
          value={dayPnl === null ? "—" : formatSignedMoney(dayPnl.pnl.toFixed(2))}
          trend={dayPnl?.pnl ?? 0}
          sub={dayPnl === null ? "等待今日真实行情" : `今日 ${formatSignedPercent(dayPnl.pct)}（相对昨收）`}
        />
        <Metric label="累计盈亏" value={formatSignedMoney(totalPnl)} trend={Number(totalPnl)} sub={`权益基线 ${formatMoney(selectedSummary.initial_equity)}`} />
        <Metric label="持仓市值" value={formatMoney(marketValue)} />
        <Metric label="剩余现金" value={formatMoney(cash)} />
      </section>

      <div className="paper-equity-formula" role="note">
        <strong>总资产</strong>
        <span>=</span>
        <span>剩余现金 {formatMoney(cash)}</span>
        <span>+</span>
        <span>持仓市值 {formatMoney(marketValue)}</span>
      </div>

      <StrategyConsole
        client={client}
        accountId={accountId}
        positions={positions}
        selectedPosition={selectedPosition ?? null}
      />

      <div className="paper-trade-section">
        {positions.length > 0 ? (
          <PositionSwitcher
            positions={positions}
            selectedId={selectedPosition?.instrument_id ?? null}
            onSelect={setSelectedInstrumentId}
          />
        ) : null}
        {selectedQuote === null ? (
          <section className="paper-chart-empty">
            <strong>录入持仓后显示策略图</strong>
            <p>这里将复用首页的真实分时与 K 线，并叠加量化信号和模拟成交点。</p>
          </section>
        ) : (
          <MarketWorkspace
            client={client}
            quote={selectedQuote}
            state={connectionQuery.data?.state ?? "UNAVAILABLE"}
            contextLabel="主模拟账户 · 持仓策略图"
            portfolioMarkers={paperMarkers}
          />
        )}
      </div>

      <div className="paper-grid">
        <Panel title="当前持仓" eyebrow="POSITIONS / MARKED">          {detail === undefined || detail.positions.length === 0 ? (
            <p className="paper-empty">先录入当前持仓，真实行情到达后会自动计算盈亏。</p>
          ) : (
            <div className="paper-table-wrap">
              <table className="paper-table">
                <thead>
                  <tr><th>证券</th><th>数量 / 可用</th><th>最新 / 成本</th><th>市值</th><th>浮动盈亏</th><th /></tr>
                </thead>
                <tbody>
                  {detail.positions.map((position) => (
                    <tr key={position.instrument_id} data-selected={position.instrument_id === selectedPosition?.instrument_id}>
                      <td><strong>{position.name ?? position.instrument_id}</strong><small>{position.instrument_id}</small></td>
                      <td>{position.quantity.toLocaleString()}<small>可用 {position.available_quantity.toLocaleString()}</small></td>
                      <td>{position.last_price ?? "等待行情"}<small>成本 {position.average_cost}</small></td>
                      <td>{formatMoney(position.market_value)}</td>
                      <td className={trendClass(Number(position.unrealized_pnl))}>{formatSignedMoney(position.unrealized_pnl)}<small>{formatPercent(position.unrealized_pnl_percent)}</small></td>
                      <td><button type="button" className="paper-table__chart-action" onClick={() => setSelectedInstrumentId(position.instrument_id)}>查看策略图</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        <OpeningPositionDock client={client} accountId={accountId} />
      </div>

      <FeeConfigEditor client={client} />

      <EquityPulse equity={equityQuery.data ?? []} baseline={selectedSummary.initial_equity} />

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

function PositionSwitcher({
  positions,
  selectedId,
  onSelect,
}: {
  positions: PaperPosition[];
  selectedId: string | null;
  onSelect: (instrumentId: string) => void;
}) {
  return (
    <div className="paper-switcher" role="tablist" aria-label="切换持仓查看策略图">
      {positions.map((position) => (
        <button
          key={position.instrument_id}
          type="button"
          role="tab"
          aria-selected={position.instrument_id === selectedId}
          onClick={() => onSelect(position.instrument_id)}
        >
          <strong>{position.name ?? position.instrument_id}</strong>
          <span>{position.instrument_id}</span>
          <small>{position.last_price ?? "等待行情"} · {formatPercent(position.unrealized_pnl_percent)}</small>
        </button>
      ))}
    </div>
  );
}

function StrategyConsole({
  client,
  accountId,
  positions,
  selectedPosition,
}: {
  client: ApiClient;
  accountId: string;
  positions: PaperPosition[];
  selectedPosition: PaperPosition | null;
}) {
  const runScan = useRunPaperStrategyScanMutation(client);
  const persistedRuns = usePaperStrategyRunsQuery(client, accountId);
  const status = usePaperStrategyStatusQuery(client);
  const results = runScan.data ?? persistedRuns.data;
  const strategyError = runScan.error instanceof Error
    ? runScan.error
    : persistedRuns.error instanceof Error
      ? persistedRuns.error
      : null;
  const autoScanLabel = status.data?.loop_enabled === true
    ? `盘中每 ${status.data.loop_interval_seconds} 秒自动检查${status.data.last_scan_at === null ? "" : ` · 上次 ${formatTime(status.data.last_scan_at)}`}`
    : "自动检查未开启";
  return (
    <Panel
      title="量化策略"
      eyebrow="STRATEGY / ACCOUNT CONTEXT"
      className="paper-strategy"
      action={<span className="paper-strategy__version">baseline-v1</span>}
    >
      <div className="paper-strategy__layout">
        <div className="paper-strategy__controls">
          <div className="paper-strategy__scope">
            <span>当前检查范围</span>
            <strong>{positions.length === 0 ? "等待录入持仓" : `全部持仓 · ${positions.length} 只（并发检查）`}</strong>
            <small className="paper-strategy__brief">baseline-v1 日内动量 + 量能突破：买入需 5 分钟涨幅 ≥ 0.3% 且均线多头排列且量比 ≥ 1.5；卖出需 5 分钟跌幅 ≥ 0.3% 且均线走弱。特征不足 20 根 1 分钟 K 线时只观察不出手。</small>
            <small className="paper-strategy__auto">{autoScanLabel}</small>
          </div>
          <button
            type="button"
            disabled={runScan.isPending || positions.length === 0}
            onClick={() => {
              if (positions.length === 0) return;
              runScan.mutate({
                accountId,
                request: {
                  instrument_id: selectedPosition?.instrument_id ?? positions[0].instrument_id,
                  quantity: 100,
                  auto_execute: true,
                  max_position_percent: "20",
                },
              });
            }}
          >{runScan.isPending ? "正在并发检查真实行情…" : "检查全部持仓"}</button>
        </div>
        <div className="paper-strategy__result" aria-live="polite">
          {results === undefined ? (
            <><strong>策略由量化核心执行</strong><p>一次并发检查全部持仓；产生的信号、风控结果和虚拟成交都会进入本地审计记录。</p></>
          ) : (
            <ScanResultList results={results} positions={positions} />
          )}
          {strategyError !== null ? <p className="paper-form__error" role="alert">策略服务暂时不可用：{strategyError.message}。请重启应用后重试。</p> : null}
        </div>
      </div>
    </Panel>
  );
}

function ScanResultList({
  results,
  positions,
}: {
  results: ReturnType<typeof useRunPaperStrategyScanMutation>["data"] extends infer T
    ? NonNullable<T>
    : never;
  positions: PaperPosition[];
}) {
  const nameOf = (instrumentId: string): string =>
    positions.find((item) => item.instrument_id === instrumentId)?.name
    ?? instrumentId;
  const lastChecked = results.length > 0
    ? new Date(Math.max(...results.map((item) => Date.parse(item.signal.decision_time))))
    : null;
  return (
    <>
      {lastChecked !== null && Number.isFinite(lastChecked.getTime()) ? (
        <div className="paper-scan__stamp">最近检查 · {formatTime(lastChecked.toISOString())}</div>
      ) : null}
      <ul className="paper-scan">
        {results.map((result) => (
          <li key={result.decision_id} data-outcome={result.outcome.toLowerCase()}>
            <span className="paper-scan__identity">
              <strong>{nameOf(result.signal.instrument_id)}</strong>
              <small>{result.signal.instrument_id} · {result.signal.state}</small>
            </span>
            <span className="paper-scan__signal">
              <b>{result.outcome}</b>
              <small>{result.signal.action} · 置信度 {(Number(result.signal.confidence) * 100).toFixed(0)}%</small>
            </span>
            <span className="paper-scan__detail">
              <small>{result.risk_reason ?? result.signal.reason_codes.map(reasonCopy).join(" · ")}</small>
              {result.fill !== null ? <small>已按真实快照价 {result.fill.price} 虚拟成交 {result.fill.quantity} 份</small> : null}
              <code>{result.decision_id}</code>
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}

function reasonCopy(code: string): string {
  switch (code) {
    case "INSUFFICIENT_COMPLETED_BARS":
      return "1 分钟 K 线不足 20 根，特征热身中";
    case "MARKET_NOT_LIVE":
      return "真实行情尚未连接";
    case "MARKET_DATA_STALE":
      return "行情数据已过期，暂停判断";
    case "NO_CONFIRMED_EDGE":
      return "未满足买入/卖出条件，保持观望";
    case "MOMENTUM_VOLUME_BREAKOUT":
      return "动量 + 量能突破，触发买入";
    case "DOWNTREND_EXIT":
      return "均线走弱下跌，触发卖出";
    default:
      return code;
  }
}

function FeeConfigEditor({ client }: { client: ApiClient }) {
  const configQuery = usePaperFeeConfigQuery(client);
  const update = useUpdatePaperFeeConfigMutation(client);
  const [commission, setCommission] = useState("");
  const [minimum, setMinimum] = useState("");
  const [stampDuty, setStampDuty] = useState("");
  const [transfer, setTransfer] = useState("");

  useEffect(() => {
    const config = configQuery.data;
    if (config === undefined) return;
    setCommission(rateToPercent(config.commission_rate));
    setMinimum(config.minimum_commission);
    setStampDuty(rateToPercent(config.stamp_duty_rate));
    setTransfer(rateToPercent(config.transfer_fee_rate));
  }, [configQuery.data]);

  const dirty =
    commission !== (configQuery.data === undefined ? "" : rateToPercent(configQuery.data.commission_rate))
    || minimum !== (configQuery.data?.minimum_commission ?? "")
    || stampDuty !== (configQuery.data === undefined ? "" : rateToPercent(configQuery.data.stamp_duty_rate))
    || transfer !== (configQuery.data === undefined ? "" : rateToPercent(configQuery.data.transfer_fee_rate));

  return (
    <Panel
      title="模拟费用设置"
      eyebrow="FEES / LOCAL ACCOUNT"
      className="paper-fees"
      action={<span className="paper-dock__step">影响虚拟成交成本</span>}
    >
      <form
        className="paper-form paper-form--compact paper-form--fees"
        onSubmit={(event) => {
          event.preventDefault();
          update.mutate({
            commission_rate: percentToRate(commission),
            minimum_commission: minimum,
            stamp_duty_rate: percentToRate(stampDuty),
            transfer_fee_rate: percentToRate(transfer),
          });
        }}
      >
        <label>佣金费率（%，每边）<input required min="0" step="any" type="number" inputMode="decimal" value={commission} onChange={(event) => setCommission(event.target.value)} /></label>
        <label>最低佣金（元，0 = 免最低 5 元）<input required min="0" step="any" type="number" inputMode="decimal" value={minimum} onChange={(event) => setMinimum(event.target.value)} /></label>
        <label>印花税率（%，卖出）<input required min="0" step="any" type="number" inputMode="decimal" value={stampDuty} onChange={(event) => setStampDuty(event.target.value)} /></label>
        <label>过户费率（%）<input required min="0" step="any" type="number" inputMode="decimal" value={transfer} onChange={(event) => setTransfer(event.target.value)} /></label>
        <button type="submit" disabled={update.isPending || !dirty || configQuery.isLoading}>
          {update.isPending ? "保存中…" : "保存费用设置"}
        </button>
        {update.error instanceof Error ? <p className="paper-form__error">{update.error.message}</p> : null}
      </form>
    </Panel>
  );
}

function rateToPercent(rate: string): string {
  return String(Number(rate) * 100);
}

function percentToRate(value: string): string {
  return String(Number(value) / 100);
}

function OpeningPositionDock({ client, accountId }: { client: ApiClient; accountId: string }) {
  const addPosition = useAddPaperPositionMutation(client);
  const [instrument, setInstrument] = useState<InstrumentSelection | null>(null);
  const [quantity, setQuantity] = useState("");
  const [available, setAvailable] = useState("");
  const [cost, setCost] = useState("");
  return (
    <Panel
      title="初始化持仓"
      eyebrow="ACCOUNT SETUP / HOLDINGS"
      className="paper-dock"
      action={<span className="paper-dock__step">可连续添加</span>}
    >
      <p className="paper-dock__hint">只录入你现在真实持有的证券。后续买卖全部由量化策略在模拟盘完成。</p>
      <form
        className="paper-form paper-form--compact"
        onSubmit={(event) => {
          event.preventDefault();
          if (instrument === null) return;
          addPosition.mutate({
            accountId,
            request: {
              instrument_id: instrument.instrument_id,
              name: instrument.name,
              quantity: Number(quantity),
              available_quantity: Number(available),
              average_cost: cost,
            },
          }, {
            onSuccess: () => {
              setInstrument(null);
              setQuantity("");
              setAvailable("");
              setCost("");
            },
          });
        }}
      >
        <label>
          证券（从真实搜索结果中选择）
          <InstrumentSearchPicker
            client={client}
            value={instrument}
            onChange={setInstrument}
            ariaLabel="搜索期初持仓证券"
            placeholder="输入代码或名称，如 159516 或半导体设备"
          />
        </label>
        <label>持有数量<input required min="1" type="number" inputMode="numeric" value={quantity} onChange={(event) => { setQuantity(event.target.value); if (available === "") setAvailable(event.target.value); }} /></label>
        <label>可用数量<input required min="0" type="number" inputMode="numeric" value={available} onChange={(event) => setAvailable(event.target.value)} /></label>
        <label>平均成本<input required min="0" step="any" type="number" inputMode="decimal" value={cost} onChange={(event) => setCost(event.target.value)} /></label>
        <button type="submit" disabled={addPosition.isPending || instrument === null}>{addPosition.isPending ? "正在保存…" : "添加到初始持仓"}</button>
        {addPosition.error instanceof Error ? <p className="paper-form__error">{friendlyPaperError(addPosition.error)}</p> : null}
      </form>
    </Panel>
  );
}

function friendlyPaperError(error: Error): string {
  if (error instanceof ApiError && error.code === "opening_position_conflict") {
    if (/invalid instrument identifier/i.test(error.message)) {
      return "请从搜索结果中选择有效的证券后再提交";
    }
    if (/already exists/i.test(error.message)) {
      return "该证券已在期初持仓中，请勿重复添加";
    }
    return "该证券无法加入期初持仓，请检查后重试";
  }
  return error.message;
}

function CashEditor({
  client,
  accountId,
  cash,
}: {
  client: ApiClient;
  accountId: string;
  cash: string;
}) {
  const updateCash = useUpdatePaperCashMutation(client);
  const [value, setValue] = useState(cash);
  useEffect(() => setValue(cash), [accountId, cash]);
  return (
    <form
      className="paper-cash-editor"
      onSubmit={(event) => {
        event.preventDefault();
        updateCash.mutate({ accountId, request: { cash: value } });
      }}
    >
      <label>
        <span>剩余现金（不含持仓）</span>
        <input
          aria-label="剩余现金（不含持仓）"
          type="number"
          min="0"
          step="0.01"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
      </label>
      <button type="submit" disabled={updateCash.isPending || value === cash}>
        {updateCash.isPending ? "保存中…" : "保存资金"}
      </button>
      {updateCash.error instanceof Error ? <span role="alert">{updateCash.error.message}</span> : null}
    </form>
  );
}

function Metric({ label, value, primary = false, trend, sub }: { label: string; value: string; primary?: boolean; trend?: number; sub?: string }) {
  return (
    <div className="paper-metric" data-primary={primary} data-trend={trend === undefined ? "neutral" : trend >= 0 ? "up" : "down"}>
      <span>{label}</span>
      <strong>{value}</strong>
      {sub !== undefined ? <small className="paper-metric__sub">{sub}</small> : null}
    </div>
  );
}

function calculateDayPnl(positions: PaperPosition[]): { pnl: number; pct: number } | null {
  let numerator = 0;
  let denominator = 0;
  for (const position of positions) {
    const last = position.last_price === null ? null : Number(position.last_price);
    const previous = position.previous_close === null ? null : Number(position.previous_close);
    if (last === null || previous === null) continue;
    if (!Number.isFinite(last) || !Number.isFinite(previous) || previous <= 0) continue;
    numerator += (last - previous) * position.quantity;
    denominator += previous * position.quantity;
  }
  if (denominator <= 0) return null;
  return { pnl: numerator, pct: (numerator / denominator) * 100 };
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
function formatSignedPercent(value: number): string { return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`; }
function formatPercent(value: string | null): string { if (value === null) return "—"; const amount = Number(value); return `${amount >= 0 ? "+" : ""}${amount.toFixed(2)}%`; }
function formatTime(value: string): string { return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(value)); }
function trendClass(value: number): string { return value >= 0 ? "paper-trend-up" : "paper-trend-down"; }

function positionQuote(position: PaperPosition, state: ConnectionState): QuoteCard {
  return {
    instrument_id: position.instrument_id,
    name: position.name ?? position.instrument_id,
    kind: "holding",
    state,
    event_time: position.marked_at,
    last_price: position.last_price ?? position.average_cost,
    change: null,
    change_percent: position.unrealized_pnl_percent,
    previous_close: null,
    open: null,
    high: null,
    low: null,
    volume: null,
    turnover: null,
    source_id: "paper-position",
  };
}
