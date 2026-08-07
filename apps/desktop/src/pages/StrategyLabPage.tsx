import { useEffect, useMemo, useRef, useState } from "react";

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
  useMarketHomeQuery,
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
  const home = useMarketHomeQuery(client);
  const replay = useResearchReplayMutation(client);
  const [instruments, setInstruments] = useState<InstrumentSelection[]>([]);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [modelId, setModelId] = useState("");
  const [cash, setCash] = useState("100000");
  const [fullyInvested, setFullyInvested] = useState(true);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const seededRef = useRef(false);
  const models = modelsQuery.data ?? [];
  const results = replay.data;

  useEffect(() => {
    if (seededRef.current || home.isLoading) return;
    const list = home.data?.watchlist ?? [];
    if (list.length > 0) {
      setInstruments(
        list.map((item) => ({
          instrument_id: item.instrument_id,
          name: item.name,
          kind: item.kind,
        })),
      );
      setSelectedIndex(0);
    }
    seededRef.current = true;
  }, [home.data, home.isLoading]);

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
      fully_invested: fullyInvested,
    });
  };

  const current: ReplayResult | undefined = results?.[selectedIndex];

  return (
    <>
      <Panel title="批量回放" eyebrow="REPLAY / ANY INSTRUMENT">
        <div className="strategy-lab__form">
          <label>
            股票（已预设首页自选，可继续添加）
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
          <label className="strategy-lab__mode">
            <input
              type="checkbox"
              checked={fullyInvested}
              onChange={(event) => setFullyInvested(event.target.checked)}
            />
            起始即全仓买入（默认，与"买入持有不操作"对比）
          </label>
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
  const days = useMemo(() => {
    const groups = new Map<string, { bars: MarketBar[]; signals: MarketSignalMarker[] }>();
    for (const bar of bars) {
      const day = shanghaiDay(bar.timestamp);
      const group = groups.get(day) ?? { bars: [], signals: [] };
      group.bars.push(bar);
      groups.set(day, group);
    }
    for (const signal of signals) {
      const day = shanghaiDay(new Date(signal.timestamp).toISOString());
      const group = groups.get(day);
      if (group !== undefined) group.signals.push(signal);
    }
    return [...groups.entries()].sort(([left], [right]) => left.localeCompare(right));
  }, [bars, signals]);
  const [selectedDay, setSelectedDay] = useState<string>(days.at(-1)?.[0] ?? "");
  useEffect(() => {
    setSelectedDay((current) => {
      if (current !== "" && days.some(([day]) => day === current)) return current;
      return days.at(-1)?.[0] ?? "";
    });
  }, [days]);
  const selected = days.find(([day]) => day === selectedDay);
  const dayBars = selected?.[1].bars ?? [];
  const daySignals = selected?.[1].signals ?? [];
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
        <Metric label="策略净收益" value={`${result.net_return_percent >= 0 ? "+" : ""}${result.net_return_percent.toFixed(2)}%`} trend={result.net_return_percent} />
        <Metric label="买入持有基准" value={`${result.buy_hold_return_percent >= 0 ? "+" : ""}${result.buy_hold_return_percent.toFixed(2)}%`} trend={result.buy_hold_return_percent} />
        <Metric label="超额收益（策略−持有）" value={`${result.excess_return_percent >= 0 ? "+" : ""}${result.excess_return_percent.toFixed(2)}%`} trend={result.excess_return_percent} />
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
        title={`${result.instrument_id} · 区间全览（${result.bars_count} 根 1 分钟线）`}
        eyebrow="OVERVIEW / SELECTED WINDOW"
        action={
          <span className="paper-strategy__version">
            {model?.strategy_version ?? result.model_id}{result.model_status === "DRAFT" ? "（草稿）" : ""}
          </span>
        }
      >
        <ReplayOverview result={result} />
        <p className="strategy-lab__note">
          全览展示所选区间完整走势与全部买卖点：红色 B = 模型买入，绿色 S = 模型卖出（悬停查看时间与上涨概率）。
          数据实际覆盖 {formatTime(result.start)} ~ {formatTime(result.end)}（东财分钟线，历史深度以数据源为准）。
        </p>
      </Panel>

      <Panel
        title={`${result.instrument_id} · 分时与买卖点（${selectedDay}）`}
        eyebrow="INTRADAY / PRICE / TRADES"
        action={
          <div className="strategy-lab__day-switcher" role="tablist" aria-label="切换分时日期">
            {days.map(([day]) => (
              <button
                key={day}
                type="button"
                role="tab"
                aria-selected={day === selectedDay}
                onClick={() => setSelectedDay(day)}
              >
                {day.slice(5)}
              </button>
            ))}
          </div>
        }
      >
        {dayBars.length === 0 ? (
          <p className="strategy-lab__empty">该日没有分钟数据（可能为节假日或数据源缺失）。</p>
        ) : (
          <>
            <div className="strategy-lab__intraday">
              <ProfessionalMarketChart
                instrumentId={result.instrument_id}
                period="intraday"
                mainIndicator="MA"
                secondaryIndicator="VOL"
                showQuantSignals
                bars={dayBars}
                signals={daySignals}
              />
            </div>
            <p className="strategy-lab__note">
              与首页一致的分时图：默认展示区间最后一天，可点击上方日期切换任意交易日；
              红 B / 绿 S 为该日真实模型信号（悬停查看时间与上涨概率）。共 {result.trades.length} 笔信号。
            </p>
          </>
        )}
      </Panel>

      <Panel title="权益曲线：策略 vs 买入持有" eyebrow="EQUITY / VS BUY & HOLD">
        <DualEquityCurve
          strategy={equity}
          buyHold={result.buy_hold_equity_points
            .filter(([timestamp]) => Number.isFinite(Date.parse(timestamp)))
            .map(([timestamp, value]) => [Date.parse(timestamp), Number(value)] as const)}
          initial={Number(result.initial_equity)}
        />
        <p className="strategy-lab__note">
          青色 = 策略实际权益；灰色 = 同样资金全仓买入持有不动（{result.buy_hold_return_percent >= 0 ? "+" : ""}{result.buy_hold_return_percent.toFixed(2)}%）。
          超额 {result.excess_return_percent >= 0 ? "+" : ""}{result.excess_return_percent.toFixed(2)}%。
        </p>
      </Panel>

      <div className="strategy-lab__grid">
        <Panel title="交易盈亏对比" eyebrow="TRADES / PAIRED PNL">
          <TradePairsTable trades={result.trades} />
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

      <Panel title="持仓金额曲线" eyebrow="POSITION VALUE / REPLAY">
        <PositionValueCurve
          points={result.position_value_points}
          trades={result.trades}
        />
        <p className="strategy-lab__note">
          每分钟持仓市值（数量 × 收盘价）；B 点后市值抬升表示建仓/加仓，S 点后回落表示卖出。
        </p>
      </Panel>
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

function ReplayOverview({ result }: { result: ReplayResult }) {
  const [selectedTrade, setSelectedTrade] = useState<ReplayTrade | null>(null);
  const pairs = useMemo(() => tradePairs(result.trades), [result.trades]);
  const points = useMemo(() => {
    const closes = result.bars.map((bar) => Number(bar.close));
    if (closes.length < 2) return null;
    const min = Math.min(...closes);
    const max = Math.max(...closes);
    const range = Math.max(max - min, 1e-9);
    const width = 100;
    const height = 100;
    const step = width / (closes.length - 1);
    return {
      line: closes.map((close, index) => {
        const x = index * step;
        const y = height - ((close - min) / range) * (height - 8) - 4;
        return `${x.toFixed(3)},${y.toFixed(3)}`;
      }),
      xOf: (index: number) => Math.min(index, closes.length - 1) * step,
      yOf: (close: number) => height - ((close - min) / range) * (height - 8) - 4,
      min,
      max,
    };
  }, [result]);

  if (points === null) {
    return <p className="strategy-lab__empty">数据不足，无法绘制全览。</p>;
  }
  const selectedPair = selectedTrade === null
    ? null
    : pairs.find((pair) => pair.sell?.index === selectedTrade.index) ?? null;
  return (
    <div className="strategy-lab__overview">
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        role="img"
        aria-label="区间全览：完整走势与买卖配对"
        className="strategy-lab__overview-svg"
      >
        <line x1="0" y1="50" x2="100" y2="50" stroke="var(--border)" strokeDasharray="2 2" />
        <polyline
          points={points.line.join(" ")}
          fill="none"
          stroke="var(--accent)"
          strokeWidth="0.55"
        />
        {pairs.map((pair) => {
          if (pair.sell === null) return null;
          return (
            <line
              key={`pair-${pair.buyIndex}`}
              x1={points.xOf(pair.buyIndex)}
              y1={points.yOf(pair.buyPrice)}
              x2={points.xOf(pair.sell.index)}
              y2={points.yOf(Number(pair.sell.price))}
              stroke={pair.pnl >= 0 ? "#21ad76" : "#ef5b5b"}
              strokeWidth="0.35"
              strokeDasharray="1.2 1.2"
              opacity="0.75"
            >
              <title>{`盈亏 ${formatSignedMoney(String(pair.pnl))}（${pair.pnlPercent.toFixed(1)}%）`}</title>
            </line>
          );
        })}
        {result.trades.map((trade) => {
          const x = points.xOf(trade.index);
          const y = points.yOf(Number(trade.price));
          const isSelected = selectedPair !== null && selectedPair.sell?.index === trade.index;
          return (
            <g key={`${trade.index}-${trade.side}`} className="strategy-lab__overview-point">
              <circle
                cx={x}
                cy={y}
                r={isSelected ? 2.6 : 2.0}
                fill={trade.side === "BUY" ? "#ef5b5b" : "#21ad76"}
                stroke={isSelected ? "#fff" : "none"}
                strokeWidth="0.4"
              >
                <title>{`${trade.side === "BUY" ? "模型买入" : "模型卖出"} ${trade.quantity} 份 @ ${trade.price}（上涨概率 ${(trade.proba * 100).toFixed(0)}%，${formatTime(trade.timestamp)}）`}</title>
              </circle>
              <text
                x={x}
                y={trade.side === "BUY" ? y - 4.2 : y + 5.6}
                textAnchor="middle"
                fontSize="4.6"
                fontWeight="bold"
                fill={trade.side === "BUY" ? "#ef5b5b" : "#21ad76"}
              >
                {trade.side === "BUY" ? "B" : "S"}
              </text>
              <text
                x={x}
                y={y - (trade.side === "BUY" ? 7.4 : -8.2)}
                textAnchor="middle"
                fontSize="3.4"
                fill="var(--text-muted)"
              >
                {trade.quantity / 100}手
              </text>
              <rect
                x={x - 3}
                y={y - 3}
                width="6"
                height="6"
                fill="transparent"
                role="presentation"
                onClick={() => setSelectedTrade(selectedTrade?.index === trade.index ? null : trade)}
              >
                <title>{`${trade.side === "BUY" ? "模型买入" : "模型卖出"} ${trade.quantity} 份 @ ${trade.price}（上涨概率 ${(trade.proba * 100).toFixed(0)}%，${formatTime(trade.timestamp)}）`}</title>
              </rect>
            </g>
          );
        })}
      </svg>
      {selectedPair === null ? (
        <div className="strategy-lab__overview-legend">
          <span>区间 {formatTime(result.start)} ~ {formatTime(result.end)}</span>
          <span>最高 {points.max.toFixed(4)} / 最低 {points.min.toFixed(4)}</span>
          <span>{result.trades.length} 笔信号（B {result.buys} / S {result.sells}），点击任意点查看买卖配对盈亏</span>
        </div>
      ) : (
        <div
          className="strategy-lab__overview-detail"
          data-pnl={selectedPair.pnl >= 0 ? "up" : "down"}
        >
          <strong>
            买入 {selectedPair.quantity} 份 @ {selectedPair.buyPrice.toFixed(4)}（{formatTime(selectedPair.buyTime)}）
          </strong>
          <span>
            {selectedPair.sell === null ? (
              "持仓中（未卖出）"
            ) : (
              <>卖出 {selectedPair.sell.quantity} 份 @ {selectedPair.sell.price}（{formatTime(selectedPair.sell.timestamp)}） · 盈亏 <b>{formatSignedMoney(String(selectedPair.pnl))}（{selectedPair.pnlPercent.toFixed(1)}%）</b></>
            )}
          </span>
        </div>
      )}
      <p className="strategy-lab__note">
        虚线为买入→卖出配对（绿=盈利，红=亏损）；"x手"为买入/卖出数量；悬停或点击查看数量、价格与盈亏。
      </p>
    </div>
  );
}

function tradePairs(trades: ReplayTrade[]): Array<{
  buyIndex: number;
  buyTime: string;
  buyPrice: number;
  quantity: number;
  sell: ReplayTrade | null;
  pnl: number;
  pnlPercent: number;
}> {
  const rows: Array<{
    buyIndex: number;
    buyTime: string;
    buyPrice: number;
    quantity: number;
    sell: ReplayTrade | null;
    pnl: number;
    pnlPercent: number;
  }> = [];
  let openQty = 0;
  let openCost = 0;
  let openIndex = -1;
  let openTime = "";
  for (const trade of trades) {
    if (trade.side === "BUY") {
      openCost = (openCost * openQty + Number(trade.price) * trade.quantity) / (openQty + trade.quantity);
      openQty += trade.quantity;
      if (openIndex < 0) {
        openIndex = trade.index;
        openTime = trade.timestamp;
      }
    } else {
      const buyCost = openQty > 0 ? openCost * trade.quantity : Number(trade.price) * trade.quantity;
      const pnl = Number(trade.pnl);
      rows.push({
        buyIndex: openIndex,
        buyTime: openTime,
        buyPrice: openCost,
        quantity: trade.quantity,
        sell: trade,
        pnl,
        pnlPercent: buyCost > 0 ? (pnl / buyCost) * 100 : 0,
      });
      openQty = Math.max(openQty - trade.quantity, 0);
      if (openQty === 0) {
        openCost = 0;
        openIndex = -1;
        openTime = "";
      }
    }
  }
  if (openQty > 0) {
    rows.push({
      buyIndex: openIndex,
      buyTime: openTime,
      buyPrice: openCost,
      quantity: openQty,
      sell: null,
      pnl: 0,
      pnlPercent: 0,
    });
  }
  return rows;
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

function shanghaiDay(timestampIso: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(timestampIso));
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

function DualEquityCurve({
  strategy,
  buyHold,
  initial,
}: {
  strategy: Array<readonly [number, number]>;
  buyHold: Array<readonly [number, number]>;
  initial: number;
}) {
  if (strategy.length < 2) {
    return <p className="strategy-lab__empty">等待回放数据生成权益曲线</p>;
  }
  const all = [initial, ...strategy.map(([, value]) => value), ...buyHold.map(([, value]) => value)];
  const min = Math.min(...all);
  const max = Math.max(...all);
  const range = Math.max(max - min, 1);
  const width = 100;
  const height = 40;
  const project = (points: Array<readonly [number, number]>) =>
    points.map(([, value], index) => {
      const x = (index / (points.length - 1)) * width;
      const y = height - ((value - min) / range) * (height - 4) - 2;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    });
  return (
    <svg className="strategy-lab__equity" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="策略权益与买入持有基准对比曲线">
      <line x1="0" y1={height / 2} x2={width} y2={height / 2} stroke="var(--border)" />
      <polyline points={project(buyHold).join(" ")} fill="none" stroke="var(--text-muted)" strokeWidth="0.9" strokeDasharray="1.5 1.5" />
      <polyline points={project(strategy).join(" ")} fill="none" stroke="var(--accent)" strokeWidth="1.4" />
    </svg>
  );
}

function PositionValueCurve({
  points,
  trades,
}: {
  points: Array<[string, string]>;
  trades: ReplayTrade[];
}) {
  const parsed = useMemo(
    () =>
      points
        .filter(([timestamp]) => Number.isFinite(Date.parse(timestamp)))
        .map(([timestamp, value]) => [Date.parse(timestamp), Number(value)] as const),
    [points],
  );
  if (parsed.length < 2) {
    return <p className="strategy-lab__empty">等待回放数据生成持仓市值曲线</p>;
  }
  const values = parsed.map(([, value]) => value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(max - min, 1);
  const width = 100;
  const height = 40;
  const coords = parsed.map(([timestamp, value], index) => {
    const x = (index / (parsed.length - 1)) * width;
    const y = height - ((value - min) / range) * (height - 4) - 2;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  const markers = trades
    .map((trade) => {
      const time = Date.parse(trade.timestamp);
      const barIndex = parsed.findIndex(([timestamp]) => timestamp === time);
      if (barIndex < 0) return null;
      const x = (barIndex / (parsed.length - 1)) * width;
      const y = height - ((parsed[barIndex][1] - min) / range) * (height - 4) - 2;
      return { trade, x, y };
    })
    .filter((item): item is { trade: ReplayTrade; x: number; y: number } => item !== null);
  return (
    <svg className="strategy-lab__equity strategy-lab__equity--value" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="持仓市值曲线">
      <line x1="0" y1={height / 2} x2={width} y2={height / 2} stroke="var(--border)" />
      <polyline points={coords.join(" ")} fill="none" stroke="var(--accent)" strokeWidth="1.2" />
      {markers.map(({ trade, x, y }) => (
        <circle
          key={`${trade.index}-${trade.side}`}
          cx={x}
          cy={y}
          r="1.6"
          fill={trade.side === "BUY" ? "#ef5b5b" : "#21ad76"}
        >
          <title>{`${trade.side === "BUY" ? "模型买入" : "模型卖出"} ${trade.quantity} 份 @ ${trade.price}（${formatTime(trade.timestamp)}）`}</title>
        </circle>
      ))}
    </svg>
  );
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

function TradePairsTable({ trades }: { trades: ReplayTrade[] }) {
  const pairs = useMemo(() => tradePairs(trades), [trades]);
  if (pairs.length === 0) {
    return <p className="strategy-lab__empty">该时段没有触发交易。</p>;
  }
  return (
    <table className="strategy-lab__pairs">
      <thead>
        <tr>
          <th>买入时间</th>
          <th>买入价</th>
          <th>数量</th>
          <th>卖出时间</th>
          <th>卖出价</th>
          <th>持有</th>
          <th>盈亏</th>
          <th>盈亏%</th>
        </tr>
      </thead>
      <tbody>
        {pairs.map((pair) => {
          const holdMs = pair.sell === null
            ? Date.now() - Date.parse(pair.buyTime)
            : Date.parse(pair.sell.timestamp) - Date.parse(pair.buyTime);
          const holdDays = Math.max(holdMs / 1000 / 60, 1);
          const holdText = holdDays < 60 ? `${Math.round(holdDays)}分钟` : `${(holdDays / 60).toFixed(1)}小时`;
          return (
            <tr key={`${pair.buyIndex}-${pair.sell?.index ?? "open"}`} data-pnl={pair.sell === null ? "open" : pair.pnl >= 0 ? "up" : "down"}>
              <td>{formatTime(pair.buyTime)}</td>
              <td>{pair.buyPrice.toFixed(4)}</td>
              <td>{pair.quantity}</td>
              <td>{pair.sell === null ? "持仓中" : formatTime(pair.sell.timestamp)}</td>
              <td>{pair.sell === null ? "—" : pair.sell.price}</td>
              <td>{pair.sell === null ? "—" : holdText}</td>
              <td>{pair.sell === null ? "—" : formatSignedMoney(String(pair.pnl))}</td>
              <td>{pair.sell === null ? "—" : `${pair.pnlPercent >= 0 ? "+" : ""}${pair.pnlPercent.toFixed(2)}%`}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
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
