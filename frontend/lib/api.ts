// Typed client for the support agent backend.

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ToolStatus = "ok" | "error" | "denied" | "rejected" | "skipped_retry";

export type TraceStep =
  | { type: "llm"; duration_ms: number; tokens: { input: number; output: number }; tool_calls: string[] }
  | {
      type: "tool";
      name: string;
      args: Record<string, unknown>;
      result: Record<string, unknown>;
      status: ToolStatus;
      duration_ms: number;
    }
  | { type: "approval"; order_id: string; amount: number; decision: "approve" | "reject"; note: string }
  | { type: "step_limit"; max_tool_steps: number; skipped_calls: string[] }
  | { type: "claim_guard"; claims: string[]; original_reply: string; corrected_reply: string };

export type Trace = {
  turn: number;
  duration_ms: number;
  steps: TraceStep[];
};

export type ApprovalRequest = {
  tool_call_id: string;
  order_id: string;
  customer_name: string;
  customer_email: string;
  items: { product: string; quantity: number; unit_price: number }[];
  amount: number;
  reason: string;
  policy_check: string;
};

export type TurnResponse = {
  reply: string | null;
  status: "done" | "awaiting_approval";
  approval: ApprovalRequest | null;
  trace: Trace;
};

export type Decision = "approve" | "reject";

export class ApiError extends Error {}

export async function createConversation(): Promise<string> {
  const response = await fetch(`${API_URL}/conversations`, { method: "POST" });
  if (!response.ok) throw new ApiError(await errorDetail(response));
  const body = (await response.json()) as { conversation_id: string };
  return body.conversation_id;
}

export function streamMessage(
  conversationId: string,
  message: string,
  onStep: (step: TraceStep) => void,
): Promise<TurnResponse> {
  return postStream(`/conversations/${conversationId}/messages/stream`, { message }, onStep);
}

export function streamApproval(
  conversationId: string,
  decision: Decision,
  note: string,
  onStep: (step: TraceStep) => void,
): Promise<TurnResponse> {
  return postStream(`/conversations/${conversationId}/approval/stream`, { decision, note }, onStep);
}

// The backend streams Server-Sent Events from a POST request, so EventSource (GET only) cannot be
// used. Events are read from the response body: "step" per trace step, then one "turn" or "error".
async function postStream(
  path: string,
  body: object,
  onStep: (step: TraceStep) => void,
): Promise<TurnResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Could not reach the support backend. Is it running?");
  }
  if (!response.ok || !response.body) throw new ApiError(await errorDetail(response));

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const { event, data } = parseEvent(block);
      if (event === "step") onStep(data as TraceStep);
      if (event === "turn") return data as TurnResponse;
      if (event === "error") throw new ApiError((data as { detail: string }).detail);
    }
  }
  throw new ApiError("The response ended before the turn finished.");
}

function parseEvent(block: string): { event: string; data: unknown } {
  let event = "message";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice(7);
    if (line.startsWith("data: ")) data += line.slice(6);
  }
  return { event, data: data ? JSON.parse(data) : null };
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // Not JSON; fall through to the generic message.
  }
  return `Request failed (${response.status}).`;
}
