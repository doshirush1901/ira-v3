"use client";

import { useEffect, useMemo, useState } from "react";
import {
  abortTask,
  fetchTaskEvents,
  fetchTasks,
  streamTaskRetry,
} from "@/lib/api";
import type { TaskProgress, TaskState } from "@/lib/types";
import { Button } from "@/components/ui/button";

function compactEvent(ev: TaskProgress): string {
  const type = String(ev.type ?? "event");
  if (type === "phase_progress") {
    return `${type} ${String(ev.phase_index ?? "?")}/${String(ev.total_phases ?? "?")} (${String(ev.progress_pct ?? 0)}%)`;
  }
  return type;
}

export default function TasksPage() {
  const [tasks, setTasks] = useState<TaskState[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string>("");
  const [events, setEvents] = useState<TaskProgress[]>([]);
  const [eventFilter, setEventFilter] = useState("all");
  const [retryPhase, setRetryPhase] = useState("0");
  const [streaming, setStreaming] = useState(false);
  const [statusLines, setStatusLines] = useState<string[]>([]);
  const [error, setError] = useState("");

  async function refreshTasks(): Promise<void> {
    setError("");
    try {
      const res = await fetchTasks(30);
      setTasks(res.tasks ?? []);
      if (!selectedTaskId && (res.tasks?.length ?? 0) > 0) {
        setSelectedTaskId(String(res.tasks?.[0]?.task_id ?? ""));
      }
    } catch (err) {
      setError(String(err));
    }
  }

  async function refreshEvents(taskId: string): Promise<void> {
    if (!taskId) return;
    setError("");
    try {
      const res = await fetchTaskEvents(taskId, 300);
      setEvents(res.events ?? []);
    } catch (err) {
      setError(String(err));
    }
  }

  useEffect(() => {
    void refreshTasks();
  }, []);

  useEffect(() => {
    if (!selectedTaskId) return;
    void refreshEvents(selectedTaskId);
  }, [selectedTaskId]);

  const eventTypes = useMemo(() => {
    return Array.from(new Set(events.map((ev) => String(ev.type ?? "event")))).sort();
  }, [events]);

  const filteredEvents = useMemo(() => {
    if (eventFilter === "all") return events;
    return events.filter((ev) => String(ev.type ?? "event") === eventFilter);
  }, [events, eventFilter]);

  function startRetry(taskId: string): void {
    if (!taskId || streaming) return;
    setStreaming(true);
    setStatusLines([]);
    const parsed = Number(retryPhase);
    const phase = Number.isFinite(parsed) ? parsed : 0;
    streamTaskRetry(
      taskId,
      {
        onProgress(ev) {
          const line = compactEvent(ev);
          setStatusLines((prev) => (prev.includes(line) ? prev : [...prev.slice(-8), line]));
        },
        onClarificationNeeded(questions, clarificationTaskId) {
          setStatusLines((prev) => [
            ...prev,
            `clarification_needed (${clarificationTaskId}): ${questions.join(" | ")}`,
          ]);
          setStreaming(false);
          void refreshTasks();
          void refreshEvents(taskId);
        },
        onResult(result) {
          setStatusLines((prev) => [
            ...prev,
            `task_result: ${String(result.status ?? "complete")}`,
          ]);
          setStreaming(false);
          void refreshTasks();
          void refreshEvents(taskId);
        },
        onError(err) {
          setStatusLines((prev) => [...prev, `error: ${err}`]);
          setStreaming(false);
        },
      },
      phase,
    );
  }

  async function stopTask(taskId: string): Promise<void> {
    if (!taskId) return;
    await abortTask(taskId, "Stopped from Tasks page");
    await refreshTasks();
    await refreshEvents(taskId);
  }

  function downloadEvents(): void {
    if (!selectedTaskId) return;
    const blob = new Blob([JSON.stringify(events, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `task_${selectedTaskId}_events.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6">
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-[var(--text-primary)]">Task Console</h1>
            <p className="text-sm text-[var(--text-secondary)]">
              Monitor, retry, and inspect multi-phase task runs.
            </p>
          </div>
          <Button type="button" variant="outline" onClick={() => void refreshTasks()}>
            Refresh
          </Button>
        </div>

        {error && (
          <div className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="rounded border border-[var(--border)] bg-[var(--bg-secondary)] p-3">
            <p className="mb-2 text-sm font-medium">Recent Tasks</p>
            <div className="space-y-2">
              {tasks.map((t) => (
                <button
                  key={String(t.task_id)}
                  className={`w-full rounded border px-2 py-2 text-left text-xs ${
                    selectedTaskId === String(t.task_id)
                      ? "border-[var(--accent)] bg-[var(--bg-tertiary)]"
                      : "border-[var(--border)]"
                  }`}
                  onClick={() => setSelectedTaskId(String(t.task_id))}
                >
                  <p className="truncate text-[var(--text-primary)]">{String(t.task_id)}</p>
                  <p className="truncate text-[var(--text-secondary)]">{String(t.status ?? "")}</p>
                </button>
              ))}
              {tasks.length === 0 && (
                <p className="text-xs text-[var(--text-secondary)]">No tasks found.</p>
              )}
            </div>
          </div>

          <div className="rounded border border-[var(--border)] bg-[var(--bg-secondary)] p-3 md:col-span-2">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <p className="text-sm font-medium">Selected: {selectedTaskId || "-"}</p>
              <select
                value={eventFilter}
                onChange={(e) => setEventFilter(e.target.value)}
                className="rounded border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1 text-xs"
              >
                <option value="all">all</option>
                {eventTypes.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
              <input
                type="number"
                min={0}
                value={retryPhase}
                onChange={(e) => setRetryPhase(e.target.value)}
                className="w-20 rounded border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1 text-xs"
                title="Retry from phase index"
              />
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => startRetry(selectedTaskId)}
                disabled={!selectedTaskId || streaming}
              >
                Retry
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => void stopTask(selectedTaskId)}
                disabled={!selectedTaskId}
              >
                Abort
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={downloadEvents}
                disabled={!selectedTaskId}
              >
                Download JSON
              </Button>
            </div>

            {statusLines.length > 0 && (
              <div className="mb-3 rounded border border-[var(--border)] p-2 text-xs">
                {statusLines.map((line, idx) => (
                  <p key={`${line}-${idx}`}>{line}</p>
                ))}
              </div>
            )}

            <div className="max-h-[26rem] overflow-auto rounded border border-[var(--border)] p-2 text-xs">
              {filteredEvents.length > 0 ? (
                filteredEvents.map((ev, idx) => (
                  <p key={`${String(ev.type ?? "event")}-${idx}`} className="py-0.5">
                    {String(ev.timestamp ?? "")} {compactEvent(ev)}
                  </p>
                ))
              ) : (
                <p className="text-[var(--text-secondary)]">No events for selected task/filter.</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
