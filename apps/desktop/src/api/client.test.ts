import { ApiClient } from "./client";
import type { RuntimeConnection, Task } from "./contracts";

const connectionFixture: RuntimeConnection = {
  base_url: "http://127.0.0.1:43127",
  protocol_version: 1,
  session_token: "session-token",
};

const taskFixture: Task = {
  task_id: "task-1",
  task_type: "demo.self_check",
  status: "RUNNING",
  progress: 20,
  current_step: "checking",
  correlation_id: "correlation-1",
  worker_pid: 4242,
  created_at: "2026-07-27T00:00:00Z",
  started_at: "2026-07-27T00:00:01Z",
  finished_at: null,
  result: null,
  error_code: null,
  error_message: null,
  revision: 1,
};

it("adds bearer and idempotency headers", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(taskFixture), {
      status: 201,
      headers: { "Content-Type": "application/json" },
    }),
  );
  const client = new ApiClient(connectionFixture, fetchMock);

  await client.createDemoTask("idem-12345678");

  expect(fetchMock).toHaveBeenCalledWith(
    "http://127.0.0.1:43127/v1/tasks/demo",
    expect.objectContaining({
      method: "POST",
      headers: expect.objectContaining({
        Authorization: "Bearer session-token",
        "Idempotency-Key": "idem-12345678",
      }),
    }),
  );
});

it("maps structured API errors", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        code: "runtime_shutting_down",
        message: "正在关闭",
      }),
      {
        status: 503,
        headers: { "Content-Type": "application/json" },
      },
    ),
  );
  const client = new ApiClient(connectionFixture, fetchMock);

  await expect(client.createDemoTask("idem-12345678")).rejects.toMatchObject({
    code: "runtime_shutting_down",
    status: 503,
  });
});

it("rejects malformed JSON responses as a protocol error", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response("not-json", {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  const client = new ApiClient(connectionFixture, fetchMock);

  await expect(client.getRuntime()).rejects.toMatchObject({
    code: "invalid_response",
    status: 200,
  });
});

it("turns browser transport failures into actionable local service errors", async () => {
  const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
  const client = new ApiClient(connectionFixture, fetchMock);

  await expect(
    client.configureEastmoney({
      sdk_python_path: "D:\\AstraQuantData\\Eastmoney\\PythonSDK\\Scripts\\python.exe",
      token: "sensitive-eastmoney-token",
    }),
  ).rejects.toMatchObject({
    code: "local_service_unreachable",
    status: 0,
    message: "本地行情服务暂时不可达，请重启 AstraQuant 后重试",
  });
});

it("calls the default fetch with the browser global binding", async () => {
  const originalFetch = globalThis.fetch;
  const browserFetch = vi.fn(function (this: unknown) {
    if (this !== globalThis) {
      throw new TypeError("Illegal invocation");
    }
    return Promise.resolve(
      new Response(
        JSON.stringify({
          active_workers: 0,
          database_size_bytes: 0,
          shutting_down: false,
        }),
        { headers: { "Content-Type": "application/json" } },
      ),
    );
  });
  globalThis.fetch = browserFetch as typeof fetch;
  try {
    const client = new ApiClient(connectionFixture);
    await expect(client.getRuntime()).resolves.toMatchObject({
      active_workers: 0,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

it("calls the local data catalog and creates an idempotent import", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(
      new Response("[]", {
        headers: { "Content-Type": "application/json" },
      }),
    )
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ...taskFixture,
          task_type: "data.import",
        }),
        {
          status: 201,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );
  const client = new ApiClient(connectionFixture, fetchMock);

  await client.listDatasets();
  await client.createDataImport(
    {
      provider: "fixture",
      instrument_id: "600000.SSE",
      frequency: "1d",
      start: "2026-07-20",
      end: "2026-07-24",
      adjustment: "none",
    },
    "data-import-600000",
  );

  expect(fetchMock).toHaveBeenNthCalledWith(
    1,
    "http://127.0.0.1:43127/v1/data/datasets",
    expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: "Bearer session-token",
      }),
    }),
  );
  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    "http://127.0.0.1:43127/v1/data/imports",
    expect.objectContaining({
      method: "POST",
      body: expect.stringContaining('"instrument_id":"600000.SSE"'),
      headers: expect.objectContaining({
        "Idempotency-Key": "data-import-600000",
      }),
    }),
  );
});

it("calls authenticated realtime market endpoints", async () => {
  const marketHome = {
    connection: { state: "UNAVAILABLE" },
    core_indices: [],
    watchlist: [],
    selected_instrument: null,
    breadth: { status: "UNAVAILABLE", reason: "not available" },
    intelligence: { status: "UNAVAILABLE", reason: "not available" },
    candidates: [],
    as_of: null,
  };
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(JSON.stringify(marketHome), {
        headers: { "Content-Type": "application/json" },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(marketHome), {
        headers: { "Content-Type": "application/json" },
      }),
    );
  const client = new ApiClient(connectionFixture, fetchMock);

  await client.getMarketHome();
  await client.addWatchlistInstrument("600000.SSE");

  expect(fetchMock).toHaveBeenNthCalledWith(
    1,
    "http://127.0.0.1:43127/v1/market/home",
    expect.objectContaining({
      headers: expect.objectContaining({ Authorization: "Bearer session-token" }),
    }),
  );
  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    "http://127.0.0.1:43127/v1/market/watchlist",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ instrument_id: "600000.SSE" }),
    }),
  );
});

it("requests strict market bars for the selected period", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response("[]", {
      headers: { "Content-Type": "application/json" },
    }),
  );
  const client = new ApiClient(connectionFixture, fetchMock);

  await client.getMarketBars("159516.SZSE", "5m", 300);

  expect(fetchMock).toHaveBeenCalledWith(
    "http://127.0.0.1:43127/v1/market/instruments/159516.SZSE/bars?period=5m&count=300",
    expect.objectContaining({
      headers: expect.objectContaining({ Authorization: "Bearer session-token" }),
    }),
  );
});

it("requests the auditable realtime quant decision for an instrument", async () => {
  const quantDecision = {
    features: {
      feature_snapshot_id: "feature-1",
      status: "READY",
      completed_bar_count: 30,
      reason_codes: [],
    },
    signal: {
      signal_id: "signal-1",
      instrument_id: "159516.SZSE",
      event_time: "2026-08-06T10:02:00+08:00",
      decision_time: "2026-08-06T10:02:01+08:00",
      expires_at: "2026-08-06T10:04:01+08:00",
      action: "BUY",
      state: "ACTIVE",
      reference_price: "0.712",
      confidence: "0.68",
      strategy_id: "intraday-momentum-volume",
      strategy_version: "baseline-v1",
      feature_version: "realtime-v1",
      reason_codes: ["MOMENTUM_UP", "VOLUME_EXPANSION"],
    },
    decision_record: {
      decision_id: "decision-1",
      feature_snapshot_id: "feature-1",
      signal_id: "signal-1",
      strategy_id: "intraday-momentum-volume",
      strategy_version: "baseline-v1",
      market_event_time: "2026-08-06T10:02:00+08:00",
      decision_time: "2026-08-06T10:02:01+08:00",
      advisory_checks: ["READ_ONLY_ADVISORY"],
    },
  };
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(quantDecision), {
      headers: { "Content-Type": "application/json" },
    }),
  );
  const client = new ApiClient(connectionFixture, fetchMock);

  await expect(client.getMarketSignal("159516.SZSE")).resolves.toEqual(quantDecision);
  expect(fetchMock).toHaveBeenCalledWith(
    "http://127.0.0.1:43127/v1/market/instruments/159516.SZSE/signal",
    expect.objectContaining({
      headers: expect.objectContaining({ Authorization: "Bearer session-token" }),
    }),
  );
});
