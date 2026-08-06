import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { ApiClient } from "./client";
import { isTaskActive } from "./contracts";
import type { Settings, Task } from "./contracts";
import type { DataImportRequest } from "./data-contracts";
import type { ConnectionState, MarketPeriod } from "./market-contracts";

export const queryKeys = {
  health: ["health"] as const,
  runtime: ["runtime"] as const,
  tasks: ["tasks"] as const,
  task: (taskId: string) => ["tasks", taskId] as const,
  activity: ["activity"] as const,
  settings: ["settings"] as const,
  datasets: ["data", "datasets"] as const,
  snapshots: (datasetId: string) =>
    ["data", "datasets", datasetId, "snapshots"] as const,
  bars: (snapshotId: string) =>
    ["data", "snapshots", snapshotId, "bars"] as const,
  marketConnection: ["market", "connection"] as const,
  marketHome: ["market", "home"] as const,
  marketIntraday: (instrumentId: string) =>
    ["market", "intraday", instrumentId] as const,
  marketBars: (instrumentId: string, period: MarketPeriod) =>
    ["market", "bars", instrumentId, period] as const,
  marketSearch: (search: string) => ["market", "search", search] as const,
};

function marketRefetchInterval(state: ConnectionState | undefined) {
  if (state === "LIVE" || state === "CONNECTING" || state === "STALE") {
    return 3_000;
  }
  return state === "CLOSED" ? 30_000 : false;
}

function marketBarsRefetchInterval(
  period: MarketPeriod,
  state: ConnectionState | undefined,
) {
  if (state !== "LIVE" && state !== "CONNECTING" && state !== "STALE") {
    return false;
  }
  return period === "intraday" || period === "1m" ? 10_000 : 60_000;
}

export function useMarketConnectionQuery(client: ApiClient) {
  return useQuery({
    queryKey: queryKeys.marketConnection,
    queryFn: () => client.getMarketConnection(),
    refetchInterval: (query) => marketRefetchInterval(query.state.data?.state),
  });
}

export function useMarketHomeQuery(
  client: ApiClient,
  state?: ConnectionState,
) {
  return useQuery({
    queryKey: queryKeys.marketHome,
    queryFn: () => client.getMarketHome(),
    refetchInterval: marketRefetchInterval(state),
  });
}

export function useMarketIntradayQuery(
  client: ApiClient,
  instrumentId: string | null,
  state?: ConnectionState,
) {
  return useQuery({
    queryKey: queryKeys.marketIntraday(instrumentId ?? "none"),
    queryFn: () => client.getMarketIntraday(requireId(instrumentId, "Instrument")),
    enabled:
      instrumentId !== null
      && (state === "LIVE" || state === "STALE" || state === "CLOSED"),
    refetchInterval: marketRefetchInterval(state),
  });
}

export function useMarketBarsQuery(
  client: ApiClient,
  instrumentId: string | null,
  period: MarketPeriod,
  state?: ConnectionState,
) {
  return useQuery({
    queryKey: queryKeys.marketBars(instrumentId ?? "none", period),
    queryFn: () =>
      client.getMarketBars(
        requireId(instrumentId, "Instrument"),
        period,
        period === "intraday" ? 240 : 500,
      ),
    enabled:
      instrumentId !== null
      && (state === "LIVE" || state === "STALE" || state === "CLOSED"),
    staleTime: period === "intraday" || period === "1m" ? 8_000 : 55_000,
    refetchInterval: marketBarsRefetchInterval(period, state),
    retry: 2,
    retryDelay: (attempt) => Math.min(250 * 2 ** attempt, 1_000),
  });
}

export function useMarketSearchQuery(client: ApiClient, search: string) {
  const normalized = search.trim();
  return useQuery({
    queryKey: queryKeys.marketSearch(normalized),
    queryFn: () => client.searchMarketInstruments(normalized),
    enabled: normalized.length >= 2,
    staleTime: 30_000,
  });
}

export function useStartMarketMutation(client: ApiClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => client.startMarketConnection(),
    onSuccess: async (connection) => {
      queryClient.setQueryData(queryKeys.marketConnection, connection);
      await queryClient.invalidateQueries({ queryKey: queryKeys.marketHome });
    },
  });
}

export function useStopMarketMutation(client: ApiClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => client.stopMarketConnection(),
    onSuccess: async (connection) => {
      queryClient.setQueryData(queryKeys.marketConnection, connection);
      await queryClient.invalidateQueries({ queryKey: queryKeys.marketHome });
    },
  });
}

export function useAddWatchlistMutation(client: ApiClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (instrumentId: string) => client.addWatchlistInstrument(instrumentId),
    onSuccess: async (home) => {
      queryClient.setQueryData(queryKeys.marketHome, home);
      await queryClient.invalidateQueries({ queryKey: queryKeys.marketHome });
    },
  });
}

export function useRemoveWatchlistMutation(client: ApiClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (instrumentId: string) => client.removeWatchlistInstrument(instrumentId),
    onSuccess: (home) => queryClient.setQueryData(queryKeys.marketHome, home),
  });
}

export function useHealthQuery(client: ApiClient) {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: () => client.getHealth(),
    refetchInterval: 3_000,
  });
}

export function useRuntimeQuery(client: ApiClient) {
  return useQuery({
    queryKey: queryKeys.runtime,
    queryFn: () => client.getRuntime(),
    refetchInterval: 3_000,
  });
}

export function useTasksQuery(client: ApiClient) {
  return useQuery({
    queryKey: queryKeys.tasks,
    queryFn: () => client.listTasks(),
    refetchInterval: (query) => {
      const tasks = query.state.data as Task[] | undefined;
      return tasks?.some(isTaskActive) ? 500 : 3_000;
    },
  });
}

export function useTaskQuery(client: ApiClient, taskId: string | null) {
  return useQuery({
    queryKey: queryKeys.task(taskId ?? "none"),
    queryFn: () => client.getTask(requireTaskId(taskId)),
    enabled: taskId !== null,
    refetchInterval: (query) => {
      const task = query.state.data as Task | undefined;
      return task !== undefined && isTaskActive(task) ? 500 : false;
    },
  });
}

export function useActivityQuery(client: ApiClient) {
  return useQuery({
    queryKey: queryKeys.activity,
    queryFn: () => client.listActivity(),
    refetchInterval: 2_000,
  });
}

export function useSettingsQuery(client: ApiClient) {
  return useQuery({
    queryKey: queryKeys.settings,
    queryFn: () => client.getSettings(),
  });
}

export function useDatasetsQuery(client: ApiClient) {
  return useQuery({
    queryKey: queryKeys.datasets,
    queryFn: () => client.listDatasets(),
    refetchInterval: 3_000,
  });
}

export function useSnapshotsQuery(
  client: ApiClient,
  datasetId: string | null,
) {
  return useQuery({
    queryKey: queryKeys.snapshots(datasetId ?? "none"),
    queryFn: () => client.listSnapshots(requireId(datasetId, "Dataset")),
    enabled: datasetId !== null,
    refetchInterval: 3_000,
  });
}

export function useBarsQuery(
  client: ApiClient,
  snapshotId: string | null,
) {
  return useQuery({
    queryKey: queryKeys.bars(snapshotId ?? "none"),
    queryFn: () => client.listBars(requireId(snapshotId, "Snapshot")),
    enabled: snapshotId !== null,
  });
}

export function useCreateDataImportMutation(client: ApiClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      request,
      idempotencyKey,
    }: {
      request: DataImportRequest;
      idempotencyKey: string;
    }) => client.createDataImport(request, idempotencyKey),
    onSuccess: async (task) => {
      queryClient.setQueryData(queryKeys.task(task.task_id), task);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.tasks }),
        queryClient.invalidateQueries({ queryKey: queryKeys.runtime }),
        queryClient.invalidateQueries({ queryKey: queryKeys.activity }),
        queryClient.invalidateQueries({ queryKey: queryKeys.datasets }),
      ]);
    },
  });
}

export function useCreateDemoTaskMutation(client: ApiClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (idempotencyKey: string) =>
      client.createDemoTask(idempotencyKey),
    onSuccess: async (task) => {
      queryClient.setQueryData(queryKeys.task(task.task_id), task);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.tasks }),
        queryClient.invalidateQueries({ queryKey: queryKeys.runtime }),
        queryClient.invalidateQueries({ queryKey: queryKeys.activity }),
      ]);
    },
  });
}

export function useCancelTaskMutation(client: ApiClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) => client.cancelTask(taskId),
    onSuccess: async (task) => {
      queryClient.setQueryData(queryKeys.task(task.task_id), task);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.tasks }),
        queryClient.invalidateQueries({ queryKey: queryKeys.runtime }),
        queryClient.invalidateQueries({ queryKey: queryKeys.activity }),
      ]);
    },
  });
}

export function useUpdateSettingsMutation(client: ApiClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (settings: Settings) =>
      client.updateSettings(settings),
    onSuccess: (settings) => {
      queryClient.setQueryData(queryKeys.settings, settings);
    },
  });
}

function requireTaskId(taskId: string | null): string {
  if (taskId === null) {
    throw new Error("Task id is required");
  }
  return taskId;
}

function requireId(value: string | null, label: string): string {
  if (value === null) {
    throw new Error(`${label} id is required`);
  }
  return value;
}
