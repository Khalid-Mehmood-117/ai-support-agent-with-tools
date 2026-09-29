"use client";

import { useRef, useState } from "react";
import {
  ApiError,
  createConversation,
  streamApproval,
  streamMessage,
  type ApprovalRequest,
  type Decision,
  type TraceStep,
  type TurnResponse,
} from "@/lib/api";

export type ChatItem =
  | { id: number; kind: "user"; content: string }
  | { id: number; kind: "assistant"; content: string; corrected: boolean }
  | { id: number; kind: "error"; content: string }
  | { id: number; kind: "approval"; request: ApprovalRequest; decision: Decision | null };

// Omit applied to each member of the union, so every item shape keeps its own fields.
type NewItem = ChatItem extends infer I ? (I extends ChatItem ? Omit<I, "id"> : never) : never;

export type TraceTurn = {
  turn: number;
  steps: TraceStep[];
  duration_ms: number | null;
  state: "running" | "waiting" | "done" | "failed";
};

// All conversation state for the page: chat items on the left, trace turns on the right.
export function useConversation() {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [items, setItems] = useState<ChatItem[]>([]);
  const [turns, setTurns] = useState<TraceTurn[]>([]);
  const [busy, setBusy] = useState(false);
  const nextId = useRef(1);

  const waitingForApproval = items.some((item) => item.kind === "approval" && item.decision === null);

  function push(item: NewItem) {
    setItems((current) => [...current, { ...item, id: nextId.current++ } as ChatItem]);
  }

  function updateLastTurn(change: (turn: TraceTurn) => TraceTurn) {
    setTurns((current) => [...current.slice(0, -1), change(current[current.length - 1])]);
  }

  function appendStep(step: TraceStep) {
    updateLastTurn((turn) => ({ ...turn, steps: [...turn.steps, step] }));
  }

  function finishTurn(result: TurnResponse) {
    const { trace } = result;
    updateLastTurn(() => ({
      turn: trace.turn,
      steps: trace.steps,
      duration_ms: trace.duration_ms,
      state: result.status === "awaiting_approval" ? "waiting" : "done",
    }));
    if (result.status === "awaiting_approval" && result.approval) {
      push({ kind: "approval", request: result.approval, decision: null });
    } else if (result.reply) {
      const corrected = trace.steps.some((step) => step.type === "claim_guard");
      push({ kind: "assistant", content: result.reply, corrected });
    }
  }

  function fail(error: unknown) {
    updateLastTurn((turn) => ({ ...turn, state: "failed" }));
    push({ kind: "error", content: error instanceof ApiError ? error.message : "Something went wrong." });
  }

  async function send(message: string) {
    const text = message.trim();
    if (!text || busy || waitingForApproval) return;

    push({ kind: "user", content: text });
    setTurns((current) => [...current, { turn: current.length + 1, steps: [], duration_ms: null, state: "running" }]);
    setBusy(true);
    try {
      const id = conversationId ?? (await createConversation());
      setConversationId(id);
      finishTurn(await streamMessage(id, text, appendStep));
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  }

  async function decide(decision: Decision, note: string) {
    if (!conversationId || busy) return;

    setItems((current) =>
      current.map((item) => (item.kind === "approval" && item.decision === null ? { ...item, decision } : item)),
    );
    updateLastTurn((turn) => ({ ...turn, state: "running" }));
    setBusy(true);
    try {
      finishTurn(await streamApproval(conversationId, decision, note, appendStep));
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setConversationId(null);
    setItems([]);
    setTurns([]);
  }

  return { items, turns, busy, waitingForApproval, send, decide, reset };
}
