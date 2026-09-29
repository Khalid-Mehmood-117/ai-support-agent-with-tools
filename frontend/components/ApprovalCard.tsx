"use client";

import { useState } from "react";
import type { ApprovalRequest, Decision } from "@/lib/api";

type Props = {
  request: ApprovalRequest;
  decision: Decision | null;
  busy: boolean;
  onDecide: (decision: Decision, note: string) => void;
};

const money = (amount: number) => `$${amount.toFixed(2)}`;

// Shown in the chat when the agent asks for a refund. In a real store this card would sit in a
// staff tool; here the same page plays both roles so the whole flow can be demoed.
export default function ApprovalCard({ request, decision, busy, onDecide }: Props) {
  const [note, setNote] = useState("");
  const open = decision === null;

  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm" data-testid="approval-card">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-amber-800">Staff approval needed</span>
        {!open && (
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-medium ${
              decision === "approve" ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"
            }`}
          >
            {decision === "approve" ? "Approved" : "Rejected"}
          </span>
        )}
      </div>

      <dl className="grid grid-cols-[96px_minmax(0,1fr)] gap-x-3 gap-y-1.5 break-words text-neutral-800">
        <dt className="text-neutral-500">Refund</dt>
        <dd className="font-semibold">
          {money(request.amount)} for {request.order_id}
        </dd>
        <dt className="text-neutral-500">Customer</dt>
        <dd>
          {request.customer_name} ({request.customer_email})
        </dd>
        <dt className="text-neutral-500">Items</dt>
        <dd>
          {request.items.map((item) => `${item.quantity} x ${item.product} (${money(item.unit_price)})`).join(", ")}
        </dd>
        <dt className="text-neutral-500">Reason</dt>
        <dd>{request.reason}</dd>
        <dt className="text-neutral-500">Policy check</dt>
        <dd className="text-green-800">{request.policy_check}</dd>
      </dl>

      {open && (
        <div className="mt-4 space-y-2">
          <input
            type="text"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Note for the customer (optional)"
            aria-label="Approval note"
            maxLength={500}
            disabled={busy}
            className="w-full rounded-md border border-amber-300 bg-white px-3 py-2 text-sm outline-none focus:border-amber-600"
          />
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => onDecide("approve", note)}
              disabled={busy}
              className="rounded-md bg-green-700 px-4 py-2 text-sm font-medium text-white hover:bg-green-800 disabled:bg-neutral-300"
            >
              Approve refund
            </button>
            <button
              type="button"
              onClick={() => onDecide("reject", note)}
              disabled={busy}
              className="rounded-md border border-neutral-300 bg-white px-4 py-2 text-sm font-medium text-neutral-800 hover:bg-neutral-100 disabled:text-neutral-400"
            >
              Reject
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
