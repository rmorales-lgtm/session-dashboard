#!/usr/bin/env python3
"""One line per burst of new work in the dashboard queue (a Claude session then runs queue_todo.py).
New = an unsent 'ping' or an approved move/archive not announced before. Clicks within 4 s arrive as one event."""
import json, os, time
Q = os.path.expanduser("~/.local/share/session-dashboard/move-queue.json")
seen = set()


def fresh():
    out = []
    try:
        for x in json.load(open(Q)):
            act = x.get("action", "move")
            if act == "ping" and not x.get("sentAt"):
                k = ("ping", x["id"], x["requestedAt"])
            elif act in ("move", "archive") and x.get("approved"):
                k = (act, x["id"], x["approved"])
            else:
                continue
            if k not in seen:
                out.append(k)
    except Exception:
        pass
    return out


while True:
    n = fresh()
    if n:
        time.sleep(4)                       # let a burst of clicks finish
        n = fresh()
        seen.update(n)
        print(f"QUEUE {len(n)} new: run ~/session-dashboard/queue_todo.py", flush=True)
    time.sleep(2)
