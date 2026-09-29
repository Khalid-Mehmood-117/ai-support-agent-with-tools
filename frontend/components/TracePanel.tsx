import TraceStep from "@/components/TraceStep";
import type { TraceTurn } from "@/lib/useConversation";

const STATE_LABELS: Record<TraceTurn["state"], string> = {
  running: "running",
  waiting: "waiting for staff",
  done: "done",
  failed: "failed",
};

export default function TracePanel({ turns }: { turns: TraceTurn[] }) {
  return (
    <section className="flex min-h-0 flex-1 flex-col rounded-md border border-neutral-200 bg-neutral-50" data-testid="trace-panel">
      <div className="border-b border-neutral-200 px-4 py-3">
        <h2 className="text-sm font-medium text-neutral-800">Tool trace</h2>
        <p className="text-xs text-neutral-500">Every model call and tool call, live, with arguments, results and timings.</p>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {turns.length === 0 && <p className="text-xs text-neutral-500">Nothing yet. Send a message to see the agent work.</p>}

        {turns.map((turn, index) => (
          <div key={index}>
            <div className="mb-2 flex items-center gap-2 text-xs">
              <span className="font-semibold text-neutral-700">Turn {turn.turn}</span>
              <span className={turn.state === "failed" ? "text-red-700" : "text-neutral-500"}>{STATE_LABELS[turn.state]}</span>
              {turn.duration_ms !== null && <span className="ml-auto text-neutral-400">{turn.duration_ms} ms working time</span>}
            </div>
            <ol className="space-y-1.5">
              {turn.steps.map((step, stepIndex) => (
                <TraceStep key={stepIndex} step={step} />
              ))}
              {turn.state === "running" && (
                <li className="animate-pulse rounded-md border border-dashed border-neutral-300 px-3 py-2 text-xs text-neutral-400">
                  Working...
                </li>
              )}
            </ol>
          </div>
        ))}
      </div>
    </section>
  );
}
