import { useMemo, useState } from "react";

import type { ApiClient } from "../api/client";
import type { MarketBar, MarketPeriod } from "../api/market-contracts";
import type {
  ReplayBar,
  ReplayResult,
  ReplayTrade,
} from "../api/research-contracts";
import type { ModelRegistryView } from "../api/paper-contracts";
import {
  usePaperModelsQuery,
  useResearchDatasetsQuery,
  useResearchReplayMutation,
} from "../api/queries";
import type { MarketSignalMarker } from "../features/market/marketSignalOverlay";
import { Panel } from "../components/Panel";
import { ProfessionalMarketChart } from "../components/ProfessionalMarketChart";

export function StrategyLabPage({ client }: { client: ApiClient }) {
  const datasetsQuery = useResearchDatasetsQuery(client);
  const modelsQuery = usePaperModelsQuery(client);
  const replay = useResearchReplayMutation(client);
  const [dataset, setDataset] = useState("");
  const [modelId, setModelId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [cash, setCash] = useState("100000");

  const datasets = datasetsQuery.data ?? [];
  const models = (modelsQuery.data ?? []).filter((item) => item.status === "APPROVED");

  const run = () => {
    if (dataset === "" || modelId === "") return;
    replay.mutate({
      dataset_id: dataset,
      model_id: modelId,
      start_date: startDate === "" ? null : startDate,
      end_date: endDate === "" ? null : endDate,
      initial_cash: cash,
    });
  };

  return (
    <section className="strategy-lab" aria-labelledby="strategy-lab-title">
      <header className="strategy-lab__toolbar">
        <div>
          <p className="strategy-lab__eyebrow">RESEARCH / REPLAY</p>
          <h1 id="strategy-lab-title">策略实验室</h1>
        </div>
      </header>

      <Panel title="回放设置" eyebrow="REPLAY / HISTORY">
        <div className="strategy-lab__form">
          <label>数据集（已录制真实分钟线）
            <select value={dataset} onChange={(event) => setDataset(event.target.value)}>
              <option value="">选择数据集…</option>
              {datasets.map((item) => (
                <option key={item.dataset_id} value={item.dataset_id}>
                  {item.instrument_id} · {item.bar_count} 根 · {item.start.slice(0, 10)}~{item.end.slice(0, 10)}
                </option>
              ))}
            </select>
          </label>
          <label>模型（仅已批准）
            <select value={modelId} onChange={(event) => setModelId(event.target.value)}>
              <option value="">选择模型…</option>
              {models.map((item) => (
                <option key={item.model_id} value={item.model_id}>
                  {item.model_id} · {item.strategy_version}
                </option>
              ))}
            </select>
          </label>
          <label>起始日期（可选）<input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
          <label>结束日期（可选）<input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label>
          <label>初始资金<input type="number" min="0" step="10000" value={cash} onChange={(event) => setCash(event.target.value)} /></label>
          <button type="button" disabled={replay.isPending || dataset === "" || modelId === ""} onClick={run}>
            {replay.isPending ? "回放中…" : "运行历史回放"}
          </button>
        </div>
        {replay.error instanceof Error ? <p className="strategy-lab__error" role="alert">{replay.error.message}</p> : null}
      </Panel>

      {replay.data === undefined ? (
        <Panel title="回放结果" eyebrow="PERFORMANCE">
          <p className="strategy-lab__empty">选择数据集与模型后运行回放。结果会在同一输入下确定性复现：K 线、买卖点、每笔盈亏与权益曲线。</p>
        </Panel>
      ) : (
        <ReplayResultView result={replay.data} models={models} />
      )}
    </section>
  );
}

function ReplayResultView({
  result,
  models,
}: {
  result: ReplayResult;
  models: ModelRegistryView[];
}) {
  const bars = useMemo(() => toChartBars(result.bars), [result.bars]);
  const signals = useMemo<MarketSignalMarker[]>(
    () =>
      result.trades
        .map((trade) => ({
          id: `replay-${trade.index}`,
          timestamp: Date.parse(trade.timestamp),
          side: trade.side,
          price: Number(trade.price),
          label: `${trade.side === "BUY" ? "回放买入" : "回放卖出"} ${trade.quantity} 份 @ ${trade.price}`,
          source: "REPLAY" as const,
        }))
        .filter((item) => Number.isFinite(item.timestamp) && Number.isFinite(item.price)),
    [result.trades],
  );
  const equity = useMemo(
    () =>
      result.equity_points
        .filter(([timestamp]) => Number.isFinite(Date.parse(timestamp)))
        .map(([timestamp, value]) => [Date.parse(timestamp), Number(value)] as const),
    [result.equity_points],
  );
  const selectedModel = models.find((item) => item.model_id === result.model_id);

  return (
    <>
      <div className="strategy-lab__metrics">
        <Metric label="净收益" value={`${result.net_return_percent >= 0 ? "+" : ""}${result.net_return_percent.toFixed(2)}%`} trend={result.net_return_percent} />
        <Metric label="胜率" value={`${(result.win_rate * 100).toFixed(0)}%`} trend={result.win_rate - 0.5} />
        <Metric label="交易（买/卖）" value={`${result.buys} / ${result.sells}`} trend={0} />
        <Metric label="已实现盈亏" value={formatSignedMoney(result.realized_pnl)} trend={Number(result.realized_pnl)} />
        <Metric label="期末资金" value={formatMoney(result.final_cash)} trend={0} />
      </div>

      <Panel
        title={`权益曲线 · ${result.instrument_id}`}
        eyebrow="EQUITY / REPLAY"
        action={<span className="paper-strategy__version">{selectedModel?.strategy_version ?? result.model_id}</span>}
      >
        <EquityCurve points={equity} initial={Number(result.initial_cash)} />
      </Panel>

      <Panel title="K 线与回放买卖点" eyebrow="PRICE / TRADES">
        <ProfessionalMarketChart
          instrumentId={result.instrument_id}
          period="1m"
          mainIndicator="MA"
          secondaryIndicator="VOL"
          showQuantSignals
          bars={bars}
          signals={signals}
        />
      </Panel>

      <div className="strategy-lab__grid">
        <Panel title="交易明细" eyebrow="TRADES / AUDIT">
          <TradeList trades={result.trades} />
        </Panel>
        <Panel title="回放说明" eyebrow="NOTES / HONESTY">
          <ul className="strategy-lab__notes">
            <li>当前回放为确定性单仓位模型：同输入同输出，可复现。</li>
            <li>结果包含模型训练时段（样本内），表现偏乐观；样本外表现以模拟盘验证为准。</li>
            <li>费用口径：佣金万 2.5 + 过户费（双边），未含滑点。</li>
            <li>信号基于 1 分钟 K 线完成时点，无未来函数。</li>
          </ul>
        </Panel>
      </div>
    </>
  );
}

function toChartBars(bars: ReplayBar[]): MarketBar[] {
  return bars.map((bar) => ({
    timestamp: bar.timestamp,
    open: Number(bar.open),
    high: Number(bar.high),
    low: Number(bar.low),
    close: Number(bar.close),
    volume: Number(bar.volume),
    turnover: Number(bar.close) * Number(bar.volume),
    previous_close: null,
  }));
}

function EquityCurve({ points, initial }: { points: Array<readonly [number, number]>; initial: number }) {
  if (points.length < 2) {
    return <p className="strategy-lab__empty">等待回放数据生成权益曲线</p>;
  }
  const values = [initial, ...points.map(([, value]) => value)];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(max - min, 1);
  const width = 100;
  const height = 40;
  const coords = points.map(([timestamp, value], index) => {
    const x = (index / (points.length - 1)) * width;
    const y = height - ((value - min) / range) * (height - 4) - 2;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  return (
    <svg className="strategy-lab__equity" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="回放权益曲线">
      <line x1="0" y1={height / 2} x2={width} y2={height / 2} stroke="var(--border)" />
      <polyline points={coords.join(" ")} fill="none" stroke="var(--accent)" strokeWidth="1.2" />
    </svg>
  );
}

function TradeList({ trades }: { trades: ReplayTrade[] }) {
  if (trades.length === 0) {
    return <p className="strategy-lab__empty">该时段没有触发交易。</p>;
  }
  return (
    <ul className="strategy-lab__trades">
      {trades.map((trade) => (
        <li key={`${trade.index}-${trade.side}`} data-side={trade.side.toLowerCase()}>
          <strong>{trade.side === "BUY" ? "买入" : "卖出"} {trade.quantity} 份 @ {trade.price}</strong>
          <span>{formatTime(trade.timestamp)} · 盈亏 {formatSignedMoney(trade.pnl)}</span>
        </li>
      ))}
    </ul>
  );
}

function Metric({ label, value, trend }: { label: string; value: string; trend: number }) {
  return (
    <div className="strategy-lab__metric" data-trend={trend >= 0 ? "up" : "down"}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function formatMoney(value: string): string {
  return Number(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function formatSignedMoney(value: string): string {
  const amount = Number(value);
  return `${amount >= 0 ? "+" : ""}${formatMoney(value)}`;
}
function formatTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value));
}
