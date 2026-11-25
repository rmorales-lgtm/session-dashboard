#!/usr/bin/env python3
"""mark_sent.py SESSION_ID [error text]: marks the unsent ping of that session as sent (or drops it on error)."""
import json, os, sys, time
Q = os.path.expanduser("~/.local/share/session-dashboard/move-queue.json")
sid = sys.argv[1]; err = len(sys.argv) > 2
q = json.load(open(Q)); out = []
for x in q:
    if x["id"] == sid and x.get("action") == "ping" and not x.get("sentAt"):
        if err: continue
        x["sentAt"] = time.time()
    out.append(x)
json.dump(out, open(Q + ".tmp", "w"), indent=1); os.replace(Q + ".tmp", Q)
