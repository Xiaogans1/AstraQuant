import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";

function usePersistentState<T>(key: string, initial: T): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // storage unavailable: keep the in-memory value
    }
  }, [key, value]);
  return [value, setValue];
}

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
  const [added, setAdded] = usePersistentState<InstrumentSelection[]>("astraquant.lab.addedInstruments", []);
  const [removedSeeded, setRemovedSeeded] = usePersistentState<string[]>("astraquant.lab.removedSeeded", []);
  const [startDate, setStartDate] = usePersistentState<string>("astraquant.lab.startDate", "");
  const [endDate, setEndDate] = usePersistentState<string>("astraquant.lab.endDate", "");
  const [modelId, setModelId] = usePersistentState<string>("astraquant.lab.modelId", "");
  const [cash, setCash] = usePersistentState<string>("astraquant.lab.cash", "100000");
  const [fullyInvested, setFullyInvested] = usePersistentState<boolean>("astraquant.lab.fullyInvested", true);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const models = modelsQuery.data ?? [];
  const results = replay.data;

  const seeded: InstrumentSelection[] = useMemo(
    () =>
      (home.data?.watchlist ?? [])
        .filter((item) => !removedSeeded.includes(item.instrument_id))
        .map((item) => ({
          instrument_id: item.instrument_id,
          name: item.name,
          kind: item.kind,
        })),
    [home.data, removedSeeded],
  );
  const instruments = [...seeded, ...added];

  useEffect(() => {
    if (selectedIndex >= instruments.length) {
      setSelectedIndex(Math.max(instruments.length - 1, 0));
    }
  }, [instruments.length, selectedIndex]);

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
            添加股票（首页自选已自动预设）
            <InstrumentSearchPicker
              client={client}
              value={null}
              ariaLabel="搜索回放股票"
              placeholder="输入代码或名称，添加后回车选择"
              onChange={(selection) => {
                if (selection === null) return;
                if (!instruments.some((item) => item.instrument_id === selection.instrument_id)) {
                  setAdded((items) => [...items, selection]);
                }
              }}
            />
          </label>
          <div className="strategy-lab__picked">
            <span className="strategy-lab__picked-title">自选（首页）</span>
            {seeded.length === 0 ? (
              <span className="strategy-lab__picked-empty">暂无</span>
            ) : (
              seeded.map((item) => (
                <span key={item.instrument_id} className="strategy-lab__chip">
                  {item.name}
                  <button
                    type="button"
                    aria-label={`移除 ${item.name}`}
                    onClick={() =>
                      setRemovedSeeded((ids) => [...ids, item.instrument_id])
                    }
                  >
                    ×
                  </button>
                </span>
              ))
            )}
          </div>
          <div className="strategy-lab__picked">
            <span className="strategy-lab__picked-title">手动添加</span>
            {added.length === 0 ? (
              <span className="strategy-lab__picked-empty">暂无</span>
            ) : (
              added.map((item) => (
                <span key={item.instrument_id} className="strategy-lab__chip strategy-lab__chip--added">
                  {item.name}
                  <button
                    type="button"
                    aria-label={`移除 ${item.name}`}
                    onClick={() =>
                      setAdded((items) => items.filter((i) => i.instrument_id !== item.instrument_id))
                    }
                  >
                    ×
                  </button>
                </span>
              ))
            )}
          </div>
          <div className="strategy-lab__form-row">
            <label>起始日期<input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
            <label>结束日期<input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label>
          </div>
          <div className="strategy-lab__form-row">
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
          </div>
          <label className="strategy-lab__mode">
            <input
              type="checkbox"
              checked={fullyInvested}
              onChange={(event) => setFullyInvested(event.target.checked)}
            />
            起始即全仓买入（默认，T+1：当日冻结不可卖，次日按模型信号交易，与"买入持有不操作"对比）
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
  const [activeSignalId, setActiveSignalId] = useState<string | null>(null);
  const bars = useMemo(() => toChartBars(result.bars), [result.bars]);
  const pairs = useMemo(() => tradePairs(result.trades), [result.trades]);
  const signals = useMemo<MarketSignalMarker[]>(
    () =>
      result.trades
        .map((trade) => {
          const pair = trade.side === "SELL"
            ? pairs.find((item) => item.sell?.index === trade.index)
            : pairs.find((item) => item.buyIndex === trade.index && item.sell === null);
          const extra = pair === undefined || pair.sell === null
            ? ""
            : ` · 配对买入 @ ${pair.buyPrice.toFixed(4)} · 盈亏 ${formatSignedMoney(String(pair.pnl))}（${pair.pnlPercent >= 0 ? "+" : ""}${pair.pnlPercent.toFixed(1)}%）`;
          return {
            id: `replay-${trade.index}`,
            timestamp: Date.parse(trade.timestamp),
            side: trade.side,
            price: Number(trade.price),
            label: `${trade.side === "BUY" ? "回放买入" : "回放卖出"} ${trade.quantity} 份 @ ${trade.price}（概率 ${(trade.proba * 100).toFixed(0)}%）${extra}`,
            source: "REPLAY" as const,
          };
        })
        .filter((item) => Number.isFinite(item.timestamp) && Number.isFinite(item.price)),
    [result.trades, pairs],
  );
  const activePairKey = useMemo(() => {
    if (activeSignalId === null) return null;
    const index = Number(activeSignalId.slice("replay-".length));
    const pair = pairs.find(
      (item) => item.sell?.index === index || (item.sell === null && item.buyIndex === index),
    );
    return pair === undefined ? null : `${pair.buyIndex}-${pair.sell?.index ?? "open"}`;
  }, [activeSignalId, pairs]);

  const connections = useMemo(
    () =>
      pairs
        .filter((pair) => pair.sell !== null && pair.buyIndex >= 0)
        .map((pair) => ({
          fromId: `replay-${pair.buyIndex}`,
          toId: `replay-${(pair.sell as ReplayTrade).index}`,
          pnl: pair.pnl,
        })),
    [pairs],
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
        title={`${result.instrument_id} · 区间 K 线与全部买卖点（${result.bars_count} 根 1 分钟）`}
        eyebrow="RANGE / PRICE / TRADES"
        action={
          <span className="paper-strategy__version">
            {model?.strategy_version ?? result.model_id}{result.model_status === "DRAFT" ? "（草稿）" : ""}
          </span>
        }
      >
        <div className="strategy-lab__intraday">
          <ProfessionalMarketChart
            instrumentId={result.instrument_id}
            period="1m"
            mainIndicator="MA"
            secondaryIndicator="VOL"
            showQuantSignals
            bars={bars}
            signals={signals}
            activeSignalId={activeSignalId}
            onSignalSelect={setActiveSignalId}
            connections={connections}
          />
        </div>
        <p className="strategy-lab__note">
          整段区间一张图：**按住拖动平移，滚轮缩放**（"显示整体"可看全区间）；红 B / 绿 S 为全部真实模型信号。
          点击标记或在下方交易表中点击任意一行，图上会自动跳到对应买卖点并高亮。
          数据实际覆盖 {formatTime(result.start)} ~ {formatTime(result.end)}，共 {result.trades.length} 笔信号。
        </p>
      </Panel>

      <Panel title="交易盈亏对比（点击行跳到图上对应买卖点）" eyebrow="TRADES / PAIRED PNL">
        <TradePairsTable
          trades={result.trades}
          activeKey={activePairKey}
          onSelect={(pair) => {
            const signalId = pair.sell !== null ? `replay-${pair.sell.index}` : `replay-${pair.buyIndex}`;
            setActiveSignalId(signalId);
          }}
        />
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
          全仓起步当日冻结（T+1），之后完全按模型信号交易——模型信号弱时策略与持有曲线一致。
        </p>
      </Panel>

      <Panel title="说明" eyebrow="NOTES / HONESTY">
        <ul className="strategy-lab__notes">
          <li>确定性回放：同输入同输出，可复现。</li>
          <li>费用口径：佣金万 2.5 + 过户费（双边），未含滑点；不模拟涨跌停/停牌。</li>
          <li>信号基于已完成 1 分钟 K 线，无未来函数。</li>
          <li>模型训练区间与回放区间可能重叠，结果偏乐观；样本外以模拟盘验证为准。</li>
        </ul>
      </Panel>

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
  const modelsQuery = usePaperModelsQuery(client);
  const approvedModel = modelsQuery.data?.find((item) => item.status === "APPROVED") ?? null;
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const runs = useStrategyRunsOnDateQuery(client, accountId, selectedDate);
  const rows = daily.data ?? [];
  const selected = rows.find((row) => row.trading_date === selectedDate);
  const [recomputed, setRecomputed] = useState<{
    date: string;
    initialCash: string;
    results: ReplayResult[];
    error: string | null;
  } | null>(null);
  const [recomputing, setRecomputing] = useState(false);

  const recompute = async (date: string) => {
    if (accountId === null || approvedModel === null) return;
    setRecomputing(true);
    try {
      const opening = await client.getPaperDailyOpen(accountId, date);
      const positions = JSON.parse(opening.positions_json) as Array<{
        instrument_id: string;
        quantity: number;
        available_quantity: number;
        average_cost: string;
      }>;
      const results = await client.runResearchReplay({
        instruments: positions.map((position) => ({
          instrument_id: position.instrument_id,
          start_date: date,
          end_date: date,
          opening: position,
        })),
        model_id: approvedModel.model_id,
        initial_cash: opening.cash,
        fully_invested: false,
      });
      setRecomputed({ date, initialCash: opening.cash, results, error: null });
    } catch (caught) {
      setRecomputed({
        date,
        initialCash: "",
        results: [],
        error: caught instanceof Error ? caught.message : "重算失败",
      });
    } finally {
      setRecomputing(false);
    }
  };

  const recomputeTotal = recomputed?.results.reduce(
    (total, item) => total + Number(item.final_cash) - Number(item.initial_equity),
    0,
  ) ?? 0;
  const recomputePercent = recomputed !== null && Number(recomputed.initialCash) > 0
    ? (recomputeTotal / Number(recomputed.initialCash)) * 100
    : 0;

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
        <Panel title={`${selected.trading_date} · 当天实际 vs 同起点重算`} eyebrow="DAILY / ACTUAL VS RECOMPUTE">
          <div className="strategy-lab__recompute">
            <div>
              <strong>当天实际</strong>
              <span className={trendClass(selected.strategy_pnl)}>
                {selected.strategy_pnl_percent === null ? "—" : `${selected.strategy_pnl_percent >= 0 ? "+" : ""}${selected.strategy_pnl_percent.toFixed(2)}%`}
                {selected.strategy_pnl === "0" ? "" : `（${formatSignedMoney(selected.strategy_pnl)}）`}
              </span>
              <small>已剔除入金/出金 {selected.external_flow === "0" ? "无" : formatSignedMoney(selected.external_flow)}</small>
            </div>
            <button
              type="button"
              disabled={recomputing || approvedModel === null}
              onClick={() => void recompute(selected.trading_date)}
            >
              {recomputing ? "重算中…" : "以日初持仓同起点重算"}
            </button>
          </div>
          {approvedModel === null ? (
            <p className="strategy-lab__note">需要先批准一个模型才能重算。</p>
          ) : null}
          {!selected.has_daily_open ? (
            <p className="strategy-lab__warn">该日无日初存档：重算使用纯现金起点，收益不可与当天实际直接对比（仅对比信号行为）。</p>
          ) : null}
          {recomputed !== null && recomputed.date === selected.trading_date ? (
            recomputed.error !== null ? (
              <p className="strategy-lab__error" role="alert">{recomputed.error}</p>
            ) : (
              <>
                <div className="strategy-lab__recompute-result" data-trend={recomputePercent >= 0 ? "up" : "down"}>
                  <strong>同起点重算收益</strong>
                  <span>{recomputePercent >= 0 ? "+" : ""}{recomputePercent.toFixed(2)}%（{formatSignedMoney(String(recomputeTotal))}）</span>
                  <small>
                    实际 {selected.strategy_pnl_percent === null ? "—" : `${selected.strategy_pnl_percent >= 0 ? "+" : ""}${selected.strategy_pnl_percent.toFixed(2)}%`}
                    {selected.strategy_pnl_percent === null ? "" : ` vs 重算 ${recomputePercent >= 0 ? "+" : ""}${recomputePercent.toFixed(2)}% → 差值 ${recomputePercent - (selected.strategy_pnl_percent ?? 0) >= 0 ? "+" : ""}${(recomputePercent - (selected.strategy_pnl_percent ?? 0)).toFixed(2)}%`}
                  </small>
                </div>
                <ul className="strategy-lab__recompute-list">
                  {recomputed.results.map((item) => (
                    <li key={item.instrument_id} data-trend={item.net_return_percent >= 0 ? "up" : "down"}>
                      <strong>{item.instrument_id}</strong>
                      <span>收益 {item.net_return_percent >= 0 ? "+" : ""}{item.net_return_percent.toFixed(2)}% · {item.buys}/{item.sells} 笔 · 期初持仓 {item.initial_equity > item.initial_cash ? "含持仓" : "无"}</span>
                    </li>
                  ))}
                </ul>
              </>
            )
          ) : null}
          {runs.data === undefined || runs.data.length === 0 ? (
            <p className="strategy-lab__empty">当天没有策略决策记录。</p>
          ) : (
            <>
              <h3 className="strategy-lab__subtitle">当天实际决策</h3>
              <RunList runs={runs.data} />
            </>
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
  const width = 1200;
  const height = 400;
  const project = (points: Array<readonly [number, number]>) =>
    points.map(([, value], index) => {
      const x = (index / (points.length - 1)) * width;
      const y = height - ((value - min) / range) * (height - 40) - 20;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    });
  return (
    <svg className="strategy-lab__equity" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="策略权益与买入持有基准对比曲线">
      <line x1="0" y1={height / 2} x2={width} y2={height / 2} stroke="var(--border)" />
      <polyline points={project(buyHold).join(" ")} fill="none" stroke="var(--text-muted)" strokeWidth="2" strokeDasharray="5 5" />
      <polyline points={project(strategy).join(" ")} fill="none" stroke="var(--accent)" strokeWidth="3" />
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
  const width = 1200;
  const height = 400;
  const coords = parsed.map(([, value], index) => {
    const x = (index / (parsed.length - 1)) * width;
    const y = height - ((value - min) / range) * (height - 40) - 20;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  const markers = trades
    .map((trade) => {
      const time = Date.parse(trade.timestamp);
      const barIndex = parsed.findIndex(([timestamp]) => timestamp === time);
      if (barIndex < 0) return null;
      const x = (barIndex / (parsed.length - 1)) * width;
      const y = height - ((parsed[barIndex][1] - min) / range) * (height - 40) - 20;
      return { trade, x, y };
    })
    .filter((item): item is { trade: ReplayTrade; x: number; y: number } => item !== null);
  return (
    <svg className="strategy-lab__equity strategy-lab__equity--value" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="持仓市值曲线">
      <line x1="0" y1={height / 2} x2={width} y2={height / 2} stroke="var(--border)" />
      <polyline points={coords.join(" ")} fill="none" stroke="var(--accent)" strokeWidth="2.5" />
      {markers.map(({ trade, x, y }) => (
        <circle
          key={`${trade.index}-${trade.side}`}
          cx={x}
          cy={y}
          r="5"
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
  const width = 1200;
  const height = 400;
  const coords = points.map(([timestamp, value], index) => {
    const x = (index / (points.length - 1)) * width;
    const y = height - ((value - min) / range) * (height - 40) - 20;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  return (
    <svg className="strategy-lab__equity" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="回放权益曲线">
      <line x1="0" y1={height / 2} x2={width} y2={height / 2} stroke="var(--border)" />
      <polyline points={coords.join(" ")} fill="none" stroke="var(--accent)" strokeWidth="2.5" />
    </svg>
  );
}

interface TradePair {
  buyIndex: number;
  buyTime: string;
  buyPrice: number;
  quantity: number;
  sell: ReplayTrade | null;
  pnl: number;
  pnlPercent: number;
}

function tradePairs(trades: ReplayTrade[]): TradePair[] {
  const rows: TradePair[] = [];
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
      const hasOpenCost = openQty > 0;
      const buyCost = hasOpenCost ? openCost * trade.quantity : 0;
      const pnl = Number(trade.pnl);
      rows.push({
        buyIndex: openIndex,
        buyTime: openTime,
        buyPrice: hasOpenCost ? openCost : 0,
        quantity: trade.quantity,
        sell: trade,
        pnl,
        pnlPercent: hasOpenCost && buyCost > 0 ? (pnl / buyCost) * 100 : 0,
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

function TradePairsTable({
  trades,
  activeKey = null,
  onSelect,
}: {
  trades: ReplayTrade[];
  activeKey?: string | null;
  onSelect?: (pair: TradePair) => void;
}) {
  const pairs = useMemo(() => tradePairs(trades), [trades]);
  if (pairs.length === 0) {
    return <p className="strategy-lab__empty">该时段没有触发交易。</p>;
  }
  const pairKey = (pair: TradePair) => `${pair.buyIndex}-${pair.sell?.index ?? "open"}`;
  return (
    <div className="strategy-lab__pairs-wrap">
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
          const fromOpening = pair.buyTime === "";
          const holdMs = pair.sell === null
            ? 0
            : Date.parse(pair.sell.timestamp) - (fromOpening ? Date.parse(pair.sell.timestamp) : Date.parse(pair.buyTime));
          const holdMinutes = holdMs / 1000 / 60;
          const holdText = fromOpening || !Number.isFinite(holdMinutes)
            ? "—"
            : holdMinutes < 60
              ? `${Math.round(holdMinutes)}分钟`
              : `${(holdMinutes / 60).toFixed(1)}小时`;
          return (
            <tr
              key={`${pair.buyIndex}-${pair.sell?.index ?? "open"}`}
              data-pnl={pair.sell === null ? "open" : pair.pnl >= 0 ? "up" : "down"}
              data-active={pairKey(pair) === activeKey}
              onClick={() => onSelect?.(pair)}
            >
              <td>{fromOpening ? "期初持仓" : formatTime(pair.buyTime)}</td>
              <td>{fromOpening ? "—" : pair.buyPrice.toFixed(4)}</td>
              <td>{pair.quantity}</td>
              <td>{pair.sell === null ? "持仓中" : formatTime(pair.sell.timestamp)}</td>
              <td>{pair.sell === null ? "—" : pair.sell.price}</td>
              <td>{pair.sell === null ? "—" : holdText}</td>
              <td>{pair.sell === null ? "—" : formatSignedMoney(String(pair.pnl))}</td>
              <td>{pair.sell === null || fromOpening ? "—" : `${pair.pnlPercent >= 0 ? "+" : ""}${pair.pnlPercent.toFixed(2)}%`}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
    </div>
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
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return "—";
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(parsed));
}
function trendClass(value: string): string {
  return Number(value) >= 0 ? "paper-trend-up" : "paper-trend-down";
}
