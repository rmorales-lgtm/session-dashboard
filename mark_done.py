#!/usr/bin/env python3
"""mark_done.py ACTION SESSION_ID [error text]: after a queued move/archive was carried out, drop it;
with an error text, keep it, clear the approval and show the error in the sidebar."""
import json, os, sys
Q = os.path.expanduser("~/.local/share/session-dashboard/move-queue.json")
act, sid = sys.argv[1], sys.argv[2]; err = " ".join(sys.argv[3:])
out = []
for x in json.load(open(Q)):
    if x["id"] == sid and x.get("action", "move") == act:
        if not err: continue
        x.pop("approved", None); x["error"] = err[:120]
    out.append(x)
json.dump(out, open(Q + ".tmp", "w"), indent=1); os.replace(Q + ".tmp", Q)
