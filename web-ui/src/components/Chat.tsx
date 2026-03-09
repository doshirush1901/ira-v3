"use client";

import {
  useState,
  useRef,
  useEffect,
  useCallback,
  type FormEvent,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Send, Loader2, Bot, User, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import FeedbackForm from "@/components/FeedbackForm";
import {
  streamQuery,
  type SSEProgress,
  type SSEFinalAnswer,
} from "@/lib/api";

// ── Types ───────────────────────────────────────────────────────────────

interface Message {
  role: "user" | "assistant";
  content: string;
  agents?: string[];
  precedingQuery?: string;
}

interface StatusLine {
  key: string;
  text: string;
}

// ── Helpers ─────────────────────────────────────────────────────────────

function progressToStatus(ev: SSEProgress): StatusLine {
  const labels: Record<string, string> = {
    perceiving: "Perceiving input\u2026",
    remembering: "Recalling context\u2026",
    fast_path: "Fast path matched",
    sphinx_checking: "Checking query clarity\u2026",
    sphinx_clarifying: "Asking clarifying questions\u2026",
    routing: "Routing query\u2026",
    synthesizing: "Synthesizing responses\u2026",
    enriching: "Enriching context\u2026",
    assessing: "Assessing confidence\u2026",
    reflecting: "Reflecting\u2026",
    shaping: "Shaping response\u2026",
    gap_resolving: "Resolving knowledge gaps\u2026",
    faithfulness_check: "Checking faithfulness\u2026",
  };

  if (ev.type === "agent_started") {
    return {
      key: `started-${ev.agent}`,
      text: `${ev.agent} (${ev.role ?? "agent"}) is working\u2026`,
    };
  }
  if (ev.type === "agent_thinking") {
    return {
      key: `thinking-${ev.agent}-${ev.iteration}`,
      text: `${ev.agent} is thinking (step ${ev.iteration})\u2026`,
    };
  }
  if (ev.type === "tool_called") {
    return {
      key: `tool-${ev.agent}-${ev.tool}`,
      text: `${ev.agent} \u2192 ${ev.tool}`,
    };
  }
  if (ev.type === "agent_done") {
    return {
      key: `done-${ev.agent}`,
      text: `${ev.agent} finished`,
    };
  }

  return {
    key: ev.type,
    text: labels[ev.type] ?? ev.type.replace(/_/g, " "),
  };
}

// ── Component ───────────────────────────────────────────────────────────

interface ChatProps {
  targetAgent: string;
}

export default function Chat({ targetAgent }: ChatProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [statusLines, setStatusLines] = useState<StatusLine[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: "smooth",
      });
    });
  }, []);

  useEffect(scrollToBottom, [messages, statusLines, scrollToBottom]);
  useEffect(() => {
    if (!streaming) inputRef.current?.focus();
  }, [streaming]);

  function handleStop() {
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming(false);
    setStatusLines([]);
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || streaming) return;

    const userMsg: Message = { role: "user", content: trimmed };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setStreaming(true);
    setStatusLines([]);

    const ctrl = streamQuery(trimmed, targetAgent, {
      onProgress(ev: SSEProgress) {
        setStatusLines((prev) => {
          const next = progressToStatus(ev);
          const exists = prev.some((s) => s.key === next.key);
          return exists ? prev : [...prev.slice(-6), next];
        });
      },
      onFinalAnswer(answer: SSEFinalAnswer) {
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: answer.response,
            agents: answer.agents_consulted ?? undefined,
            precedingQuery: trimmed,
          },
        ]);
        setStatusLines([]);
        setStreaming(false);
      },
      onError(error: string) {
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: `**Error:** ${error}`,
            precedingQuery: trimmed,
          },
        ]);
        setStatusLines([]);
        setStreaming(false);
      },
    });

    abortRef.current = ctrl;
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e as unknown as FormEvent);
    }
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-6">
        <div className="mx-auto max-w-3xl space-y-4">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center pt-32 text-center">
              <Bot className="mb-4 h-12 w-12 text-[var(--text-secondary)]" />
              <h2 className="mb-2 text-2xl font-semibold">Talk to Ira</h2>
              <p className="max-w-md text-sm text-[var(--text-secondary)]">
                Ask about sales pipeline, quotes, machine specs, customer
                history, or project status.
              </p>
            </div>
          )}

          {messages.map((msg, i) => (
            <div
              key={i}
              className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              {msg.role === "assistant" && (
                <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--accent)]/15">
                  <Bot className="h-4 w-4 text-[var(--accent)]" />
                </div>
              )}

              <div
                className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                  msg.role === "user"
                    ? "bg-[var(--user-bubble)] text-[var(--text-primary)]"
                    : "bg-[var(--ira-bubble)] text-[var(--text-primary)]"
                }`}
              >
                {msg.role === "assistant" ? (
                  <div>
                    <div className="markdown-body">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {msg.content}
                      </ReactMarkdown>
                    </div>
                    {msg.agents && msg.agents.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-1.5 border-t border-[var(--border)] pt-2">
                        {msg.agents.map((a) => (
                          <span
                            key={a}
                            className="rounded-full bg-[var(--bg-tertiary)] px-2.5 py-0.5 text-xs text-[var(--text-secondary)]"
                          >
                            {a}
                          </span>
                        ))}
                      </div>
                    )}
                    <FeedbackForm
                      previousQuery={msg.precedingQuery ?? ""}
                      previousResponse={msg.content}
                    />
                  </div>
                ) : (
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                )}
              </div>

              {msg.role === "user" && (
                <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--user-bubble)]">
                  <User className="h-4 w-4 text-[var(--text-primary)]" />
                </div>
              )}
            </div>
          ))}

          {/* Status indicators */}
          {statusLines.length > 0 && (
            <div className="flex gap-3">
              <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--accent)]/15">
                <Loader2 className="h-4 w-4 animate-spin text-[var(--accent)]" />
              </div>
              <div className="space-y-1 py-2">
                {statusLines.map((s) => (
                  <p
                    key={s.key}
                    className="text-xs text-[var(--text-secondary)]"
                  >
                    {s.text}
                  </p>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Input bar */}
      <div className="border-t border-[var(--border)] px-4 py-3">
        <form
          onSubmit={handleSubmit}
          className="mx-auto flex max-w-3xl items-end gap-3"
        >
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask Ira anything\u2026"
            disabled={streaming}
            rows={1}
            className="flex-1 resize-none rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-3 text-sm text-[var(--text-primary)] placeholder-[var(--text-secondary)] outline-none transition-colors focus:border-[var(--accent)] disabled:opacity-50"
          />
          {streaming ? (
            <Button
              type="button"
              variant="destructive"
              size="icon"
              className="h-11 w-11 shrink-0 rounded-xl"
              onClick={handleStop}
              title="Stop generation"
            >
              <Square className="h-4 w-4" />
            </Button>
          ) : (
            <Button
              type="submit"
              disabled={!input.trim()}
              size="icon"
              className="h-11 w-11 shrink-0 rounded-xl"
            >
              <Send className="h-4 w-4" />
            </Button>
          )}
        </form>
      </div>
    </div>
  );
}
