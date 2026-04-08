#!/usr/bin/env python3
"""Search archive.db emails with FTS4 keyword search and structured filters."""

import argparse
import json
import os
import sqlite3
import sys

DEFAULT_DB = os.path.expanduser("~/.config/pkm-sync/archive.db")


def parse_args():
    p = argparse.ArgumentParser(description="Search Gmail archive.db")
    p.add_argument("query", nargs="?", default="", help="FTS4 MATCH query string")
    p.add_argument("--from", dest="from_addr", default="", help="Filter sender (substring)")
    p.add_argument("--since", default="", help="Filter date_sent >= YYYY-MM-DD")
    p.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    p.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")
    p.add_argument("--body", action="store_true", help="Include email body text")
    p.add_argument("--db", default=DEFAULT_DB, help="Path to archive.db")
    return p.parse_args()


def build_query(args):
    select = """
        SELECT m.gmail_id, m.thread_id, m.subject, m.from_addr,
               m.to_addrs, m.cc_addrs, m.date_sent, m.source_name,
               fc.c1body
    """
    params = []

    if args.query:
        sql = select + """
        FROM messages_fts f
        JOIN messages m ON f.rowid = m.rowid
        JOIN messages_fts_content fc ON fc.docid = m.rowid
        WHERE messages_fts MATCH ?
        """
        params.append(args.query)
        if args.from_addr:
            sql += " AND m.from_addr LIKE ?"
            params.append(f"%{args.from_addr}%")
        if args.since:
            sql += " AND m.date_sent >= ?"
            params.append(args.since)
    else:
        sql = select + """
        FROM messages m
        LEFT JOIN messages_fts_content fc ON fc.docid = m.rowid
        WHERE 1=1
        """
        if args.from_addr:
            sql += " AND m.from_addr LIKE ?"
            params.append(f"%{args.from_addr}%")
        if args.since:
            sql += " AND m.date_sent >= ?"
            params.append(args.since)

    sql += " ORDER BY m.date_sent DESC LIMIT ?"
    params.append(args.limit)
    return sql, params


def parse_addrs(raw):
    if not raw:
        return []
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else [str(result)]
    except (json.JSONDecodeError, TypeError):
        return [str(raw)]


def format_text(row, include_body):
    gmail_id, thread_id, subject, from_addr, to_addrs, cc_addrs, date_sent, source_name, body = row
    date = (date_sent or "")[:10]
    to_list = parse_addrs(to_addrs)
    to_str = ", ".join(to_list[:3])
    if len(to_list) > 3:
        to_str += f" (+{len(to_list) - 3} more)"
    lines = [
        f"[{date}] {subject or '(no subject)'}",
        f"  From: {from_addr} → {to_str}",
    ]
    if include_body and body:
        snippet = body.strip().replace("\n", " ")[:200]
        lines.append(f"  Body: {snippet}...")
    return "\n".join(lines)


def format_json_record(row, include_body):
    gmail_id, thread_id, subject, from_addr, to_addrs, cc_addrs, date_sent, source_name, body = row
    record = {
        "subject": subject,
        "from": from_addr,
        "to": parse_addrs(to_addrs),
        "cc": parse_addrs(cc_addrs),
        "date": date_sent,
        "gmail_id": gmail_id,
        "thread_id": thread_id,
        "source": source_name,
    }
    if include_body:
        record["body"] = body or ""
    return record


def main():
    args = parse_args()

    if not os.path.exists(args.db):
        print(f"Error: database not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    if not args.query and not args.from_addr and not args.since:
        print("Error: provide a query, --from, or --since filter", file=sys.stderr)
        sys.exit(1)

    db = sqlite3.connect(args.db)
    try:
        sql, params = build_query(args)
        rows = db.execute(sql, params).fetchall()
    except sqlite3.OperationalError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()

    if args.fmt == "json":
        output = {
            "query": args.query,
            "filters": {"from": args.from_addr, "since": args.since},
            "count": len(rows),
            "results": [format_json_record(r, args.body) for r in rows],
        }
        print(json.dumps(output, indent=2))
    else:
        if not rows:
            print("No results found.")
            return
        print(f"{len(rows)} result(s):\n")
        for row in rows:
            print(format_text(row, args.body))
            print()


if __name__ == "__main__":
    main()
