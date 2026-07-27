import {
  useMemo,
} from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { getRuntimeConnection } from "../runtime/tauri";
import { ApiClient } from "./client";
import { isTaskActive } from "./contracts";
import type { Settings, Task } from "./contracts";

export const queryKeys = {
  connection: ["runtime-connection"] as const,
  health: ["health"] as const,
  runtime: ["runtime"] as const,
  tasks: ["tasks"] as const,
  task: (taskId: string) => ["tasks", taskId] as const,
  activity: ["activity"] as const,
  settings: ["settings"] as const,
};

export function useRuntimeConnectionQuery() {
  return useQuery({
    queryKey: queryKeys.connection,
    queryFn: getRuntimeConnection,
    staleTime: Number.POSITIVE_INFINITY,
    retry: 1,
  });
}

export function useApiClient(): ApiClient | null {
  const connection = useRuntimeConnectionQuery().data;
  return useMemo(
    () => (connection === undefined ? null : new ApiClient(connection)),
    [connection],
  );
}

export function useHealthQuery() {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: () => requireClient(client).getHealth(),
    enabled: client !== null,
    refetchInterval: 3_000,
  });
}

export function useRuntimeQuery() {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.runtime,
    queryFn: () => requireClient(client).getRuntime(),
    enabled: client !== null,
    refetchInterval: 3_000,
  });
}

export function useTasksQuery() {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.tasks,
    queryFn: () => requireClient(client).listTasks(),
    enabled: client !== null,
    refetchInterval: (query) => {
      const tasks = query.state.data as Task[] | undefined;
      return tasks?.some(isTaskActive) ? 500 : 3_000;
    },
  });
}

export function useTaskQuery(taskId: string | null) {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.task(taskId ?? "none"),
    queryFn: () => requireClient(client).getTask(requireTaskId(taskId)),
    enabled: client !== null && taskId !== null,
    refetchInterval: (query) => {
      const task = query.state.data as Task | undefined;
      return task !== undefined && isTaskActive(task) ? 500 : false;
    },
  });
}

export function useActivityQuery() {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.activity,
    queryFn: () => requireClient(client).listActivity(),
    enabled: client !== null,
    refetchInterval: 2_000,
  });
}

export function useSettingsQuery() {
  const client = useApiClient();
  return useQuery({
    queryKey: queryKeys.settings,
    queryFn: () => requireClient(client).getSettings(),
    enabled: client !== null,
  });
}

export function useCreateDemoTaskMutation() {
  const client = useApiClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (idempotencyKey: string) =>
      requireClient(client).createDemoTask(idempotencyKey),
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

export function useCancelTaskMutation() {
  const client = useApiClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) => requireClient(client).cancelTask(taskId),
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

export function useUpdateSettingsMutation() {
  const client = useApiClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (settings: Settings) =>
      requireClient(client).updateSettings(settings),
    onSuccess: (settings) => {
      queryClient.setQueryData(queryKeys.settings, settings);
    },
  });
}

function requireClient(client: ApiClient | null): ApiClient {
  if (client === null) {
    throw new Error("Local runtime connection is not ready");
  }
  return client;
}

function requireTaskId(taskId: string | null): string {
  if (taskId === null) {
    throw new Error("Task id is required");
  }
  return taskId;
}
