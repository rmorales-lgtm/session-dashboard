#!/usr/bin/env python3
"""mark_many.py KIND ID [ID...] [--err TEXT]   KIND = sent | move | archive   (silent)
sent: mark the pings sent. move/archive: drop the entries, or with --err keep them, clear the approval and show TEXT."""
import json, os, sys, time
Q = os.environ.get("QUEUE_FILE", os.path.expanduser("~/.local/share/session-dashboard/move-queue.json"))
a = sys.argv[1:]
kind = a[0]
err = None
if "--err" in a:
    i = a.index("--err"); err = " ".join(a[i + 1:])[:120]; a = a[:i]
ids = set(a[1:])
out = []
for x in json.load(open(Q)):
    act = x.get("action", "move")
    hit = x["id"] in ids and ((kind == "sent" and act == "ping" and not x.get("sentAt")) or (kind == act and kind != "sent"))
    if not hit:
        out.append(x)
    elif kind == "sent":
        x["sentAt"] = time.time(); out.append(x)
    elif err:
        x.pop("approved", None); x["error"] = err; out.append(x)
json.dump(out, open(Q + ".tmp", "w"), indent=1); os.replace(Q + ".tmp", Q)
