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
  streamTask,
  submitTaskClarification,
  abortTask,
  fetchTasks,
  fetchTaskEvents,
  streamTaskRetry,
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

interface TaskSummary {
  task_id: string;
  status: string;
  goal?: string;
}

interface TaskEvent {
  type?: string;
  timestamp?: string;
  [key: string]: unknown;
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
  runAsTaskLoop?: boolean;
}

export default function Chat({ targetAgent, runAsTaskLoop = false }: ChatProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [statusLines, setStatusLines] = useState<StatusLine[]>([]);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [awaitingClarification, setAwaitingClarification] = useState(false);
  const [recentTasks, setRecentTasks] = useState<TaskSummary[]>([]);
  const [retryPhaseByTask, setRetryPhaseByTask] = useState<Record<string, string>>({});
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [taskEvents, setTaskEvents] = useState<TaskEvent[]>([]);
  const [eventFilter, setEventFilter] = useState("all");
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

  useEffect(() => {
    if (!runAsTaskLoop) return;
    void fetchTasks(8)
      .then((res) => {
        setRecentTasks(
          (res.tasks ?? []).map((t) => ({
            task_id: String(t.task_id),
            status: String(t.status ?? "unknown"),
            goal: String(t.goal ?? ""),
          })),
        );
      })
      .catch(() => {});
  }, [runAsTaskLoop, messages.length]);

  function handleStop() {
    if (runAsTaskLoop && activeTaskId) {
      void abortTask(activeTaskId);
    }
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming(false);
    setStatusLines([]);
    setAwaitingClarification(false);
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

    const ctrl = runAsTaskLoop
      ? (awaitingClarification && activeTaskId
          ? submitTaskClarification(activeTaskId, trimmed, {
              onProgress(ev) {
                setStatusLines((prev) => {
                  const key = String(ev.type ?? "progress");
                  const label =
                    ev.type === "phase_progress"
                      ? `Phase ${String(ev.phase_index ?? "?")}/${String(ev.total_phases ?? "?")} - ${String(ev.progress_pct ?? 0)}%`
                      : String(ev.type ?? "progress");
                  const next = { key, text: label };
                  const exists = prev.some((s) => s.key === next.key && s.text === next.text);
                  return exists ? prev : [...prev.slice(-6), next];
                });
              },
              onClarificationNeeded() {},
              onResult(result) {
                setMessages((prev) => [
                  ...prev,
                  {
                    role: "assistant",
                    content: result.summary || result.file_path || "Task completed.",
                    precedingQuery: trimmed,
                  },
                ]);
                setStreaming(false);
                setStatusLines([]);
                setAwaitingClarification(false);
              },
              onError(error) {
                setMessages((prev) => [
                  ...prev,
                  { role: "assistant", content: `**Error:** ${error}`, precedingQuery: trimmed },
                ]);
                setStreaming(false);
                setStatusLines([]);
              },
            })
          : streamTask(trimmed, {
              onProgress(ev) {
                if (ev.task_id) setActiveTaskId(String(ev.task_id));
                setStatusLines((prev) => {
                  const key = String(ev.type ?? "progress");
                  const label =
                    ev.type === "phase_progress"
                      ? `Phase ${String(ev.phase_index ?? "?")}/${String(ev.total_phases ?? "?")} - ${String(ev.progress_pct ?? 0)}%`
                      : String(ev.type ?? "progress");
                  const next = { key, text: label };
                  const exists = prev.some((s) => s.key === next.key && s.text === next.text);
                  return exists ? prev : [...prev.slice(-6), next];
                });
              },
              onClarificationNeeded(questions, taskId) {
                setActiveTaskId(taskId || null);
                setAwaitingClarification(true);
                setStreaming(false);
                setStatusLines([]);
                setMessages((prev) => [
                  ...prev,
                  {
                    role: "assistant",
                    content: `Need clarification before continuing:\n\n- ${questions.join("\n- ")}`,
                    precedingQuery: trimmed,
                  },
                ]);
              },
              onResult(result) {
                setMessages((prev) => [
                  ...prev,
                  {
                    role: "assistant",
                    content: result.summary || result.file_path || "Task completed.",
                    precedingQuery: trimmed,
                  },
                ]);
                setStreaming(false);
                setStatusLines([]);
                setAwaitingClarification(false);
              },
              onError(error) {
                setMessages((prev) => [
                  ...prev,
                  { role: "assistant", content: `**Error:** ${error}`, precedingQuery: trimmed },
                ]);
                setStreaming(false);
                setStatusLines([]);
              },
            }))
      : streamQuery(trimmed, targetAgent, {
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

  function runRetry(taskId: string) {
    if (streaming) return;
    const phaseRaw = retryPhaseByTask[taskId];
    const phase = phaseRaw === undefined || phaseRaw === "" ? undefined : Number(phaseRaw);
    setStreaming(true);
    setStatusLines([]);
    const ctrl = streamTaskRetry(
      taskId,
      {
        onProgress(ev) {
          if (ev.task_id) setActiveTaskId(String(ev.task_id));
          setStatusLines((prev) => {
            const key = String(ev.type ?? "progress");
            const label =
              ev.type === "phase_progress"
                ? `Phase ${String(ev.phase_index ?? "?")}/${String(ev.total_phases ?? "?")} - ${String(ev.progress_pct ?? 0)}%`
                : String(ev.type ?? "progress");
            const next = { key, text: label };
            const exists = prev.some((s) => s.key === next.key && s.text === next.text);
            return exists ? prev : [...prev.slice(-6), next];
          });
        },
        onClarificationNeeded(questions, taskIdFromEvent) {
          setActiveTaskId(taskIdFromEvent || null);
          setAwaitingClarification(true);
          setStreaming(false);
          setStatusLines([]);
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: `Retry needs clarification:\n\n- ${questions.join("\n- ")}` },
          ]);
        },
        onResult(result) {
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: result.summary || result.file_path || "Retry completed." },
          ]);
          setStreaming(false);
          setStatusLines([]);
        },
        onError(error) {
          setMessages((prev) => [...prev, { role: "assistant", content: `**Error:** ${error}` }]);
          setStreaming(false);
          setStatusLines([]);
        },
      },
      Number.isFinite(phase) ? phase : undefined,
    );
    abortRef.current = ctrl;
  }

  async function showTaskEvents(taskId: string) {
    try {
      const res = await fetchTaskEvents(taskId, 200);
      setSelectedTaskId(taskId);
      setTaskEvents((res.events || []) as TaskEvent[]);
      setEventFilter("all");
      if ((res.events || []).length === 0) {
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: `No events found for task \`${taskId}\`.`,
          },
        ]);
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `**Error:** ${String(err)}` },
      ]);
    }
  }

  function downloadTaskEvents() {
    if (!selectedTaskId || taskEvents.length === 0) return;
    const blob = new Blob([JSON.stringify(taskEvents, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `task_${selectedTaskId}_events.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const filteredTaskEvents =
    eventFilter === "all"
      ? taskEvents
      : taskEvents.filter((ev) => String(ev.type ?? "unknown") === eventFilter);

  const availableEventTypes = Array.from(
    new Set(taskEvents.map((ev) => String(ev.type ?? "unknown"))),
  ).sort();

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
          {runAsTaskLoop && recentTasks.length > 0 && (
            <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-3">
              <p className="mb-2 text-xs text-[var(--text-secondary)]">Recent tasks</p>
              <div className="space-y-2">
                {recentTasks.slice(0, 5).map((t) => (
                  <div key={t.task_id} className="flex items-center justify-between gap-2 text-xs">
                    <div className="min-w-0">
                      <p className="truncate text-[var(--text-primary)]">{t.task_id}</p>
                      <p className="truncate text-[var(--text-secondary)]">{t.status}</p>
                    </div>
                    <div className="flex items-center gap-1">
                      <input
                        type="number"
                        min={0}
                        placeholder="from"
                        value={retryPhaseByTask[t.task_id] ?? ""}
                        onChange={(e) =>
                          setRetryPhaseByTask((prev) => ({
                            ...prev,
                            [t.task_id]: e.target.value,
                          }))
                        }
                        className="w-16 rounded border border-[var(--border)] bg-[var(--bg-primary)] px-1 py-1 text-xs"
                      />
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => showTaskEvents(t.task_id)}
                      >
                        Events
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => runRetry(t.task_id)}
                      >
                        Retry
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
              {selectedTaskId && (
                <div className="mt-3 border-t border-[var(--border)] pt-3">
                  <div className="mb-2 flex items-center gap-2">
                    <p className="text-xs text-[var(--text-secondary)]">
                      Timeline: {selectedTaskId}
                    </p>
                    <select
                      className="rounded border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1 text-xs"
                      value={eventFilter}
                      onChange={(e) => setEventFilter(e.target.value)}
                    >
                      <option value="all">all</option>
                      {availableEventTypes.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={downloadTaskEvents}
                    >
                      Download JSON
                    </Button>
                  </div>
                  <div className="max-h-36 overflow-auto rounded border border-[var(--border)] p-2 text-xs">
                    {filteredTaskEvents.slice(-20).map((ev, idx) => (
                      <p key={`${String(ev.type ?? "event")}-${idx}`} className="py-0.5">
                        {String(ev.timestamp ?? "")} {String(ev.type ?? "event")}
                      </p>
                    ))}
                    {filteredTaskEvents.length === 0 && (
                      <p className="text-[var(--text-secondary)]">No events for selected filter.</p>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
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
