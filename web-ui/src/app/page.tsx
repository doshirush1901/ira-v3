"use client";

import { useState, useEffect } from "react";
import { ChevronDown } from "lucide-react";
import Chat from "@/components/Chat";
import { fetchAgents, type Agent } from "@/lib/api";

export default function Home() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selected, setSelected] = useState("athena");
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    fetchAgents()
      .then((list) => {
        setAgents(list);
        if (list.length > 0 && !list.some((a) => a.name === "athena")) {
          setSelected(list[0].name);
        }
      })
      .catch((err) => {
        setLoadError(err.message);
        setAgents([
          { name: "athena", role: "Orchestrator", description: "" },
          { name: "prometheus", role: "Sales", description: "" },
          { name: "plutus", role: "Finance", description: "" },
          { name: "clio", role: "Research", description: "" },
        ]);
      });
  }, []);

  const current = agents.find((a) => a.name === selected);

  return (
    <div className="flex h-screen flex-col bg-[var(--bg-primary)]">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-[var(--border)] px-6 py-3">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold tracking-tight text-[var(--text-primary)]">
            Ira
          </h1>
          <span className="text-xs text-[var(--text-secondary)]">
            Machinecraft AI
          </span>
        </div>

        <div className="flex items-center gap-3">
          {loadError && (
            <span className="text-xs text-amber-400" title={loadError}>
              offline
            </span>
          )}

          <div className="relative">
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              className="appearance-none rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] py-1.5 pl-3 pr-8 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]"
            >
              {agents.map((a) => (
                <option key={a.name} value={a.name}>
                  {a.name} — {a.role}
                </option>
              ))}
            </select>
            <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-secondary)]" />
          </div>
        </div>
      </header>

      {/* Agent description bar */}
      {current?.description && (
        <div className="border-b border-[var(--border)] bg-[var(--bg-secondary)] px-6 py-1.5">
          <p className="text-xs text-[var(--text-secondary)]">
            {current.description}
          </p>
        </div>
      )}

      {/* Chat area */}
      <Chat targetAgent={selected} />
    </div>
  );
}
