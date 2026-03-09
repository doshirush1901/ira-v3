# `prompts/` — LLM Prompt Templates

71 text files that serve as configuration for Ira's LLM calls. Prompts
are loaded at runtime via `prompt_loader.load_prompt()` — never inlined
in Python source.

## Naming Conventions

| Pattern | Example | Purpose |
|:--------|:--------|:--------|
| `{agent}_system.txt` | `athena_system.txt` | Agent system prompt (one per agent) |
| `{task}.txt` | `extract_entities.txt` | Task-specific prompt |
| `{module}_{action}.txt` | `digestive_summarize.txt` | Module-scoped prompt |
| `dream_{stage}.txt` | `dream_insight.txt` | Dream mode stage prompts |
| `nemesis_{action}.txt` | `nemesis_training.txt` | Training/correction prompts |

## Template Variables

Prompts use `{variable_name}` for Python `.format()` substitution at
runtime. Common variables: `{query}`, `{context}`, `{agent_name}`,
`{tools}`, `{history}`.

## Guidelines

- Keep prompts under 2,000 tokens where possible.
- Never embed API keys, file paths, or env-specific values.
- The SOUL.md preamble is injected automatically by `BaseAgent.run()` —
  do not duplicate identity/voice/boundary rules in agent prompts.
