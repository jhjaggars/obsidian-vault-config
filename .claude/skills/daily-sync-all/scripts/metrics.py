"""Agent metrics tracking — pure stdlib, crash-safe.

Records token usage, latency, and tool-call telemetry for every agent run.
Writes to both SQLite (for Datasette queries) and JSONL (for grep/tail).
All writes are wrapped in try/except so metrics never crash the agent.
"""

import json
import sqlite3
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("~/.config/pkm-sync/agent_metrics.db").expanduser()
JSONL_PATH = Path("~/Library/Logs/daily-work-sync/agent_metrics.jsonl").expanduser()

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id TEXT PRIMARY KEY,
    run_date TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    pipeline_step TEXT,
    trigger TEXT DEFAULT 'scheduled',
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    model_variant TEXT,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    thinking_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    wall_time_s REAL NOT NULL,
    time_to_first_tool REAL,
    total_turns INTEGER NOT NULL,
    total_tool_calls INTEGER DEFAULT 0,
    tools_used TEXT,
    completed BOOLEAN DEFAULT 1,
    stop_reason TEXT,
    error_message TEXT,
    ollama_eval_duration_ns INTEGER,
    ollama_prompt_eval_duration_ns INTEGER,
    ollama_load_duration_ns INTEGER,
    ollama_total_duration_ns INTEGER
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_date ON agent_runs(run_date);
CREATE INDEX IF NOT EXISTS idx_agent_runs_agent ON agent_runs(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_runs_model ON agent_runs(provider, model);

CREATE TABLE IF NOT EXISTS turn_details (
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    turn_number INTEGER NOT NULL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    thinking_tokens INTEGER DEFAULT 0,
    api_latency_s REAL,
    tool_calls INTEGER DEFAULT 0,
    tools_invoked TEXT,
    ollama_eval_count INTEGER,
    ollama_prompt_eval_count INTEGER,
    ollama_eval_duration_ns INTEGER,
    ollama_prompt_eval_duration_ns INTEGER,
    PRIMARY KEY (run_id, turn_number)
);
"""


def _ensure_db() -> sqlite3.Connection:
    """Create tables idempotently with WAL mode."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA_SQL)
    conn.commit()
    return conn


class RunMetrics:
    """Accumulates metrics for a single agent run."""

    def __init__(
        self,
        agent_name: str,
        provider: str,
        model: str,
        model_variant: str | None = None,
        pipeline_step: str | None = None,
        trigger: str = "scheduled",
    ):
        self.run_id = str(uuid.uuid4())
        self.agent_name = agent_name
        self.provider = provider
        self.model = model
        self.model_variant = model_variant
        self.pipeline_step = pipeline_step
        self.trigger = trigger

        self.wall_start = time.monotonic()
        self.run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Accumulators
        self._turn_number = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._thinking_tokens = 0
        self._cache_read_tokens = 0
        self._cache_write_tokens = 0
        self._tool_counter: Counter = Counter()
        self._total_tool_calls = 0
        self._time_to_first_tool: float | None = None
        self._turns: list[dict] = []

        # Ollama-specific accumulators
        self._ollama_eval_duration_ns = 0
        self._ollama_prompt_eval_duration_ns = 0
        self._ollama_load_duration_ns = 0
        self._ollama_total_duration_ns = 0

    def record_turn(
        self,
        response: object,
        tool_names: list[str],
        api_latency_s: float,
    ) -> None:
        """Record one API round-trip. Works for Anthropic and Ollama responses."""
        self._turn_number += 1
        usage = getattr(response, "usage", None)

        prompt_tok = getattr(usage, "input_tokens", 0) or 0
        completion_tok = getattr(usage, "output_tokens", 0) or 0
        thinking_tok = getattr(usage, "thinking_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0

        self._prompt_tokens += prompt_tok
        self._completion_tokens += completion_tok
        self._thinking_tokens += thinking_tok
        self._cache_read_tokens += cache_read
        self._cache_write_tokens += cache_write

        num_tools = len(tool_names)
        self._total_tool_calls += num_tools
        self._tool_counter.update(tool_names)
        if num_tools > 0 and self._time_to_first_tool is None:
            self._time_to_first_tool = time.monotonic() - self.wall_start

        # Ollama-specific timing
        ollama_eval_dur = getattr(usage, "eval_duration_ns", None)
        ollama_prompt_eval_dur = getattr(usage, "prompt_eval_duration_ns", None)
        ollama_load_dur = getattr(usage, "load_duration_ns", None)
        ollama_total_dur = getattr(usage, "total_duration_ns", None)
        ollama_eval_count = getattr(usage, "output_tokens", None) if ollama_eval_dur else None
        ollama_prompt_eval_count = getattr(usage, "input_tokens", None) if ollama_prompt_eval_dur else None

        if ollama_eval_dur:
            self._ollama_eval_duration_ns += ollama_eval_dur
        if ollama_prompt_eval_dur:
            self._ollama_prompt_eval_duration_ns += ollama_prompt_eval_dur
        if ollama_load_dur:
            self._ollama_load_duration_ns += ollama_load_dur
        if ollama_total_dur:
            self._ollama_total_duration_ns += ollama_total_dur

        self._turns.append({
            "turn_number": self._turn_number,
            "prompt_tokens": prompt_tok,
            "completion_tokens": completion_tok,
            "thinking_tokens": thinking_tok,
            "api_latency_s": round(api_latency_s, 3),
            "tool_calls": num_tools,
            "tools_invoked": ",".join(tool_names) if tool_names else None,
            "ollama_eval_count": ollama_eval_count,
            "ollama_prompt_eval_count": ollama_prompt_eval_count,
            "ollama_eval_duration_ns": ollama_eval_dur,
            "ollama_prompt_eval_duration_ns": ollama_prompt_eval_dur,
        })

    def finalize(
        self,
        completed: bool,
        stop_reason: str,
        error_message: str | None = None,
    ) -> None:
        """Compute aggregates and write to SQLite + JSONL."""
        wall_time = round(time.monotonic() - self.wall_start, 2)
        tools_used = json.dumps(dict(self._tool_counter)) if self._tool_counter else None

        run_row = {
            "run_id": self.run_id,
            "run_date": self.run_date,
            "agent_name": self.agent_name,
            "pipeline_step": self.pipeline_step,
            "trigger": self.trigger,
            "provider": self.provider,
            "model": self.model,
            "model_variant": self.model_variant,
            "prompt_tokens": self._prompt_tokens,
            "completion_tokens": self._completion_tokens,
            "thinking_tokens": self._thinking_tokens,
            "cache_read_tokens": self._cache_read_tokens,
            "cache_write_tokens": self._cache_write_tokens,
            "wall_time_s": wall_time,
            "time_to_first_tool": round(self._time_to_first_tool, 3) if self._time_to_first_tool is not None else None,
            "total_turns": self._turn_number,
            "total_tool_calls": self._total_tool_calls,
            "tools_used": tools_used,
            "completed": completed,
            "stop_reason": stop_reason,
            "error_message": error_message,
            "ollama_eval_duration_ns": self._ollama_eval_duration_ns or None,
            "ollama_prompt_eval_duration_ns": self._ollama_prompt_eval_duration_ns or None,
            "ollama_load_duration_ns": self._ollama_load_duration_ns or None,
            "ollama_total_duration_ns": self._ollama_total_duration_ns or None,
        }

        self._write_sqlite(run_row)
        self._write_jsonl(run_row)

    def _write_sqlite(self, run_row: dict) -> None:
        """Insert run + turn rows into SQLite. Never raises."""
        try:
            conn = _ensure_db()
            cols = list(run_row.keys())
            placeholders = ",".join("?" for _ in cols)
            conn.execute(
                f"INSERT INTO agent_runs ({','.join(cols)}) VALUES ({placeholders})",
                [run_row[c] for c in cols],
            )
            for turn in self._turns:
                turn_row = {"run_id": self.run_id, **turn}
                t_cols = list(turn_row.keys())
                t_ph = ",".join("?" for _ in t_cols)
                conn.execute(
                    f"INSERT INTO turn_details ({','.join(t_cols)}) VALUES ({t_ph})",
                    [turn_row[c] for c in t_cols],
                )
            conn.commit()
            conn.close()
        except Exception as exc:
            import sys
            print(f"[metrics] SQLite write failed (non-fatal): {exc}", file=sys.stderr)

    def _write_jsonl(self, run_row: dict) -> None:
        """Append a JSON line with run + turns. Never raises."""
        try:
            JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
            record = {**run_row, "turns": self._turns}
            with open(JSONL_PATH, "a") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except Exception as exc:
            import sys
            print(f"[metrics] JSONL write failed (non-fatal): {exc}", file=sys.stderr)
