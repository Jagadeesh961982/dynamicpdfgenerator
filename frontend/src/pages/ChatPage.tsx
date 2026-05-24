import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import {
  Plus, Send, MessageSquare, Trash2, Bot, User,
  Loader2, Sparkles, X,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  chatWithAI, createThread, deleteThread, listMessages, listThreads,
} from "@/api/client";
import type { ChatMessageOut, ChatThreadOut } from "@/api/types";

function fmtTime(iso: string) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function MessageBubble({ msg }: { msg: ChatMessageOut }) {
  const isUser = msg.role === "user";
  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : ""} animate-slide-up`}>
      <div className={`w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 mt-1
        ${isUser ? "bg-gradient-to-br from-violet-500 to-indigo-600" : "bg-bg-elevated border border-border"}`}>
        {isUser ? <User className="w-3.5 h-3.5 text-white" /> : <Bot className="w-3.5 h-3.5 text-txt-muted" />}
      </div>
      <div className={`max-w-[75%] ${isUser ? "items-end" : "items-start"} flex flex-col gap-1`}>
        <div className={`px-4 py-2.5 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap
          ${isUser
            ? "bg-brand text-white rounded-tr-sm"
            : "bg-bg-elevated border border-border text-txt-primary rounded-tl-sm"
          }`}>
          {msg.content}
        </div>
        <span className="text-[10px] text-txt-subtle px-1">{fmtTime(msg.created_at)}</span>
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex gap-3 animate-slide-up">
      <div className="w-7 h-7 rounded-full bg-bg-elevated border border-border flex items-center justify-center flex-shrink-0 mt-1">
        <Bot className="w-3.5 h-3.5 text-txt-muted" />
      </div>
      <div className="bg-bg-elevated border border-border px-4 py-3 rounded-2xl rounded-tl-sm">
        <div className="flex gap-1 items-center h-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="w-1.5 h-1.5 rounded-full bg-txt-subtle animate-bounce"
              style={{ animationDelay: `${i * 0.15}s` }} />
          ))}
        </div>
      </div>
    </div>
  );
}

export function ChatPage() {
  const qc = useQueryClient();
  const [activeThread, setActiveThread] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [showNewThread, setShowNewThread] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const { data: threads = [] } = useQuery({
    queryKey: ["threads"],
    queryFn: listThreads,
  });

  const { data: messages = [], isLoading: msgsLoading } = useQuery({
    queryKey: ["messages", activeThread],
    queryFn: () => listMessages(activeThread!),
    enabled: !!activeThread,
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  const createMut = useMutation({
    mutationFn: (title: string) => createThread(title || "New Conversation"),
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: ["threads"] });
      setActiveThread(t.id);
      setShowNewThread(false);
      setNewTitle("");
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Failed to create thread"),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteThread(id),
    onSuccess: (_, id) => {
      qc.invalidateQueries({ queryKey: ["threads"] });
      if (activeThread === id) setActiveThread(null);
      toast.success("Thread deleted");
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Delete failed"),
  });

  const sendMut = useMutation({
    mutationFn: async (msg: string) => {
      if (!activeThread) throw new Error("No thread selected");
      setIsTyping(true);
      try {
        return await chatWithAI(activeThread, { message: msg });
      } finally {
        setIsTyping(false);
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["messages", activeThread] });
    },
    onError: (e) => {
      setIsTyping(false);
      toast.error(e instanceof Error ? e.message : "Failed to send message");
    },
  });

  function handleSend() {
    const msg = input.trim();
    if (!msg || sendMut.isPending) return;
    setInput("");
    // Optimistic: add user message to cache
    qc.setQueryData<ChatMessageOut[]>(["messages", activeThread], (prev) => [
      ...(prev ?? []),
      {
        id: crypto.randomUUID(),
        thread_id: activeThread!,
        role: "user",
        content: msg,
        created_at: new Date().toISOString(),
      },
    ]);
    sendMut.mutate(msg);
    setTimeout(() => inputRef.current?.focus(), 50);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const activeThreadData = threads.find((t) => t.id === activeThread);

  return (
    <div className="flex h-full bg-bg-page">
      {/* Thread list */}
      <aside className="w-64 flex-shrink-0 flex flex-col border-r border-border bg-bg-surface">
        <div className="flex items-center justify-between px-4 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-txt-primary">Conversations</h2>
          <button
            onClick={() => setShowNewThread(true)}
            className="w-7 h-7 rounded-lg bg-brand-soft hover:bg-brand text-brand-light hover:text-white flex items-center justify-center transition-colors"
            title="New conversation"
          >
            <Plus className="w-4 h-4" />
          </button>
        </div>

        {showNewThread && (
          <div className="p-3 border-b border-border bg-bg-elevated/40 animate-slide-up">
            <input
              autoFocus value={newTitle} onChange={(e) => setNewTitle(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") createMut.mutate(newTitle); if (e.key === "Escape") setShowNewThread(false); }}
              className="input text-xs" placeholder="Thread title…"
            />
            <div className="flex gap-2 mt-2">
              <button onClick={() => createMut.mutate(newTitle)} disabled={createMut.isPending} className="btn-primary flex-1 justify-center py-1.5 text-xs">
                {createMut.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : "Create"}
              </button>
              <button onClick={() => setShowNewThread(false)} className="btn-ghost py-1.5 px-2">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto py-2">
          {threads.length === 0 ? (
            <div className="text-center py-10 px-4">
              <MessageSquare className="w-8 h-8 text-txt-subtle mx-auto mb-2" />
              <p className="text-xs text-txt-subtle">No conversations yet</p>
            </div>
          ) : (
            threads.map((t: ChatThreadOut) => (
              <div key={t.id} className="group relative">
                <button
                  onClick={() => setActiveThread(t.id)}
                  className={`w-full text-left px-4 py-2.5 text-sm transition-colors ${activeThread === t.id ? "bg-brand-soft text-brand-light" : "text-txt-muted hover:text-txt-primary hover:bg-bg-hover"}`}
                >
                  <div className="flex items-start gap-2">
                    <MessageSquare className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                    <p className="truncate leading-snug pr-5">{t.title}</p>
                  </div>
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); if (confirm("Delete this conversation?")) deleteMut.mutate(t.id); }}
                  className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 p-1 text-txt-subtle hover:text-err transition-all"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            ))
          )}
        </div>
      </aside>

      {/* Chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {activeThread ? (
          <>
            {/* Header */}
            <div className="flex items-center gap-3 px-5 py-3.5 border-b border-border bg-bg-surface">
              <div className="w-7 h-7 rounded-full bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center">
                <Sparkles className="w-3.5 h-3.5 text-white" />
              </div>
              <div>
                <p className="text-sm font-medium text-txt-primary">{activeThreadData?.title ?? "Conversation"}</p>
                <p className="text-xs text-txt-subtle">{messages.length} messages</p>
              </div>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              {msgsLoading ? (
                <div className="flex justify-center pt-10">
                  <Loader2 className="w-5 h-5 animate-spin text-brand" />
                </div>
              ) : messages.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-center py-20">
                  <div className="w-14 h-14 rounded-2xl bg-brand-soft flex items-center justify-center mb-4">
                    <Bot className="w-7 h-7 text-brand-light" />
                  </div>
                  <p className="text-txt-primary font-medium">Start the conversation</p>
                  <p className="text-txt-subtle text-sm mt-1 max-w-xs">Ask about your data, report topics, or get help with the pipeline.</p>
                </div>
              ) : (
                messages.map((m) => <MessageBubble key={m.id} msg={m} />)
              )}
              {isTyping && <TypingIndicator />}
              <div ref={bottomRef} />
            </div>

            {/* Input */}
            <div className="border-t border-border p-4 bg-bg-surface">
              <div className="flex gap-3 items-end bg-bg-elevated border border-border rounded-xl p-3">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Message DocuMind AI… (Enter to send, Shift+Enter for newline)"
                  rows={1}
                  className="flex-1 bg-transparent text-sm text-txt-primary placeholder:text-txt-subtle resize-none outline-none max-h-32 min-h-[24px]"
                  style={{ height: "auto" }}
                  onInput={(e) => {
                    const t = e.currentTarget;
                    t.style.height = "auto";
                    t.style.height = Math.min(t.scrollHeight, 128) + "px";
                  }}
                />
                <button
                  onClick={handleSend}
                  disabled={!input.trim() || sendMut.isPending}
                  className="w-8 h-8 rounded-lg bg-brand hover:bg-brand-light disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center transition-colors flex-shrink-0"
                >
                  {sendMut.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin text-white" /> : <Send className="w-3.5 h-3.5 text-white" />}
                </button>
              </div>
              <p className="text-[10px] text-txt-subtle mt-2 text-center">
                AI responses are generated using your configured LLM provider.
              </p>
            </div>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-center p-10">
            <div className="w-20 h-20 rounded-3xl bg-brand-soft flex items-center justify-center mb-6">
              <MessageSquare className="w-10 h-10 text-brand-light" />
            </div>
            <h3 className="text-xl font-bold text-txt-primary mb-2">AI Chat</h3>
            <p className="text-txt-muted text-sm max-w-sm leading-relaxed mb-6">
              Ask questions about your data, brainstorm report topics, or get help with the pipeline.
            </p>
            <button onClick={() => setShowNewThread(true)} className="btn-primary">
              <Plus className="w-4 h-4" />
              New Conversation
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
