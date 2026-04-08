#!/usr/bin/env python3
"""Extract deadline fields from JIRA issue JSON (stdin)."""
import json, sys

d = json.load(sys.stdin)
f = d["fields"]
target_end = f.get("customfield_12313942")
due_date = f.get("duedate")
if target_end or due_date:
    print(json.dumps({"key": d["key"], "target_end": target_end, "due_date": due_date}))
