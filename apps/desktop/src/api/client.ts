import type {
  ActivityItem,
  ApiProblem,
  Health,
  Runtime,
  RuntimeConnection,
  Settings,
  Task,
} from "./contracts";
import type {
  BarPreview,
  DataImportRequest,
  DatasetSummary,
  SnapshotSummary,
} from "./data-contracts";
import type {
  EastmoneyConfigRequest,
  EastmoneyConfigStatus,
  InstrumentSearchResult,
  IntradayBar,
  MarketConnection,
  MarketHome,
} from "./market-contracts";

type Fetch = typeof fetch;

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(problem: ApiProblem, status: number) {
    super(problem.message);
    this.name = "ApiError";
    this.code = problem.code;
    this.status = status;
  }
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly fetchImplementation: Fetch;

  constructor(
    private readonly connection: RuntimeConnection,
    fetchImplementation?: Fetch,
  ) {
    this.baseUrl = connection.base_url.replace(/\/+$/, "");
    this.fetchImplementation = (
      fetchImplementation ?? globalThis.fetch
    ).bind(globalThis);
  }

  getHealth(): Promise<Health> {
    return this.request("/health");
  }

  getRuntime(): Promise<Runtime> {
    return this.request("/v1/runtime");
  }

  listTasks(limit = 100): Promise<Task[]> {
    return this.request(`/v1/tasks?limit=${encodeURIComponent(limit)}`);
  }

  createDemoTask(idempotencyKey: string): Promise<Task> {
    return this.request("/v1/tasks/demo", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
    });
  }

  getTask(taskId: string): Promise<Task> {
    return this.request(`/v1/tasks/${encodeURIComponent(taskId)}`);
  }

  cancelTask(taskId: string): Promise<Task> {
    return this.request(`/v1/tasks/${encodeURIComponent(taskId)}/cancel`, {
      method: "POST",
    });
  }

  listActivity(limit = 100): Promise<ActivityItem[]> {
    return this.request(`/v1/activity?limit=${encodeURIComponent(limit)}`);
  }

  listDatasets(): Promise<DatasetSummary[]> {
    return this.request("/v1/data/datasets");
  }

  listSnapshots(datasetId: string): Promise<SnapshotSummary[]> {
    return this.request(
      `/v1/data/datasets/${encodeURIComponent(datasetId)}/snapshots`,
    );
  }

  getSnapshot(snapshotId: string): Promise<SnapshotSummary> {
    return this.request(`/v1/data/snapshots/${encodeURIComponent(snapshotId)}`);
  }

  listBars(snapshotId: string, limit = 10): Promise<BarPreview[]> {
    return this.request(
      `/v1/data/snapshots/${encodeURIComponent(snapshotId)}/bars?limit=${encodeURIComponent(limit)}`,
    );
  }

  createDataImport(
    request: DataImportRequest,
    idempotencyKey: string,
  ): Promise<Task> {
    return this.request("/v1/data/imports", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(request),
    });
  }

  getMarketConnection(): Promise<MarketConnection> {
    return this.request("/v1/market/connection");
  }

  configureEastmoney(
    config: EastmoneyConfigRequest,
  ): Promise<EastmoneyConfigStatus> {
    return this.request("/v1/market/eastmoney/config", {
      method: "PUT",
      body: JSON.stringify(config),
    });
  }

  startMarketConnection(): Promise<MarketConnection> {
    return this.request("/v1/market/connection/start", { method: "POST" });
  }

  stopMarketConnection(): Promise<MarketConnection> {
    return this.request("/v1/market/connection/stop", { method: "POST" });
  }

  getMarketHome(): Promise<MarketHome> {
    return this.request("/v1/market/home");
  }

  searchMarketInstruments(query: string): Promise<InstrumentSearchResult[]> {
    return this.request(
      `/v1/market/instruments/search?q=${encodeURIComponent(query)}`,
    );
  }

  getMarketIntraday(instrumentId: string, count = 240): Promise<IntradayBar[]> {
    return this.request(
      `/v1/market/instruments/${encodeURIComponent(instrumentId)}/intraday?count=${encodeURIComponent(count)}`,
    );
  }

  addWatchlistInstrument(instrumentId: string): Promise<MarketHome> {
    return this.request("/v1/market/watchlist", {
      method: "POST",
      body: JSON.stringify({ instrument_id: instrumentId }),
    });
  }

  removeWatchlistInstrument(instrumentId: string): Promise<MarketHome> {
    return this.request(
      `/v1/market/watchlist/${encodeURIComponent(instrumentId)}`,
      { method: "DELETE" },
    );
  }

  getSettings(): Promise<Settings> {
    return this.request("/v1/settings");
  }

  updateSettings(settings: Settings): Promise<Settings> {
    return this.request("/v1/settings", {
      method: "PATCH",
      body: JSON.stringify(settings),
    });
  }

  shutdown(): Promise<{ status: "shutting_down" }> {
    return this.request("/internal/shutdown", { method: "POST" });
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.connection.session_token}`,
      ...normalizeHeaders(init.headers),
    };
    if (init.body !== undefined && headers["Content-Type"] === undefined) {
      headers["Content-Type"] = "application/json";
    }

    const response = await this.fetchImplementation(`${this.baseUrl}${path}`, {
      ...init,
      headers,
    });
    const contentType = response.headers.get("Content-Type") ?? "";
    if (!contentType.toLowerCase().includes("application/json")) {
      throw invalidResponse(response.status);
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      throw invalidResponse(response.status);
    }
    if (!response.ok) {
      throw new ApiError(toApiProblem(payload, response.statusText), response.status);
    }
    return payload as T;
  }
}

function invalidResponse(status: number): ApiError {
  return new ApiError(
    {
      code: "invalid_response",
      message: "本地服务返回了无效的 JSON 响应",
    },
    status,
  );
}

function normalizeHeaders(headers: HeadersInit | undefined): Record<string, string> {
  if (headers === undefined) {
    return {};
  }
  if (headers instanceof Headers) {
    return Object.fromEntries(headers.entries());
  }
  if (Array.isArray(headers)) {
    return Object.fromEntries(headers);
  }
  return { ...headers };
}

function toApiProblem(payload: unknown, fallbackMessage: string): ApiProblem {
  if (
    typeof payload === "object" &&
    payload !== null &&
    "code" in payload &&
    "message" in payload &&
    typeof payload.code === "string" &&
    typeof payload.message === "string"
  ) {
    return { code: payload.code, message: payload.message };
  }
  return {
    code: "http_error",
    message: fallbackMessage || "本地服务请求失败",
  };
}
