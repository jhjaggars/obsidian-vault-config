---
name: agent-metrics-dashboard
description: |
  Launch a local web dashboard for visualizing agent pipeline metrics.
  Shows token usage, tok/s comparison, context growth, cost estimates,
  error tracking, and tool usage across all agents and providers.
  Use this skill when the user wants to:
  - See agent metrics or pipeline performance
  - View token usage or cost dashboard
  - Compare Ollama vs Vertex performance
  - Launch the metrics dashboard
---

# Agent Metrics Dashboard

Launch the dashboard:

```bash
uv run .claude/skills/agent-metrics-dashboard/scripts/dashboard.py
```

Opens at http://localhost:9847. Reads from `~/.config/pkm-sync/agent_metrics.db` (read-only).

Custom port:

```bash
uv run .claude/skills/agent-metrics-dashboard/scripts/dashboard.py --port 8080
```
