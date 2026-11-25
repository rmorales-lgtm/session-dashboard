#!/usr/bin/env python3
"""Compact work list for the Claude session that serves the dashboard queue. Silent when there is nothing to do.
   queue_todo.py          what the dashboard approved / asked (monitor events)
   queue_todo.py --all    also the entries the user has not approved (when the user says "process the queue")
Lines:
   PING <id>
   MOVE <id> <section_id>
   ARCHIVE <id> <session-string-for-archive_session>
Send the standard 'Something new?' text for PING; then run mark_many.py once with every id."""
import datetime, glob, json, os, sys
Q = os.environ.get("QUEUE_FILE", os.path.expanduser("~/.local/share/session-dashboard/move-queue.json"))
ALL = "--all" in sys.argv
APP = glob.glob("/mnt/c/Users/*/AppData/Roaming/Claude/claude-code-sessions/*/*")


def app_session(sid):
    for d in APP:
        p = f"{d}/{sid}.json"
        if os.path.exists(p):
            try:
                return json.load(open(p))
            except Exception:
                return None


def session_string(sid, title):
    d = app_session(sid) or {}
    src = {"tool": "title set by an agent", "auto": "auto-generated title"}.get(d.get("titleSource"))
    last = datetime.datetime.fromtimestamp((d.get("lastActivityAt") or 0) / 1000).strftime("%Y-%m-%d")
    cwd = d.get("cwd") or "~"
    return f'"{title}" ({src}), folder {cwd}, last active {last} ({sid})' if src else ""


try:
    q = json.load(open(Q))
except Exception:
    q = []
for x in q:
    act = x.get("action", "move")
    if act == "ping":
        if not x.get("sentAt"):
            print(f"PING {x['id']}")
    elif ALL or x.get("approved"):
        if act == "move":
            print(f"MOVE {x['id']} {x['toSection']}")
        elif act == "archive":
            t = (x.get("title") or "")
            print(f"ARCHIVE {x['id']} {session_string(x['id'], (app_session(x['id']) or {}).get('title') or t)}")
