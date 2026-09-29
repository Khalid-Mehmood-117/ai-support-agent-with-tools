import type { ChatItem } from "@/lib/useConversation";

type Props = {
  item: Extract<ChatItem, { kind: "user" | "assistant" | "error" }>;
};

export default function MessageBubble({ item }: Props) {
  if (item.kind === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] whitespace-pre-wrap break-words rounded-lg bg-neutral-900 px-3.5 py-2 text-sm text-white">
          {item.content}
        </div>
      </div>
    );
  }

  if (item.kind === "error") {
    return (
      <div className="flex justify-start">
        <div className="max-w-[80%] rounded-lg border border-red-200 bg-red-50 px-3.5 py-2 text-sm text-red-800" role="alert">
          {item.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div
        className="max-w-[80%] rounded-lg border border-neutral-200 bg-white px-3.5 py-2 text-sm text-neutral-800"
        data-testid="reply"
      >
        {item.corrected && (
          <span className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-amber-700">
            Corrected by action-claim guard
          </span>
        )}
        <p className="whitespace-pre-wrap break-words leading-relaxed">{item.content}</p>
      </div>
    </div>
  );
}
