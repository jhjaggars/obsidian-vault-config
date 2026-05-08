#!/usr/bin/env python3
# /// script
# dependencies = ["flask>=3.0"]
# ///
"""Agent metrics dashboard — read-only Flask app serving Chart.js visualizations."""

import argparse
import json
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

DB_PATH = Path("~/.config/pkm-sync/agent_metrics.db").expanduser()
TEMPLATE_DIR = Path(__file__).parent / "templates"

app = Flask(__name__)


def get_db():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def days_param():
    return request.args.get("days", "30", type=str)


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


@app.route("/")
def index():
    return send_from_directory(TEMPLATE_DIR, "index.html")


@app.route("/api/summary")
def api_summary():
    db = get_db()
    try:
        totals = db.execute("""
            SELECT COUNT(*) AS total_runs,
                COUNT(DISTINCT agent_name) AS agents,
                SUM(CASE WHEN completed = 1 THEN 1 ELSE 0 END) AS successes,
                SUM(CASE WHEN completed = 0 THEN 1 ELSE 0 END) AS failures,
                MAX(run_date) AS last_run_date
            FROM agent_runs
        """).fetchone()
        cost = db.execute("""
            SELECT ROUND(SUM(prompt_tokens) * 3.0 / 1e6
                + SUM(completion_tokens) * 15.0 / 1e6, 4) AS est_cost_usd
            FROM agent_runs
            WHERE provider IN ('anthropic', 'vertex')
        """).fetchone()
        result = dict(totals)
        result["est_cost_usd"] = cost["est_cost_usd"]
        return jsonify(result)
    finally:
        db.close()


@app.route("/api/tokens")
def api_tokens():
    db = get_db()
    try:
        rows = db.execute("""
            SELECT provider, model, COUNT(*) AS runs,
                SUM(prompt_tokens) AS total_prompt,
                SUM(completion_tokens) AS total_completion,
                SUM(thinking_tokens) AS total_thinking,
                ROUND(AVG(prompt_tokens + completion_tokens), 0) AS avg_tokens_per_run,
                ROUND(AVG(wall_time_s), 1) AS avg_wall_s
            FROM agent_runs
            WHERE run_date >= date('now', ? || ' days')
            GROUP BY provider, model
            ORDER BY total_prompt + total_completion DESC
        """, (f"-{days_param()}",)).fetchall()
        return jsonify(rows_to_dicts(rows))
    finally:
        db.close()


@app.route("/api/tokps")
def api_tokps():
    db = get_db()
    try:
        rows = db.execute("""
            SELECT provider, model, COUNT(*) AS runs,
                ROUND(SUM(completion_tokens) * 1.0 / SUM(wall_time_s), 1) AS wall_tok_per_s,
                CASE WHEN SUM(ollama_eval_duration_ns) > 0
                    THEN ROUND(SUM(completion_tokens) * 1.0
                        / (SUM(ollama_eval_duration_ns) / 1e9), 1)
                    ELSE NULL END AS native_tok_per_s,
                ROUND(AVG(wall_time_s), 1) AS avg_wall_s
            FROM agent_runs
            WHERE run_date >= date('now', ? || ' days') AND wall_time_s > 0
            GROUP BY provider, model
            ORDER BY wall_tok_per_s DESC
        """, (f"-{days_param()}",)).fetchall()
        return jsonify(rows_to_dicts(rows))
    finally:
        db.close()


@app.route("/api/context")
def api_context():
    db = get_db()
    try:
        rows = db.execute("""
            SELECT r.run_id, r.agent_name, r.model,
                r.pipeline_step, r.trigger, r.run_date,
                t.turn_number, t.prompt_tokens, t.completion_tokens,
                t.tool_calls, t.api_latency_s
            FROM turn_details t
            JOIN agent_runs r ON r.run_id = t.run_id
            WHERE r.run_date >= date('now', ? || ' days')
            ORDER BY r.run_id, t.turn_number
        """, (f"-{days_param()}",)).fetchall()

        runs = {}
        for r in rows:
            d = dict(r)
            rid = d.pop("run_id")
            if rid not in runs:
                runs[rid] = {
                    "run_id": rid,
                    "agent_name": d.pop("agent_name"),
                    "model": d.pop("model"),
                    "pipeline_step": d.pop("pipeline_step"),
                    "trigger": d.pop("trigger"),
                    "run_date": d.pop("run_date"),
                    "turns": [],
                }
            else:
                d.pop("agent_name")
                d.pop("model")
                d.pop("pipeline_step")
                d.pop("trigger")
                d.pop("run_date")
            runs[rid]["turns"].append(d)

        return jsonify(list(runs.values()))
    finally:
        db.close()


@app.route("/api/cost")
def api_cost():
    db = get_db()
    try:
        rows = db.execute("""
            SELECT run_date, COUNT(*) AS runs,
                SUM(prompt_tokens) AS prompt_tok,
                SUM(completion_tokens) AS completion_tok,
                ROUND(SUM(prompt_tokens) * 3.0 / 1e6
                    + SUM(completion_tokens) * 15.0 / 1e6, 4) AS est_cost_usd,
                SUM(cache_read_tokens) AS cache_read_tok
            FROM agent_runs
            WHERE provider IN ('anthropic', 'vertex')
            GROUP BY run_date
            ORDER BY run_date DESC
            LIMIT ?
        """, (int(days_param()),)).fetchall()
        return jsonify(rows_to_dicts(rows))
    finally:
        db.close()


@app.route("/api/errors")
def api_errors():
    db = get_db()
    try:
        rows = db.execute("""
            SELECT run_date, agent_name, model, total_turns,
                stop_reason, error_message, wall_time_s
            FROM agent_runs
            WHERE completed = 0 OR stop_reason = 'max_turns'
                OR error_message IS NOT NULL
            ORDER BY run_date DESC
            LIMIT 100
        """).fetchall()
        return jsonify(rows_to_dicts(rows))
    finally:
        db.close()


@app.route("/api/tools")
def api_tools():
    db = get_db()
    try:
        rows = db.execute("""
            SELECT agent_name, model, tools_used, total_tool_calls
            FROM agent_runs
            WHERE run_date >= date('now', ? || ' days')
                AND tools_used IS NOT NULL
        """, (f"-{days_param()}",)).fetchall()

        agg = {}
        for r in rows:
            key = (r["agent_name"], r["model"])
            if key not in agg:
                agg[key] = {"agent_name": r["agent_name"], "model": r["model"],
                            "runs": 0, "total_tool_calls": 0, "tools": {}}
            agg[key]["runs"] += 1
            agg[key]["total_tool_calls"] += r["total_tool_calls"]
            tools = json.loads(r["tools_used"])
            for tool, count in tools.items():
                agg[key]["tools"][tool] = agg[key]["tools"].get(tool, 0) + count

        result = list(agg.values())
        for entry in result:
            entry["avg_tools_per_run"] = round(
                entry["total_tool_calls"] / entry["runs"], 1
            ) if entry["runs"] else 0
        return jsonify(result)
    finally:
        db.close()


def _launchd_socket():
    """Return a socket from launchd activation, or None if not launched by launchd."""
    import socket
    try:
        import ctypes
        import ctypes.util
        lib = ctypes.CDLL(ctypes.util.find_library("System"))
        lib.launch_activate_socket.argtypes = [
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_int)),
            ctypes.POINTER(ctypes.c_size_t),
        ]
        lib.launch_activate_socket.restype = ctypes.c_int
        fds = ctypes.POINTER(ctypes.c_int)()
        cnt = ctypes.c_size_t(0)
        err = lib.launch_activate_socket(b"MetricsSock", ctypes.byref(fds), ctypes.byref(cnt))
        if err == 0 and cnt.value > 0:
            fd = fds[0]
            sock = socket.fromfd(fd, socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            return sock
    except Exception:
        pass
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agent metrics dashboard")
    parser.add_argument("--port", type=int, default=9847)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"Error: database not found at {DB_PATH}")
        raise SystemExit(1)

    from werkzeug.serving import make_server
    sock = _launchd_socket()
    if sock:
        print("Dashboard: started via launchd socket activation")
        server = make_server(args.host, args.port, app, fd=sock.fileno())
    else:
        print(f"Dashboard: http://{args.host}:{args.port}")
        server = make_server(args.host, args.port, app)
    server.serve_forever()
