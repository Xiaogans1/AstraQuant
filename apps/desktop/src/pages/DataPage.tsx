import { useState } from "react";

import type {
  BarPreview,
  DataImportRequest,
  DatasetSummary,
  SnapshotSummary,
} from "../api/data-contracts";
import type { Task } from "../api/contracts";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";
import { QualityBadge } from "../components/QualityBadge";

interface DataPageProps {
  datasets: DatasetSummary[];
  snapshots: SnapshotSummary[];
  bars: BarPreview[];
  selectedDatasetId: string | null;
  importing: boolean;
  loading: boolean;
  stale: boolean;
  importTask?: Task | null;
  importError?: string | null;
  onImport: (request: DataImportRequest) => void;
  onSelectDataset: (datasetId: string) => void;
}

const initialRequest: DataImportRequest = {
  provider: "fixture",
  instrument_id: "600000.SSE",
  frequency: "1d",
  start: "2026-07-20",
  end: "2026-07-24",
  adjustment: "none",
};

export function DataPage({
  datasets,
  snapshots,
  bars,
  selectedDatasetId,
  importing,
  loading,
  stale,
  importTask = null,
  importError = null,
  onImport,
  onSelectDataset,
}: DataPageProps) {
  const [request, setRequest] = useState(initialRequest);
  const latestSnapshot = snapshots[0];

  return (
    <div className="page-stack data-page">
      {stale ? (
        <div className="stale-banner" role="status">
          <strong>本地数据服务暂时离线</strong>
          <span>已加载的目录仍可查看，导入已暂停。</span>
        </div>
      ) : null}

      <section className="data-locality" aria-label="本地数据处理边界">
        <div className="data-locality__copy">
          <p className="panel__eyebrow">LOCAL DATA PULSE</p>
          <h2>数据只保存在本机</h2>
          <p>不包含账户或下单连接</p>
        </div>
        <ol className="data-pulse">
          <li data-active="true"><span>01</span>只读来源</li>
          <li data-active="true"><span>02</span>质量校验</li>
          <li data-active={latestSnapshot !== undefined}><span>03</span>不可变快照</li>
        </ol>
      </section>

      <div className="data-workbench">
        <div className="data-workbench__left">
          <Panel title="导入本地样例" eyebrow="IMPORT / READ ONLY">
            <form
              className="data-import-form"
              onSubmit={(event) => {
                event.preventDefault();
                onImport(request);
              }}
            >
              <label>
                <span>市场样例</span>
                <select
                  value={request.instrument_id}
                  onChange={(event) => {
                    const instrument = event.target.value;
                    setRequest((current) => ({
                      ...current,
                      instrument_id: instrument,
                      adjustment: instrument.endsWith(".SHFE")
                        ? "none"
                        : current.adjustment,
                    }));
                  }}
                >
                  <option value="600000.SSE">浦发银行 · 600000.SSE</option>
                  <option value="RB0.SHFE">螺纹连续 · RB0.SHFE</option>
                </select>
              </label>
              <div className="data-import-form__dates">
                <label>
                  <span>开始日期</span>
                  <input
                    type="date"
                    value={request.start}
                    onChange={(event) =>
                      setRequest((current) => ({
                        ...current,
                        start: event.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  <span>结束日期</span>
                  <input
                    type="date"
                    value={request.end}
                    onChange={(event) =>
                      setRequest((current) => ({
                        ...current,
                        end: event.target.value,
                      }))
                    }
                  />
                </label>
              </div>
              <label>
                <span>复权方式</span>
                <select
                  value={request.adjustment}
                  disabled={request.instrument_id.endsWith(".SHFE")}
                  onChange={(event) =>
                    setRequest((current) => ({
                      ...current,
                      adjustment: event.target
                        .value as DataImportRequest["adjustment"],
                    }))
                  }
                >
                  <option value="none">不复权</option>
                  <option value="qfq">前复权</option>
                  <option value="hfq">后复权</option>
                </select>
              </label>
              <button
                className="button button--primary"
                type="submit"
                disabled={importing || stale || request.end < request.start}
              >
                {importing ? "正在导入…" : "导入示例数据"}
              </button>
            </form>
            {importTask !== null ? (
              <div className="data-import-status" role="status">
                <div>
                  <span>后台导入任务</span>
                  <strong>{formatTaskStep(importTask.current_step)}</strong>
                  <small>可在任务中心查看完整记录</small>
                </div>
                <span>{importTask.progress}%</span>
              </div>
            ) : null}
            {importError !== null ? (
              <p className="form-error">{importError}</p>
            ) : null}
          </Panel>

          <Panel title="本地数据集" eyebrow={`CATALOG / ${datasets.length}`}>
            {loading ? (
              <p className="data-muted">正在读取本地目录…</p>
            ) : datasets.length === 0 ? (
              <EmptyState
                title="还没有本地快照"
                description="先导入一个合成样例，验证行情、质量检查和本地存储闭环。"
              />
            ) : (
              <div className="dataset-list">
                {datasets.map((dataset) => (
                  <button
                    key={dataset.dataset_id}
                    type="button"
                    aria-pressed={dataset.dataset_id === selectedDatasetId}
                    onClick={() => onSelectDataset(dataset.dataset_id)}
                  >
                    <span className="dataset-list__class">
                      {dataset.asset_class === "equity" ? "A 股" : "期货"}
                    </span>
                    <strong>{dataset.name}</strong>
                    <small>
                      {dataset.frequency} · {dataset.snapshot_count} 个快照
                    </small>
                  </button>
                ))}
              </div>
            )}
          </Panel>
        </div>

        <Panel
          className="snapshot-panel"
          title="快照检查"
          eyebrow="QUALITY / POINT-IN-TIME"
          action={
            latestSnapshot ? (
              <button
                className="button"
                type="button"
                disabled={latestSnapshot.status !== "PUBLISHED"}
              >
                作为特征输入
              </button>
            ) : undefined
          }
        >
          {latestSnapshot === undefined ? (
            <EmptyState
              title="选择一个数据集"
              description="这里会展示最新快照的时间覆盖、质量问题和最近十条数据。"
            />
          ) : (
            <SnapshotDetail snapshot={latestSnapshot} bars={bars} />
          )}
        </Panel>
      </div>
    </div>
  );
}

function SnapshotDetail({
  snapshot,
  bars,
}: {
  snapshot: SnapshotSummary;
  bars: BarPreview[];
}) {
  return (
    <div className="snapshot-detail">
      <div className="snapshot-metrics">
        <div><span>状态</span><strong>{snapshot.status}</strong></div>
        <div><span>数据行</span><strong>{snapshot.row_count}</strong></div>
        <div><span>来源</span><strong>{snapshot.provider_id}</strong></div>
        <div><span>生成时间</span><strong>{formatTime(snapshot.created_at)}</strong></div>
      </div>
      <div className="snapshot-range">
        <span>{formatTime(snapshot.min_event_time)}</span>
        <i aria-hidden="true" />
        <span>{formatTime(snapshot.max_event_time)}</span>
      </div>
      <section className="quality-section">
        <h3>质量报告</h3>
        {snapshot.quality_issues.length === 0 ? (
          <p className="quality-clear"><span aria-hidden="true">✓</span>质量检查通过</p>
        ) : (
          <ul>
            {snapshot.quality_issues.map((issue) => (
              <li key={`${issue.code}-${issue.severity}`}>
                <QualityBadge issue={issue} />
                <div>
                  <strong>{issue.code}</strong>
                  <small>{issue.count} 项 · {formatIssueSamples(issue.samples)}</small>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      <div className="bar-table-wrap">
        <table className="bar-table">
          <thead>
            <tr>
              <th>交易时间</th>
              <th>可用时间</th>
              <th>开盘</th>
              <th>最高</th>
              <th>最低</th>
              <th>收盘</th>
              <th>成交量</th>
            </tr>
          </thead>
          <tbody>
            {bars.map((bar) => (
              <tr key={`${bar.instrument_id}-${bar.event_time}`}>
                <td>{formatTime(bar.event_time)}</td>
                <td>{formatTime(bar.available_time)}</td>
                <td>{bar.open}</td>
                <td>{bar.high}</td>
                <td>{bar.low}</td>
                <td>{bar.close}</td>
                <td>{bar.volume}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {bars.length === 0 ? (
          <p className="data-muted">这个快照没有可预览的数据。</p>
        ) : null}
      </div>
    </div>
  );
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function formatTaskStep(step: string): string {
  const labels: Record<string, string> = {
    queued: "等待 Worker",
    fetch: "读取行情",
    normalize: "标准化",
    validate: "质量校验",
    stage_files: "暂存快照",
    stage_catalog: "登记目录",
    publish_files: "发布文件",
    publish_catalog: "发布目录",
    completed: "导入完成",
  };
  return labels[step] ?? step;
}

function formatIssueSamples(samples: string[]): string {
  if (samples.length === 0) {
    return "无样例";
  }
  const visible = samples.slice(0, 2).join(" / ");
  const remaining = samples.length - 2;
  return remaining > 0 ? `${visible} / 另 ${remaining} 项` : visible;
}
