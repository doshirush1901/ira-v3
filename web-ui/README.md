# `web-ui/` — Next.js Web Interface

A team-facing web interface for Ira, built with Next.js (App Router),
Tailwind CSS, and shadcn/ui. Connects to the FastAPI backend via SSE
streaming.

## Pages

| Route | Description |
|:------|:------------|
| `/chat` | Pantheon Chat — agent selector, SSE streaming, feedback buttons |
| `/crm` | Pipeline kanban, vendor payables table, email search |
| `/board-meeting` | Multi-agent strategic discussions with split-screen results |
| `/corrections` | Corrections log with stats and filtering |

## Setup

```bash
cd web-ui
npm install
npm run dev    # → http://localhost:3000
```

Set `CORS_ORIGINS=http://localhost:3000` in the backend `.env`.
If the backend has `API_SECRET_KEY` set, add `NEXT_PUBLIC_IRA_API_KEY=<key>`
to `web-ui/.env.local`.

## Stack

- **Framework:** Next.js 14 (App Router)
- **Styling:** Tailwind CSS + shadcn/ui components
- **Data fetching:** SWR + native fetch with SSE
- **State:** React hooks (no external state library)

## Directory Structure

```
src/
├── app/              Pages (chat, crm, board-meeting, corrections)
├── components/       Feature components (Chat, PipelineBoard, EmailSearch, etc.)
│   └── ui/           shadcn/ui primitives (button, badge, tabs, etc.)
└── lib/              API client, SWR config, types, utilities
```
