import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import {
  createThread,
  listMessages,
  listThreads,
  postMessage,
} from "@/api/client";
import type { ChatMessageOut } from "@/api/types";

export function ChatPage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [role, setRole] = useState<"user" | "assistant" | "system">("user");
  const bottomRef = useRef<HTMLDivElement>(null);

  const threadsQuery = useQuery({
    queryKey: ["chat-threads"],
    queryFn: listThreads,
  });

  useEffect(() => {
    if (!selectedId && threadsQuery.data?.length) {
      setSelectedId(threadsQuery.data[0].id);
    }
  }, [selectedId, threadsQuery.data]);

  const messagesQuery = useQuery({
    queryKey: ["chat-messages", selectedId],
    queryFn: () => listMessages(selectedId!),
    enabled: !!selectedId,
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messagesQuery.data]);

  const newThreadMut = useMutation({
    mutationFn: (title: string) => createThread(title),
    onSuccess: (th) => {
      setSelectedId(th.id);
      void queryClient.invalidateQueries({ queryKey: ["chat-threads"] });
    },
  });

  const sendMut = useMutation({
    mutationFn: () =>
      postMessage(selectedId!, { role, content: draft.trim() }),
    onSuccess: () => {
      setDraft("");
      void queryClient.invalidateQueries({
        queryKey: ["chat-messages", selectedId],
      });
    },
  });

  function bubbleClass(m: ChatMessageOut) {
    if (m.role === "user")
      return "ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-accent/15 px-4 py-2 text-sm text-ink";
    if (m.role === "assistant")
      return "mr-auto max-w-[85%] rounded-2xl rounded-bl-md bg-black/[0.06] px-4 py-2 text-sm text-ink";
    return "mx-auto max-w-[90%] rounded-lg bg-amber-50 px-3 py-2 text-center text-xs text-amber-900";
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-3rem)] max-w-6xl gap-4">
      <aside className="flex w-56 shrink-0 flex-col rounded-2xl border border-black/5 bg-surface-card p-3 shadow-sm">
        <button
          type="button"
          onClick={() => {
            const t = window.prompt("Thread title", "Chat");
            if (t) newThreadMut.mutate(t);
          }}
          className="rounded-lg bg-ink py-2 text-sm font-medium text-white hover:bg-ink/90"
        >
          New thread
        </button>
        <div className="mt-3 flex-1 overflow-y-auto">
          {threadsQuery.data?.map((th) => (
            <button
              key={th.id}
              type="button"
              onClick={() => setSelectedId(th.id)}
              className={`mb-1 w-full rounded-lg px-2 py-2 text-left text-sm ${
                selectedId === th.id
                  ? "bg-black/10 font-medium text-ink"
                  : "text-ink-muted hover:bg-black/5"
              }`}
            >
              <div className="truncate">{th.title}</div>
              <div className="text-xs text-ink-muted/80">
                {new Date(th.created_at).toLocaleDateString()}
              </div>
            </button>
          ))}
          {threadsQuery.data?.length === 0 && (
            <p className="text-xs text-ink-muted">No threads yet.</p>
          )}
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col rounded-2xl border border-black/5 bg-surface-card shadow-sm">
        <header className="border-b border-black/5 px-4 py-3">
          <h1 className="text-lg font-medium text-ink">Chat</h1>
          <p className="text-xs text-ink-muted">
            Stored threads and messages (API CRUD). Add assistant replies
            manually if needed.
          </p>
        </header>

        <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
          {!selectedId && (
            <p className="text-sm text-ink-muted">
              Select or create a thread.
            </p>
          )}
          {selectedId && messagesQuery.isLoading && (
            <p className="text-sm text-ink-muted">Loading messages…</p>
          )}
          {messagesQuery.data?.map((m) => (
            <div key={m.id} className="flex flex-col gap-1">
              <div className={bubbleClass(m)}>
                <div className="mb-1 text-[10px] uppercase tracking-wide text-ink-muted">
                  {m.role}
                </div>
                <div className="whitespace-pre-wrap">{m.content}</div>
              </div>
              <div className="px-1 text-[10px] text-ink-muted/70">
                {new Date(m.created_at).toLocaleString()}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        <footer className="border-t border-black/5 p-4">
          <div className="mb-2 flex flex-wrap gap-2 text-xs">
            <span className="text-ink-muted">Role:</span>
            {(["user", "assistant", "system"] as const).map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setRole(r)}
                className={`rounded-full px-2 py-0.5 ${
                  role === r
                    ? "bg-ink text-white"
                    : "bg-black/5 text-ink-muted hover:bg-black/10"
                }`}
              >
                {r}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Message…"
              rows={3}
              disabled={!selectedId}
              className="min-w-0 flex-1 resize-none rounded-xl border border-black/10 bg-white px-3 py-2 text-sm outline-none ring-accent/30 focus:ring-2 disabled:opacity-50"
            />
            <button
              type="button"
              disabled={
                !selectedId ||
                sendMut.isPending ||
                !draft.trim()
              }
              onClick={() => sendMut.mutate()}
              className="self-end rounded-xl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
            >
              Send
            </button>
          </div>
          {sendMut.error && (
            <p className="mt-2 text-sm text-red-700">
              {sendMut.error instanceof Error
                ? sendMut.error.message
                : "Send failed"}
            </p>
          )}
        </footer>
      </section>
    </div>
  );
}
