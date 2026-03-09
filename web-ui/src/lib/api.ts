/**
 * Typed client for the Ira FastAPI backend.
 *
 * CORS reminder: add http://localhost:3000 to CORS_ORIGINS in the
 * backend .env so the Next.js dev server can reach the API.
 */

import { fetchEventSource } from "@microsoft/fetch-event-source";
import type {
  HealthResponse,
  FeedbackRequest,
  FeedbackResponse,
  PipelineResponse,
  OverdueResponse,
  EmailSearchRequest,
  EmailSearchResponse,
  EmailThread,
  BoardMeetingRequest,
  BoardMeetingResponse,
  TaskStreamCallbacks,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function authHeaders(): Record<string, string> {
  const key = process.env.NEXT_PUBLIC_IRA_API_KEY;
  if (key) return { Authorization: `Bearer ${key}` };
  return {};
}

function jsonHeaders(): Record<string, string> {
  return { "Content-Type": "application/json", ...authHeaders() };
}

// ── Agent list ──────────────────────────────────────────────────────────

export interface Agent {
  name: string;
  role: string;
  description: string;
}

interface AgentListResponse {
  agents: Agent[];
  count: number;
}

export async function fetchAgents(): Promise<Agent[]> {
  const res = await fetch(`${API_URL}/api/agents`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`GET /api/agents failed: ${res.status}`);
  const data: AgentListResponse = await res.json();
  return data.agents;
}

// ── Health ───────────────────────────────────────────────────────────────

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_URL}/api/health`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`GET /api/health failed: ${res.status}`);
  return res.json();
}

// ── Feedback ─────────────────────────────────────────────────────────────

export async function submitFeedback(
  req: FeedbackRequest,
): Promise<FeedbackResponse> {
  const res = await fetch(`${API_URL}/api/feedback`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ ...req, user_id: req.user_id ?? "web-user" }),
  });
  if (!res.ok) throw new Error(`POST /api/feedback failed: ${res.status}`);
  return res.json();
}

// ── Pipeline ─────────────────────────────────────────────────────────────

export async function fetchPipeline(): Promise<PipelineResponse> {
  const res = await fetch(`${API_URL}/api/pipeline`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`GET /api/pipeline failed: ${res.status}`);
  return res.json();
}

// ── Vendors ──────────────────────────────────────────────────────────────

export async function fetchVendorsOverdue(): Promise<OverdueResponse> {
  const res = await fetch(`${API_URL}/api/vendors/overdue`, {
    headers: authHeaders(),
  });
  if (!res.ok)
    throw new Error(`GET /api/vendors/overdue failed: ${res.status}`);
  return res.json();
}

// ── Email ────────────────────────────────────────────────────────────────

export async function searchEmails(
  req: EmailSearchRequest,
): Promise<EmailSearchResponse> {
  const res = await fetch(`${API_URL}/api/email/search`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(req),
  });
  if (!res.ok)
    throw new Error(`POST /api/email/search failed: ${res.status}`);
  return res.json();
}

export async function fetchEmailThread(
  threadId: string,
): Promise<EmailThread> {
  const res = await fetch(`${API_URL}/api/email/thread/${threadId}`, {
    headers: authHeaders(),
  });
  if (!res.ok)
    throw new Error(`GET /api/email/thread failed: ${res.status}`);
  return res.json();
}

// ── Board Meeting ────────────────────────────────────────────────────────

export async function startBoardMeeting(
  req: BoardMeetingRequest,
): Promise<BoardMeetingResponse> {
  const res = await fetch(`${API_URL}/api/board-meeting`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(req),
  });
  if (!res.ok)
    throw new Error(`POST /api/board-meeting failed: ${res.status}`);
  return res.json();
}

// ── SSE streaming query ─────────────────────────────────────────────────

export interface SSEProgress {
  type: string;
  agent?: string;
  role?: string;
  tool?: string;
  iteration?: number;
  preview?: string;
  [key: string]: unknown;
}

export interface SSEFinalAnswer {
  response: string;
  agents_consulted: string[] | null;
}

export interface StreamCallbacks {
  onProgress: (event: SSEProgress) => void;
  onFinalAnswer: (answer: SSEFinalAnswer) => void;
  onError: (error: string) => void;
}

export function streamQuery(
  query: string,
  targetAgent: string,
  callbacks: StreamCallbacks,
): AbortController {
  const ctrl = new AbortController();

  fetchEventSource(`${API_URL}/api/query/stream`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({
      query,
      user_id: "web-user",
      context: { channel: "WEB", target_agent: targetAgent },
    }),
    signal: ctrl.signal,

    onmessage(ev) {
      if (!ev.data) return;

      if (ev.event === "final_answer") {
        try {
          callbacks.onFinalAnswer(JSON.parse(ev.data));
        } catch {
          callbacks.onFinalAnswer({
            response: ev.data,
            agents_consulted: null,
          });
        }
        return;
      }

      if (ev.event === "error") {
        try {
          const parsed = JSON.parse(ev.data);
          callbacks.onError(parsed.error ?? ev.data);
        } catch {
          callbacks.onError(ev.data);
        }
        return;
      }

      try {
        callbacks.onProgress(JSON.parse(ev.data));
      } catch {
        callbacks.onProgress({ type: ev.event || "progress" });
      }
    },

    onerror(err) {
      callbacks.onError(err?.message ?? "Connection lost");
      throw err;
    },

    openWhenHidden: true,
  });

  return ctrl;
}

// ── Task stream ──────────────────────────────────────────────────────────

export function streamTask(
  goal: string,
  callbacks: TaskStreamCallbacks,
): AbortController {
  const ctrl = new AbortController();

  fetchEventSource(`${API_URL}/api/task/stream`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({
      goal,
      user_id: "web-user",
      output_format: "markdown",
    }),
    signal: ctrl.signal,

    onmessage(ev) {
      if (!ev.data) return;
      try {
        const data = JSON.parse(ev.data);

        if (ev.event === "clarification_needed") {
          callbacks.onClarificationNeeded(
            data.questions ?? [],
            data.task_id ?? "",
          );
          return;
        }

        if (ev.event === "task_result" || ev.event === "task_complete") {
          callbacks.onResult(data);
          return;
        }

        if (ev.event === "task_error") {
          callbacks.onError(data.error ?? "Task failed");
          return;
        }

        callbacks.onProgress(data);
      } catch {
        callbacks.onProgress({ type: ev.event || "progress" });
      }
    },

    onerror(err) {
      callbacks.onError(err?.message ?? "Connection lost");
      throw err;
    },

    openWhenHidden: true,
  });

  return ctrl;
}

export function submitTaskClarification(
  taskId: string,
  answer: string,
  callbacks: TaskStreamCallbacks,
): AbortController {
  const ctrl = new AbortController();

  fetchEventSource(`${API_URL}/api/task/clarify`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({
      task_id: taskId,
      answer,
      user_id: "web-user",
    }),
    signal: ctrl.signal,

    onmessage(ev) {
      if (!ev.data) return;
      try {
        const data = JSON.parse(ev.data);

        if (ev.event === "task_result" || ev.event === "task_complete") {
          callbacks.onResult(data);
          return;
        }

        if (ev.event === "task_error") {
          callbacks.onError(data.error ?? "Task failed");
          return;
        }

        callbacks.onProgress(data);
      } catch {
        callbacks.onProgress({ type: ev.event || "progress" });
      }
    },

    onerror(err) {
      callbacks.onError(err?.message ?? "Connection lost");
      throw err;
    },

    openWhenHidden: true,
  });

  return ctrl;
}
