import {
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";

import { ApiClient } from "./api/client";
import type {
  RuntimeConnection,
  Settings,
} from "./api/contracts";
import {
  useActivityQuery,
  useBarsQuery,
  useCancelTaskMutation,
  useDatasetsQuery,
  useHealthQuery,
  useRuntimeQuery,
  useSettingsQuery,
  useSnapshotsQuery,
  useTasksQuery,
  useUpdateSettingsMutation,
} from "./api/queries";
import { EmptyState } from "./components/EmptyState";
import { MarketConnectionPanel } from "./components/MarketConnectionPanel";
import { Panel } from "./components/Panel";
import { ServiceError } from "./components/ServiceError";
import { Sidebar } from "./components/Sidebar";
import type { WorkspaceView } from "./components/Sidebar";
import { StatusRail } from "./components/StatusRail";
import { ActivityPage } from "./pages/ActivityPage";
import { DataPage } from "./pages/DataPage";
import { OverviewPage } from "./pages/OverviewPage";
import { PaperPage } from "./pages/PaperPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TasksPage } from "./pages/TasksPage";
import {
  getRuntimeConnection,
  openLogDirectory,
} from "./runtime/tauri";
import {
  applyBackgroundEffect,
  applyReducedMotion,
  applyTheme,
} from "./theme/theme";

const defaultSettings: Settings = {
  theme: "astra-minimal",
  reduced_motion: false,
  sidebar_collapsed: false,
  background_effect: "nebula",
};

const viewCopy: Record<
  WorkspaceView,
  { index: string; title: string; summary: string }
> = {
  overview: {
    index: "MARKET / 01",
    title: "市场首页",
    summary: "实时观察中国市场，并将量化候选、AI 情报与虚拟盘叠加在行情之上。",
  },
  data: {
    index: "CONNECTIONS / 02",
    title: "数据与连接",
    summary: "接入真实只读行情，管理本地历史仓库，并将通过质量校验的快照送入后续 AI 特征流程。",
  },
  paper: {
    index: "PORTFOLIO / PAPER",
    title: "模拟账户",
    summary: "用真实行情驱动本地虚拟成交，观察持仓、资金与策略收益；当前不会向券商发送任何委托。",
  },
  tasks: {
    index: "WORKSPACE / 03",
    title: "任务中心",
    summary: "查看 Worker 长任务的状态、精确进度、执行结果与重启恢复记录。",
  },
  activity: {
    index: "WORKSPACE / 04",
    title: "本地活动",
    summary: "以关联 ID 串联服务与任务事件，不暴露原始环境信息或凭据。",
  },
  settings: {
    index: "WORKSPACE / 05",
    title: "设置",
    summary: "主题、动态效果与侧栏偏好只保存在本机状态库中。",
  },
};

type StartupState =
  | { status: "loading" }
  | { status: "online"; connection: RuntimeConnection }
  | { status: "error"; message: string };

export function App() {
  const [retryRevision, setRetryRevision] = useState(0);
  const [startup, setStartup] = useState<StartupState>({ status: "loading" });

  useEffect(() => {
    let active = true;
    setStartup({ status: "loading" });
    getRuntimeConnection()
      .then((connection) => {
        if (active) {
          setStartup({ status: "online", connection });
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setStartup({
            status: "error",
            message: readableError(error, "无法取得本地服务连接信息"),
          });
        }
      });
    return () => {
      active = false;
    };
  }, [retryRevision]);

  if (startup.status === "loading") {
    return <StartupScreen />;
  }
  if (startup.status === "error") {
    return (
      <ServiceError
        message={startup.message}
        onRetry={() => setRetryRevision((value) => value + 1)}
        onOpenLogs={() => {
          void openLogDirectory();
        }}
      />
    );
  }
  return <ConnectedApp connection={startup.connection} />;
}

function ConnectedApp({ connection }: { connection: RuntimeConnection }) {
  const client = useMemo(() => new ApiClient(connection), [connection]);
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: 1,
            refetchOnWindowFocus: true,
          },
          mutations: { retry: 0 },
        },
      }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      <Workspace client={client} protocolVersion={connection.protocol_version} />
    </QueryClientProvider>
  );
}

function Workspace({
  client,
  protocolVersion,
}: {
  client: ApiClient;
  protocolVersion: number;
}) {
  const [currentView, setCurrentView] = useState<WorkspaceView>("overview");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(
    null,
  );
  const healthQuery = useHealthQuery(client);
  const runtimeQuery = useRuntimeQuery(client);
  const tasksQuery = useTasksQuery(client);
  const activityQuery = useActivityQuery(client);
  const settingsQuery = useSettingsQuery(client);
  const datasetsQuery = useDatasetsQuery(client);
  const realDatasets = useMemo(
    () =>
      (datasetsQuery.data ?? []).filter(
        (dataset) =>
          dataset.latest_provider_id !== null &&
          dataset.latest_provider_id !== "fixture",
      ),
    [datasetsQuery.data],
  );
  const effectiveDatasetId =
    (selectedDatasetId !== null &&
    realDatasets.some((dataset) => dataset.dataset_id === selectedDatasetId)
      ? selectedDatasetId
      : realDatasets[0]?.dataset_id) ?? null;
  const snapshotsQuery = useSnapshotsQuery(client, effectiveDatasetId);
  const latestSnapshotId =
    snapshotsQuery.data?.[0]?.snapshot_id ?? null;
  const barsQuery = useBarsQuery(client, latestSnapshotId);
  const cancelTask = useCancelTaskMutation(client);
  const updateSettings = useUpdateSettingsMutation(client);

  useEffect(() => {
    const settings = settingsQuery.data;
    if (settings === undefined) {
      return;
    }
    applyTheme(settings.theme);
    applyReducedMotion(settings.reduced_motion);
    applyBackgroundEffect(settings.background_effect);
    setSidebarCollapsed(settings.sidebar_collapsed);
  }, [settingsQuery.data]);

  const copy = viewCopy[currentView];
  const serviceError =
    healthQuery.error ?? runtimeQuery.error ?? tasksQuery.error ?? activityQuery.error;
  const hasCachedWorkspace =
    runtimeQuery.data !== undefined && tasksQuery.data !== undefined;

  if (serviceError !== null && !hasCachedWorkspace) {
    return (
      <ServiceError
        message={readableError(serviceError, "无法读取本地服务状态")}
        onRetry={() => {
          void Promise.all([
            healthQuery.refetch(),
            runtimeQuery.refetch(),
            tasksQuery.refetch(),
            activityQuery.refetch(),
          ]);
        }}
        onOpenLogs={() => {
          void openLogDirectory();
        }}
      />
    );
  }

  const runtime = runtimeQuery.data;
  const tasks = tasksQuery.data ?? [];
  const activity = activityQuery.data ?? [];
  const settings = settingsQuery.data ?? defaultSettings;
  const isStale =
    healthQuery.isError ||
    runtimeQuery.isError ||
    tasksQuery.isError ||
    activityQuery.isError;

  return (
    <div className="app">
      <StatusRail
        status={isStale ? "offline" : "online"}
        protocolVersion={protocolVersion}
      />
      <div className="workspace" data-sidebar-collapsed={sidebarCollapsed}>
        <Sidebar
          currentView={currentView}
          collapsed={sidebarCollapsed}
          onNavigate={setCurrentView}
          onToggle={() => setSidebarCollapsed((value) => !value)}
        />
        <main className="workspace-main">
          {currentView === "overview" ? null : (
            <header className="page-heading">
              <div>
                <p className="page-heading__index">{copy.index}</p>
                <h1>{copy.title}</h1>
              </div>
              <p className="page-heading__summary">{copy.summary}</p>
            </header>
          )}
          <div className="workspace-content" data-view={currentView}>
            {currentView === "overview" ? (
              <OverviewPage client={client} />
            ) : runtime === undefined ? (
              <Panel>
                <EmptyState
                  title="正在同步本地状态"
                  description="桌面已连接控制服务，正在读取任务与状态库摘要。"
                />
              </Panel>
            ) : (
              renderView({
                client,
                currentView,
                runtime,
                tasks,
                activity,
                settings,
                isStale,
                cancelTask,
                updateSettings,
                datasets: realDatasets,
                snapshots: snapshotsQuery.data ?? [],
                bars: barsQuery.data ?? [],
                selectedDatasetId: effectiveDatasetId,
                dataLoading: datasetsQuery.isLoading,
                dataStale:
                  datasetsQuery.isError ||
                  snapshotsQuery.isError ||
                  barsQuery.isError,
                onSelectDataset: setSelectedDatasetId,
              })
            )}
          </div>
        </main>
      </div>
    </div>
  );
}

function renderView({
  client,
  currentView,
  runtime,
  tasks,
  activity,
  settings,
  isStale,
  cancelTask,
  updateSettings,
  datasets,
  snapshots,
  bars,
  selectedDatasetId,
  dataLoading,
  dataStale,
  onSelectDataset,
}: {
  client: ApiClient;
  currentView: WorkspaceView;
  runtime: NonNullable<ReturnType<typeof useRuntimeQuery>["data"]>;
  tasks: NonNullable<ReturnType<typeof useTasksQuery>["data"]>;
  activity: NonNullable<ReturnType<typeof useActivityQuery>["data"]>;
  settings: Settings;
  isStale: boolean;
  cancelTask: ReturnType<typeof useCancelTaskMutation>;
  updateSettings: ReturnType<typeof useUpdateSettingsMutation>;
  datasets: NonNullable<ReturnType<typeof useDatasetsQuery>["data"]>;
  snapshots: NonNullable<ReturnType<typeof useSnapshotsQuery>["data"]>;
  bars: NonNullable<ReturnType<typeof useBarsQuery>["data"]>;
  selectedDatasetId: string | null;
  dataLoading: boolean;
  dataStale: boolean;
  onSelectDataset: (datasetId: string) => void;
}) {
  if (currentView === "overview") {
    return <OverviewPage client={client} />;
  }
  if (currentView === "data") {
    return (
      <>
        <MarketConnectionPanel client={client} />
        <DataPage
          datasets={datasets}
          snapshots={snapshots}
          bars={bars}
          selectedDatasetId={selectedDatasetId}
          loading={dataLoading}
          stale={dataStale}
          onSelectDataset={onSelectDataset}
        />
      </>
    );
  }
  if (currentView === "paper") {
    return <PaperPage client={client} />;
  }
  if (currentView === "tasks") {
    return (
      <TasksPage
        tasks={tasks}
        isStale={isStale}
        cancelingTaskId={
          cancelTask.isPending ? (cancelTask.variables ?? null) : null
        }
        onCancelTask={(taskId) => cancelTask.mutate(taskId)}
      />
    );
  }
  if (currentView === "activity") {
    return (
      <ActivityPage
        activity={activity}
        onOpenLogs={() => {
          void openLogDirectory();
        }}
      />
    );
  }
  return (
    <SettingsPage
      settings={settings}
      saving={updateSettings.isPending}
      onSave={(nextSettings) => updateSettings.mutateAsync(nextSettings)}
    />
  );
}

function StartupScreen() {
  return (
    <main className="startup-screen">
      <div className="brand-mark" aria-hidden="true">
        <span className="brand-mark__core" />
      </div>
      <p className="panel__eyebrow">ASTRAQUANT / LOCAL</p>
      <h1>正在启动本地工作区</h1>
      <p>正在验证桌面与控制服务的私有会话。</p>
    </main>
  );
}

function readableError(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.length > 0) {
    return error.message;
  }
  if (typeof error === "string" && error.length > 0) {
    return error;
  }
  return fallback;
}
