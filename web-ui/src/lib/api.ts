/**
 * Typed client for the Ira FastAPI backend.
 *
 * CORS reminder: add http://localhost:3000 to CORS_ORIGINS in the
 * backend .env so the Next.js dev server can reach the API.
 */

import { fetchEventSource } from "@microsoft/fetch-event-source";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function authHeaders(): Record<string, string> {
  const key = process.env.NEXT_PUBLIC_IRA_API_KEY;
  if (key) return { Authorization: `Bearer ${key}` };
  return {};
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
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
    },
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
          callbacks.onFinalAnswer({ response: ev.data, agents_consulted: null });
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
