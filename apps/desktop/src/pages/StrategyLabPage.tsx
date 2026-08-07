import { useMemo, useState } from "react";

import type { ApiClient } from "../api/client";
import type { MarketBar } from "../api/market-contracts";
import type {
  ReplayBar,
  ReplayInstrumentInput,
  ReplayResult,
  ReplayTrade,
} from "../api/research-contracts";
import type { ModelRegistryView, PaperStrategyRun } from "../api/paper-contracts";
import {
  useDailySummaryQuery,
  usePaperModelsQuery,
  useResearchExperimentsQuery,
  useResearchReplayMutation,
  useStrategyRunsOnDateQuery,
} from "../api/queries";
import type { MarketSignalMarker } from "../features/market/marketSignalOverlay";
import { Panel } from "../components/Panel";
import { ProfessionalMarketChart } from "../components/ProfessionalMarketChart";
import { InstrumentSearchPicker, type InstrumentSelection } from "../components/InstrumentSearchPicker";
import { useDefaultPaperAccountQuery } from "../api/queries";

type LabTab = "replay" | "daily" | "experiments" | "train";

export function StrategyLabPage({ client }: { client: ApiClient }) {
  const [tab, setTab] = useState<LabTab>("replay");
  return (
    <section className="strategy-lab" aria-labelledby="strategy-lab-title">
      <header className="strategy-lab__toolbar">
        <div>
          <p className="strategy-lab__eyebrow">RESEARCH / REPLAY</p>
          <h1 id="strategy-lab-title">策略实验室</h1>
        </div>
        <div className="strategy-lab__tabs" role="tablist" aria-label="实验室分区">
          {([
            ["replay", "回放"],
            ["daily", "每日收益"],
            ["experiments", "历史实验"],
            ["train", "训练"],
          ] as [LabTab, string][]).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </div>
      </header>

      {tab === "replay" ? <ReplayTab client={client} /> : null}
      {tab === "daily" ? <DailyTab client={client} /> : null}
      {tab === "experiments" ? <ExperimentsTab client={client} /> : null}
      {tab === "train" ? <TrainTab client={client} /> : null}
    </section>
  );
}

function ReplayTab({ client }: { client: ApiClient }) {
  const modelsQuery = usePaperModelsQuery(client);
  const replay = useResearchReplayMutation(client);
  const [instruments, setInstruments] = useState<InstrumentSelection[]>([]);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [modelId, setModelId] = useState("");
  const [cash, setCash] = useState("100000");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const models = modelsQuery.data ?? [];
  const results = replay.data;

  const run = () => {
    if (instruments.length === 0 || modelId === "") return;
    replay.mutate({
      instruments: instruments.map((item) => ({
        instrument_id: item.instrument_id,
        start_date: startDate === "" ? null : startDate,
        end_date: endDate === "" ? null : endDate,
      })),
      model_id: modelId,
      initial_cash: cash,
    });
  };

  const current: ReplayResult | undefined = results?.[selectedIndex];

  return (
    <>
      <Panel title="批量回放" eyebrow="REPLAY / ANY INSTRUMENT">
        <div className="strategy-lab__form">
          <label>
            股票（可连续添加，与首页一致的真实搜索）
            <InstrumentSearchPicker
              client={client}
              value={null}
              ariaLabel="搜索回放股票"
              placeholder="输入代码或名称，添加后回车选择"
              onChange={(selection) => {
                if (selection === null) return;
                if (!instruments.some((item) => item.instrument_id === selection.instrument_id)) {
                  setInstruments((items) => [...items, selection]);
                }
              }}
            />
          </label>
          <div className="strategy-lab__picked">
            {instruments.map((item) => (
              <span key={item.instrument_id} className="strategy-lab__chip">
                {item.name}
                <button
                  type="button"
                  aria-label={`移除 ${item.name}`}
                  onClick={() => {
                    setInstruments((items) => items.filter((i) => i.instrument_id !== item.instrument_id));
                    setSelectedIndex(0);
                  }}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
          <label>起始日期<input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
          <label>结束日期<input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label>
          <label>模型
            <select value={modelId} onChange={(event) => setModelId(event.target.value)}>
              <option value="">选择模型…</option>
              {models.map((item) => (
                <option key={item.model_id} value={item.model_id}>
                  {item.model_id} · {item.strategy_version}{item.status === "DRAFT" ? "（未批准）" : ""}
                </option>
              ))}
            </select>
          </label>
          <label>初始资金<input type="number" min="0" step="10000" value={cash} onChange={(event) => setCash(event.target.value)} /></label>
          <button type="button" disabled={replay.isPending || instruments.length === 0 || modelId === ""} onClick={run}>
            {replay.isPending ? "批量回放中（N 只 × 分钟级推理，约几十秒）…" : `批量运行 ${instruments.length} 只`}
          </button>
        </div>
        {replay.error instanceof Error ? <p className="strategy-lab__error" role="alert">{replay.error.message}</p> : null}
        <p className="strategy-lab__note">数据从东财实时拉取，可用历史深度以数据源为准；盘中回放仅覆盖已完成 K 线。回放不模拟涨跌停与停牌。</p>
      </Panel>

      {results === undefined || results.length === 0 ? (
        <Panel title="回放结果" eyebrow="PERFORMANCE">
          <p className="strategy-lab__empty">添加股票并运行批量回放。结果自动存档为实验，可随时回看并生成报告。</p>
        </Panel>
      ) : (
        <>
          <div className="strategy-lab__switcher" role="tablist" aria-label="切换回放标的">
            {results.map((item, index) => (
              <button
                key={item.instrument_id}
                type="button"
                role="tab"
                aria-selected={index === selectedIndex}
                onClick={() => setSelectedIndex(index)}
              >
                <strong>{item.instrument_id}</strong>
                <span>{item.net_return_percent >= 0 ? "+" : ""}{item.net_return_percent.toFixed(2)}%</span>
              </button>
            ))}
          </div>
          {current === undefined ? null : (
            <ReplayResultView result={current} models={models} />
          )}
        </>
      )}
    </>
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
          label: `${trade.side === "BUY" ? "回放买入" : "回放卖出"} ${trade.quantity} 份 @ ${trade.price}（概率 ${(trade.proba * 100).toFixed(0)}%）`,
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
  const model = models.find((item) => item.model_id === result.model_id);

  return (
    <>
      {result.model_status === "DRAFT" ? (
        <div className="strategy-lab__warn">未批准模型回放，仅供参考，不代表可上线。</div>
      ) : null}
      <div className="strategy-lab__metrics">
        <Metric label="净收益" value={`${result.net_return_percent >= 0 ? "+" : ""}${result.net_return_percent.toFixed(2)}%`} trend={result.net_return_percent} />
        <Metric label="胜率" value={`${(result.win_rate * 100).toFixed(0)}%`} trend={result.win_rate - 0.5} />
        <Metric label="买卖" value={`${result.buys} / ${result.sells}`} trend={0} />
        <Metric label="最大回撤" value={`${result.max_drawdown_percent.toFixed(2)}%`} trend={-result.max_drawdown_percent} />
        <Metric label="夏普" value={result.sharpe.toFixed(2)} trend={result.sharpe} />
        <Metric label="盈亏比" value={result.profit_factor >= 99 ? "∞" : result.profit_factor.toFixed(2)} trend={result.profit_factor - 1} />
      </div>
      <p className="strategy-lab__report">
        <button
          type="button"
          onClick={() => downloadReport(result)}
        >
          导出实验报告（Markdown）
        </button>
      </p>

      <Panel
        title={`${result.instrument_id} · K 线与买卖点`}
        eyebrow="PRICE / TRADES"
        action={
          <span className="paper-strategy__version">
            {model?.strategy_version ?? result.model_id}{result.model_status === "DRAFT" ? "（草稿）" : ""}
          </span>
        }
      >
        <ProfessionalMarketChart
          instrumentId={result.instrument_id}
          period="1m"
          mainIndicator="MA"
          secondaryIndicator="VOL"
          showQuantSignals
          bars={bars}
          signals={signals}
        />
        <p className="strategy-lab__note">
          买卖点显示触发时模型上涨概率（悬停标记查看）；起点 {result.initial_cash} 现金
          {result.initial_equity > result.initial_cash ? ` + 期初持仓（初始权益 ${formatMoney(result.initial_equity)}）` : ""}
          ，期末资金 {formatMoney(result.final_cash)}，剩余持仓 {result.position_remaining} 份。
        </p>
      </Panel>

      <Panel title="权益曲线" eyebrow="EQUITY / REPLAY">
        <EquityCurve points={equity} initial={Number(result.initial_equity)} />
      </Panel>

      <div className="strategy-lab__grid">
        <Panel title="交易明细" eyebrow="TRADES / AUDIT">
          <TradeList trades={result.trades} />
        </Panel>
        <Panel title="说明" eyebrow="NOTES / HONESTY">
          <ul className="strategy-lab__notes">
            <li>确定性回放：同输入同输出，可复现。</li>
            <li>费用口径：佣金万 2.5 + 过户费（双边），未含滑点；不模拟涨跌停/停牌。</li>
            <li>信号基于已完成 1 分钟 K 线，无未来函数。</li>
            <li>模型训练区间与回放区间可能重叠，结果偏乐观；样本外以模拟盘验证为准。</li>
          </ul>
        </Panel>
      </div>
    </>
  );
}

function DailyTab({ client }: { client: ApiClient }) {
  const defaultAccount = useDefaultPaperAccountQuery(client);
  const accountId = defaultAccount.data?.account.account_id ?? null;
  const daily = useDailySummaryQuery(client, accountId);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const runs = useStrategyRunsOnDateQuery(client, accountId, selectedDate);
  const rows = daily.data ?? [];
  const selected = rows.find((row) => row.trading_date === selectedDate);

  return (
    <>
      <Panel title="每日收益" eyebrow="DAILY / PAPER ACCOUNT">
        {rows.length === 0 ? (
          <p className="strategy-lab__empty">还没有权益快照。模拟盘运行一段时间后这里会按日展示收益（自动剔除外部入金/出金）。</p>
        ) : (
          <table className="strategy-lab__daily">
            <thead>
              <tr><th>日期</th><th>策略收益</th><th>权益变动</th><th>入金/出金</th><th>成交净额</th><th>日初存档</th></tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.trading_date} data-selected={row.trading_date === selectedDate} onClick={() => setSelectedDate(row.trading_date)}>
                  <td>{row.trading_date}</td>
                  <td className={trendClass(row.strategy_pnl)}>{row.strategy_pnl_percent === null ? "—" : `${row.strategy_pnl_percent >= 0 ? "+" : ""}${row.strategy_pnl_percent.toFixed(2)}%`}</td>
                  <td>{formatSignedMoney(row.equity_pnl)}</td>
                  <td>{row.external_flow === "0" ? "—" : formatSignedMoney(row.external_flow)}</td>
                  <td>{formatSignedMoney(row.fills)}</td>
                  <td>{row.has_daily_open ? "✓" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      {selected === undefined ? null : (
        <Panel title={`${selected.trading_date} · 当天实际`} eyebrow="DAILY / ACTUAL">
          {!selected.has_daily_open ? (
            <p className="strategy-lab__warn">该日无日初存档：当天"重新回放"将使用纯现金起点，收益不可与当天实际直接对比（仅对比信号行为）。</p>
          ) : null}
          {runs.data === undefined || runs.data.length === 0 ? (
            <p className="strategy-lab__empty">当天没有策略决策记录。</p>
          ) : (
            <RunList runs={runs.data} />
          )}
        </Panel>
      )}
    </>
  );
}

function ExperimentsTab({ client }: { client: ApiClient }) {
  const experiments = useResearchExperimentsQuery(client);
  const [detail, setDetail] = useState<{ id: string; resultsJson: string; summaryJson: string; requestJson: string } | null>(null);
  const [loaded, setLoaded] = useState<ReplayResult[] | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);

  const open = async (experimentId: string) => {
    const record = await client.getResearchExperiment(experimentId);
    const parsed = JSON.parse(record.results_json) as ReplayResult[];
    setDetail({ id: record.experiment_id, resultsJson: record.results_json, summaryJson: record.summary_json, requestJson: record.request_json });
    setLoaded(parsed);
    setSelectedIndex(0);
  };

  return (
    <Panel title="历史实验" eyebrow="EXPERIMENTS / ARCHIVE">
      {experiments.data?.length === 0 ? (
        <p className="strategy-lab__empty">还没有实验。运行批量回放后自动存档。</p>
      ) : (
        <ul className="strategy-lab__experiments">
          {(experiments.data ?? []).map((item) => {
            let summary: { model_id?: string; instruments?: string[]; net_return_percent?: number; trades?: number } = {};
            try {
              summary = JSON.parse(item.summary_json);
            } catch {
              summary = {};
            }
            return (
              <li key={item.experiment_id}>
                <button type="button" onClick={() => void open(item.experiment_id)}>
                  <strong>{formatTime(item.created_at)} · {summary.model_id ?? "?"}</strong>
                  <span>{(summary.instruments ?? []).join(", ")} · 净收益 {(summary.net_return_percent ?? 0).toFixed(2)}% · {summary.trades ?? 0} 笔</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {detail !== null && loaded !== null ? (
        <div className="strategy-lab__experiment-detail">
          <div className="strategy-lab__switcher" role="tablist" aria-label="切换实验标的">
            {loaded.map((item, index) => (
              <button key={item.instrument_id} type="button" role="tab" aria-selected={index === selectedIndex} onClick={() => setSelectedIndex(index)}>
                <strong>{item.instrument_id}</strong>
                <span>{item.net_return_percent >= 0 ? "+" : ""}{item.net_return_percent.toFixed(2)}%</span>
              </button>
            ))}
          </div>
          {loaded[selectedIndex] === undefined ? null : (
            <ReplayResultView result={loaded[selectedIndex]} models={[]} />
          )}
        </div>
      ) : null}
    </Panel>
  );
}

function TrainTab({ client }: { client: ApiClient }) {
  const [instrument, setInstrument] = useState<InstrumentSelection | null>(null);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [modelId, setModelId] = useState("lgbm-" + Date.now().toString(36));
  const [training, setTraining] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    model_id: string;
    auc: number;
    net_return: number;
    trades: number;
    recommended_buy: number;
    recommended_sell: number;
  } | null>(null);

  const run = async () => {
    if (instrument === null) return;
    setTraining(true);
    setError(null);
    setResult(null);
    try {
      const data = await client.trainResearchModel({
        dataset_ids: [],
        instruments: [{
          instrument_id: instrument.instrument_id,
          start_date: startDate === "" ? null : startDate,
          end_date: endDate === "" ? null : endDate,
        }],
        model_id: modelId,
        horizon: 5,
        threshold: "0.005",
      });
      setResult({
        model_id: data.model_id,
        auc: data.auc,
        net_return: data.net_return,
        trades: data.trades,
        recommended_buy: data.recommended_buy,
        recommended_sell: data.recommended_sell,
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "训练失败");
    } finally {
      setTraining(false);
    }
  };

  return (
    <Panel title="训练新模型" eyebrow="TRAIN / LIGHTGBM">
      <div className="strategy-lab__form">
        <label>
          股票（真实搜索）
          <InstrumentSearchPicker
            client={client}
            value={instrument}
            onChange={setInstrument}
            ariaLabel="搜索训练股票"
            placeholder="输入代码或名称"
          />
        </label>
        <label>起始日期<input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
        <label>结束日期<input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label>
        <label>模型标识<input value={modelId} onChange={(event) => setModelId(event.target.value)} /></label>
        <button type="button" disabled={training || instrument === null} onClick={() => void run()}>
          {training ? "训练中…" : "开始训练"}
        </button>
      </div>
      {error !== null ? <p className="strategy-lab__error" role="alert">{error}</p> : null}
      {result === null ? null : (
        <div className="strategy-lab__metrics">
          <Metric label="AUC" value={result.auc.toFixed(4)} trend={result.auc - 0.55} />
          <Metric label="含费用净收益" value={`${result.net_return >= 0 ? "+" : ""}${(result.net_return * 100).toFixed(2)}%`} trend={result.net_return} />
          <Metric label="交易数" value={String(result.trades)} trend={0} />
          <Metric label="推荐买入阈值" value={result.recommended_buy.toFixed(2)} trend={0} />
          <Metric label="推荐卖出阈值" value={result.recommended_sell.toFixed(2)} trend={0} />
        </div>
      )}
      <p className="strategy-lab__note">训练完成后模型以草稿注册（模型列表可见），可先回放验证再批准上线。</p>
    </Panel>
  );
}

function downloadReport(result: ReplayResult) {
  const lines = [
    `# 回放实验报告 — ${result.instrument_id}`,
    "",
    `- 生成时间：${new Date().toLocaleString("zh-CN")}`,
    `- 回放区间：${formatTime(result.start)} ~ ${formatTime(result.end)}（分钟级，${result.bars_count} 根）`,
    `- 模型：${result.model_id}（${result.model_status}）`,
    `- 初始资金：${formatMoney(result.initial_cash)}${result.initial_equity > result.initial_cash ? `（含期初持仓，初始权益 ${formatMoney(result.initial_equity)}）` : ""}`,
    `- 期末资金：${formatMoney(result.final_cash)}（剩余持仓 ${result.position_remaining} 份）`,
    "",
    "## 绩效",
    "",
    `| 指标 | 数值 |`,
    `| --- | --- |`,
    `| 净收益 | ${result.net_return_percent >= 0 ? "+" : ""}${result.net_return_percent.toFixed(2)}% |`,
    `| 胜率 | ${(result.win_rate * 100).toFixed(1)}% |`,
    `| 交易 | 买入 ${result.buys} / 卖出 ${result.sells} |`,
    `| 最大回撤 | ${result.max_drawdown_percent.toFixed(2)}% |`,
    `| 夏普 | ${result.sharpe.toFixed(2)} |`,
    `| 盈亏比 | ${result.profit_factor >= 99 ? "∞" : result.profit_factor.toFixed(2)} |`,
    `| 已实现盈亏 | ${formatSignedMoney(result.realized_pnl)} |`,
    "",
    "## 交易明细",
    "",
    "| 时间 | 方向 | 价格 | 数量 | 盈亏 | 上涨概率 |",
    "| --- | --- | --- | --- | --- | --- |",
    ...result.trades.map(
      (trade) =>
        `| ${formatTime(trade.timestamp)} | ${trade.side === "BUY" ? "买入" : "卖出"} | ${trade.price} | ${trade.quantity} | ${formatSignedMoney(trade.pnl)} | ${(trade.proba * 100).toFixed(0)}% |`,
    ),
    "",
    "## 边界说明",
    "",
    "- 确定性回放，同输入同输出；费用口径佣金万 2.5 + 过户费（双边），未含滑点。",
    "- 未模拟涨跌停与停牌；信号基于已完成 1 分钟 K 线，无未来函数。",
    "- 回放区间可能与模型训练区间重叠，结果偏乐观；样本外以模拟盘验证为准。",
    "",
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `replay-report-${result.instrument_id}-${Date.now()}.md`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function RunList({ runs }: { runs: PaperStrategyRun[] }) {
  return (
    <ul className="strategy-lab__trades">
      {runs.map((run) => (
        <li key={run.decision_id} data-outcome={run.outcome.toLowerCase()}>
          <strong>{run.signal.instrument_id} · {run.outcome} · {run.signal.action}</strong>
          <span>{run.risk_reason ?? run.signal.reason_codes.join(" · ")} · {formatTime(run.signal.decision_time)}</span>
          {run.fill !== null ? <small>成交 {run.fill.quantity} 份 @ {run.fill.price}</small> : null}
        </li>
      ))}
    </ul>
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
          <span>{formatTime(trade.timestamp)} · 盈亏 {formatSignedMoney(trade.pnl)} · 上涨概率 {(trade.proba * 100).toFixed(0)}%</span>
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
function trendClass(value: string): string {
  return Number(value) >= 0 ? "paper-trend-up" : "paper-trend-down";
}
