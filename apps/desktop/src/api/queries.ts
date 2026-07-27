import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { ApiClient } from "./client";
import { isTaskActive } from "./contracts";
import type { Settings, Task } from "./contracts";

export const queryKeys = {
  health: ["health"] as const,
  runtime: ["runtime"] as const,
  tasks: ["tasks"] as const,
  task: (taskId: string) => ["tasks", taskId] as const,
  activity: ["activity"] as const,
  settings: ["settings"] as const,
};

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
