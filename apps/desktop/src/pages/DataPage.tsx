import type {
  BarPreview,
  DatasetSummary,
  SnapshotSummary,
} from "../api/data-contracts";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";
import { QualityBadge } from "../components/QualityBadge";

interface DataPageProps {
  datasets: DatasetSummary[];
  snapshots: SnapshotSummary[];
  bars: BarPreview[];
  selectedDatasetId: string | null;
  loading: boolean;
  stale: boolean;
  onSelectDataset: (datasetId: string) => void;
}

export function DataPage({
  datasets,
  snapshots,
  bars,
  selectedDatasetId,
  loading,
  stale,
  onSelectDataset,
}: DataPageProps) {
  const realDatasets = datasets.filter(
    (dataset) => dataset.latest_provider_id !== null && dataset.latest_provider_id !== "fixture",
  );
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
          <li data-active="true"><span>01</span>东财只读行情</li>
          <li data-active={realDatasets.length > 0}><span>02</span>真实历史仓库</li>
          <li data-active={latestSnapshot !== undefined}><span>03</span>质量快照</li>
        </ol>
      </section>

      <div className="data-workbench">
        <div className="data-workbench__left">
          <Panel title="本地行情仓库" eyebrow={`REAL CATALOG / ${realDatasets.length}`}>
            {loading ? (
              <p className="data-muted">正在读取本地目录…</p>
            ) : realDatasets.length === 0 ? (
              <EmptyState
                title="尚无真实历史数据"
                description="实时行情当前用于市场观察；正式历史同步接入后，将在这里形成可追溯的本地快照。"
              />
            ) : (
              <div className="dataset-list">
                {realDatasets.map((dataset) => (
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
                      {dataset.frequency} · {dataset.snapshot_count} 个快照 · {sourceLabel(dataset.latest_provider_id)}
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

function formatIssueSamples(samples: string[]): string {
  if (samples.length === 0) {
    return "无样例";
  }
  const visible = samples.slice(0, 2).join(" / ");
  const remaining = samples.length - 2;
  return remaining > 0 ? `${visible} / 另 ${remaining} 项` : visible;
}

function sourceLabel(providerId: string | null): string {
  if (providerId === "eastmoney") {
    return "东方财富";
  }
  if (providerId === "akshare") {
    return "AKShare";
  }
  return providerId ?? "未知来源";
}
