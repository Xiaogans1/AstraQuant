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
