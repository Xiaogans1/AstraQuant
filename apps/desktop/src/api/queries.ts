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
import type {
  CreatePaperAccountRequest,
  OpeningPositionRequest,
  PaperCashBalanceRequest,
  PaperFeeConfig,
  PaperMarketOrderRequest,
  PaperStrategyRunRequest,
} from "./paper-contracts";

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
  marketSignal: (instrumentId: string) =>
    ["market", "signal", instrumentId] as const,
  marketSearch: (search: string) => ["market", "search", search] as const,
  paperAccounts: ["paper", "accounts"] as const,
  paperDefaultAccount: ["paper", "accounts", "default"] as const,
  paperAccount: (accountId: string) => ["paper", "accounts", accountId] as const,
  paperOrders: (accountId: string) => ["paper", "accounts", accountId, "orders"] as const,
  paperFills: (accountId: string) => ["paper", "accounts", accountId, "fills"] as const,
  paperEquity: (accountId: string) => ["paper", "accounts", accountId, "equity"] as const,
  paperStrategyRuns: (accountId: string) =>
    ["paper", "accounts", accountId, "strategy-runs"] as const,
  paperStrategyStatus: ["paper", "strategy", "status"] as const,
  paperFeeConfig: ["paper", "fee-config"] as const,
};

export function useDefaultPaperAccountQuery(client: ApiClient) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: queryKeys.paperDefaultAccount,
    queryFn: async () => {
      const detail = await client.ensureDefaultPaperAccount();
      queryClient.setQueryData(queryKeys.paperAccount(detail.account.account_id), detail);
      return detail;
    },
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

export function usePaperAccountsQuery(client: ApiClient, enabled = true) {
  return useQuery({
    queryKey: queryKeys.paperAccounts,
    queryFn: () => client.listPaperAccounts(),
    enabled,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

export function usePaperAccountQuery(client: ApiClient, accountId: string | null) {
  return useQuery({
    queryKey: queryKeys.paperAccount(accountId ?? "none"),
    queryFn: () => client.getPaperAccount(requireId(accountId, "Paper account")),
    enabled: accountId !== null,
    refetchInterval: 1_000,
  });
}

export function usePaperOrdersQuery(client: ApiClient, accountId: string | null) {
  return useQuery({
    queryKey: queryKeys.paperOrders(accountId ?? "none"),
    queryFn: () => client.listPaperOrders(requireId(accountId, "Paper account")),
    enabled: accountId !== null,
    refetchInterval: 2_000,
  });
}

export function usePaperFillsQuery(client: ApiClient, accountId: string | null) {
  return useQuery({
    queryKey: queryKeys.paperFills(accountId ?? "none"),
    queryFn: () => client.listPaperFills(requireId(accountId, "Paper account")),
    enabled: accountId !== null,
    refetchInterval: 2_000,
  });
}

export function usePaperEquityQuery(client: ApiClient, accountId: string | null) {
  return useQuery({
    queryKey: queryKeys.paperEquity(accountId ?? "none"),
    queryFn: () => client.listPaperEquity(requireId(accountId, "Paper account")),
    enabled: accountId !== null,
    refetchInterval: 1_000,
  });
}

export function useCreatePaperAccountMutation(client: ApiClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: CreatePaperAccountRequest) => client.createPaperAccount(request),
    onSuccess: async (detail) => {
      queryClient.setQueryData(queryKeys.paperAccount(detail.account.account_id), detail);
      await queryClient.invalidateQueries({ queryKey: queryKeys.paperAccounts });
    },
  });
}

export function useAddPaperPositionMutation(client: ApiClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ accountId, request }: { accountId: string; request: OpeningPositionRequest }) =>
      client.addPaperOpeningPosition(accountId, request),
    onSuccess: async (detail) => {
      queryClient.setQueryData(queryKeys.paperAccount(detail.account.account_id), detail);
      await queryClient.invalidateQueries({ queryKey: queryKeys.paperAccounts });
    },
  });
}

export function useUpdatePaperCashMutation(client: ApiClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      accountId,
      request,
    }: {
      accountId: string;
      request: PaperCashBalanceRequest;
    }) => client.updatePaperCash(accountId, request),
    onSuccess: async (detail) => {
      const accountId = detail.account.account_id;
      queryClient.setQueryData(queryKeys.paperAccount(accountId), detail);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.paperAccounts }),
        queryClient.invalidateQueries({ queryKey: queryKeys.paperEquity(accountId) }),
      ]);
    },
  });
}

export function useSubmitPaperOrderMutation(client: ApiClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      accountId,
      request,
      idempotencyKey,
    }: {
      accountId: string;
      request: PaperMarketOrderRequest;
      idempotencyKey: string;
    }) => client.submitPaperOrder(accountId, request, idempotencyKey),
    onSuccess: async (result) => {
      const accountId = result.portfolio.account.account_id;
      queryClient.setQueryData(queryKeys.paperAccount(accountId), result.portfolio);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.paperAccounts }),
        queryClient.invalidateQueries({ queryKey: queryKeys.paperOrders(accountId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.paperFills(accountId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.paperEquity(accountId) }),
      ]);
    },
  });
}

export function useRunPaperStrategyMutation(client: ApiClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      accountId,
      request,
    }: {
      accountId: string;
      request: PaperStrategyRunRequest;
    }) => client.runPaperStrategy(accountId, request),
    onSuccess: async (result, variables) => {
      if (result.outcome !== "EXECUTED") return;
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.paperAccounts }),
        queryClient.invalidateQueries({ queryKey: queryKeys.paperAccount(variables.accountId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.paperOrders(variables.accountId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.paperFills(variables.accountId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.paperEquity(variables.accountId) }),
      ]);
    },
  });
}

export function useRunPaperStrategyScanMutation(client: ApiClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      accountId,
      request,
    }: {
      accountId: string;
      request: PaperStrategyRunRequest;
    }) => client.runPaperStrategyScan(accountId, request),
    onSuccess: async (results, variables) => {
      queryClient.setQueryData(
        queryKeys.paperStrategyRuns(variables.accountId),
        results,
      );
      if (!results.some((result) => result.outcome === "EXECUTED")) return;
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.paperAccounts }),
        queryClient.invalidateQueries({ queryKey: queryKeys.paperAccount(variables.accountId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.paperOrders(variables.accountId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.paperFills(variables.accountId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.paperEquity(variables.accountId) }),
      ]);
    },
  });
}

export function usePaperStrategyRunsQuery(client: ApiClient, accountId: string | null) {
  return useQuery({
    queryKey: queryKeys.paperStrategyRuns(accountId ?? "none"),
    queryFn: () => client.listPaperStrategyRuns(requireId(accountId, "Paper account")),
    enabled: accountId !== null,
    staleTime: 15_000,
    refetchInterval: 15_000,
  });
}

export function usePaperStrategyStatusQuery(client: ApiClient) {
  return useQuery({
    queryKey: queryKeys.paperStrategyStatus,
    queryFn: () => client.getPaperStrategyStatus(),
    staleTime: 15_000,
    refetchInterval: 15_000,
  });
}

export function usePaperFeeConfigQuery(client: ApiClient) {
  return useQuery({
    queryKey: queryKeys.paperFeeConfig,
    queryFn: () => client.getPaperFeeConfig(),
    staleTime: 30_000,
  });
}

export function useUpdatePaperFeeConfigMutation(client: ApiClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (config: PaperFeeConfig) => client.updatePaperFeeConfig(config),
    onSuccess: (config) => {
      queryClient.setQueryData(queryKeys.paperFeeConfig, config);
    },
  });
}

function marketRefetchInterval(state: ConnectionState | undefined) {
  if (state === "LIVE" || state === "CONNECTING" || state === "STALE") {
    return 3_000;
  }
  return state === "CLOSED" ? 30_000 : false;
}

function marketQuoteRefetchInterval(state: ConnectionState | undefined) {
  if (state === "LIVE" || state === "CONNECTING" || state === "STALE") {
    return 1_000;
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
    refetchInterval: marketQuoteRefetchInterval(state),
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

export function useMarketSignalQuery(
  client: ApiClient,
  instrumentId: string | null,
  state?: ConnectionState,
) {
  const usable = state === "LIVE" || state === "STALE" || state === "CLOSED";
  return useQuery({
    queryKey: queryKeys.marketSignal(instrumentId ?? "none"),
    queryFn: () => client.getMarketSignal(requireId(instrumentId, "Instrument")),
    enabled: instrumentId !== null && usable,
    staleTime: state === "LIVE" || state === "STALE" ? 8_000 : 55_000,
    refetchInterval:
      state === "LIVE" || state === "STALE"
        ? 10_000
        : state === "CLOSED"
          ? 60_000
          : false,
    retry: 1,
    retryDelay: 250,
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
