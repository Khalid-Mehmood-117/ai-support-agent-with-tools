import type { ToolStatus, TraceStep as Step } from "@/lib/api";

const STATUS_STYLES: Record<ToolStatus, string> = {
  ok: "bg-green-100 text-green-800",
  error: "bg-red-100 text-red-800",
  denied: "bg-amber-100 text-amber-800",
  rejected: "bg-amber-100 text-amber-800",
  skipped_retry: "bg-neutral-200 text-neutral-700",
};

function Json({ value }: { value: unknown }) {
  return (
    <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-all rounded bg-neutral-50 p-2 font-mono text-[11px] leading-snug text-neutral-700">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function Row({ title, badge, meta, children }: { title: string; badge?: React.ReactNode; meta?: string; children?: React.ReactNode }) {
  return (
    <li className="rounded-md border border-neutral-200 bg-white px-3 py-2 text-xs" data-testid="trace-step">
      <div className="flex items-center gap-2">
        <span className="font-medium text-neutral-900">{title}</span>
        {badge}
        {meta && <span className="ml-auto text-neutral-400">{meta}</span>}
      </div>
      {children}
    </li>
  );
}

export default function TraceStep({ step }: { step: Step }) {
  switch (step.type) {
    case "llm":
      return (
        <Row title="Model" meta={`${step.duration_ms} ms`}>
          <p className="mt-0.5 text-neutral-500">
            {step.tokens.input.toLocaleString()} in, {step.tokens.output.toLocaleString()} out tokens.{" "}
            {step.tool_calls.length > 0 ? `Calls ${step.tool_calls.join(", ")}` : "Writes the reply"}
          </p>
        </Row>
      );

    case "tool":
      return (
        <Row
          title={step.name}
          badge={<span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${STATUS_STYLES[step.status]}`}>{step.status}</span>}
          meta={`${step.duration_ms} ms`}
        >
          <p className="mt-0.5 truncate font-mono text-[11px] text-neutral-500" title={JSON.stringify(step.args)}>
            {JSON.stringify(step.args)}
          </p>
          <details className="mt-1">
            <summary className="cursor-pointer text-neutral-500 hover:text-neutral-800">Result</summary>
            <Json value={step.result} />
          </details>
        </Row>
      );

    case "approval":
      return (
        <Row
          title="Staff approval"
          badge={
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                step.decision === "approve" ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"
              }`}
            >
              {step.decision}
            </span>
          }
        >
          <p className="mt-0.5 text-neutral-500">
            {step.order_id}, ${step.amount.toFixed(2)}
            {step.note ? `. Note: ${step.note}` : ""}
          </p>
        </Row>
      );

    case "step_limit":
      return (
        <Row title="Step limit reached" badge={<span className="rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-medium text-red-800">guard</span>}>
          <p className="mt-0.5 text-neutral-500">
            Limit {step.max_tool_steps} tool calls per turn. Skipped: {step.skipped_calls.join(", ")}
          </p>
        </Row>
      );

    case "claim_guard":
      return (
        <Row title="Action-claim guard" badge={<span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800">corrected</span>}>
          <p className="mt-0.5 text-neutral-500">
            The reply claimed a {step.claims.join(", ")} action that no tool performed, so it was rewritten.
          </p>
          <details className="mt-1">
            <summary className="cursor-pointer text-neutral-500 hover:text-neutral-800">Original reply</summary>
            <p className="mt-1 rounded bg-neutral-50 p-2 text-neutral-600 line-through">{step.original_reply}</p>
          </details>
        </Row>
      );
  }
}
