"use client";

import ChatPanel from "@/components/ChatPanel";
import TracePanel from "@/components/TracePanel";
import { useConversation } from "@/lib/useConversation";

export default function Home() {
  const { items, turns, busy, waitingForApproval, send, decide, reset } = useConversation();

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-7xl flex-col px-4 py-6 md:h-screen">
      <header className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900">AI Support Agent with Tools</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Northwind Goods support. The agent calls real tools, refund policy is enforced in code, and staff approve
            every refund.
          </p>
        </div>
        <button
          type="button"
          onClick={reset}
          disabled={busy}
          className="shrink-0 rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-100 disabled:text-neutral-400"
        >
          New conversation
        </button>
      </header>

      {/* min-w-0 lets the columns shrink below their content, so long JSON never widens the page */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 md:grid-cols-[minmax(0,1fr)_440px]">
        <div className="flex min-h-[480px] min-w-0 flex-col">
          <ChatPanel items={items} busy={busy} waitingForApproval={waitingForApproval} onSend={send} onDecide={decide} />
        </div>
        <div className="flex min-h-[480px] min-w-0 flex-col">
          <TracePanel turns={turns} />
        </div>
      </div>
    </main>
  );
}
