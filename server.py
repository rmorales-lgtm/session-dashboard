#!/usr/bin/env python3
"""Local dashboard for Claude Desktop (Code tab) sessions. Read-only on Claude's files.

Run:  python3 server.py [port]      (default: "port" in config.json, 8787)

Sources (all local):
  * Desktop app session files + sidebar sections: <Windows>/AppData/Roaming/Claude (WSL path auto-detected)
  * Process status (busy/idle/waiting):            ~/.claude/sessions/*.json
  * Transcripts (activity timestamps, titles):     ~/.claude/projects/*/<cliSessionId>.jsonl
History is persisted in ~/.local/share/session-dashboard/history.json so a session deleted
in the app stays in the weekly view.
"""
import glob, json, os, re, sys, threading, time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # `python -I` does not add the script folder
from dashcfg import CFG, find_app_dir, pid_alive

HOME = os.path.expanduser("~")
TZ = ZoneInfo(CFG["timezone"]) if CFG["timezone"] else None      # None = this computer's local time
HIST_DIR = f"{HOME}/.local/share/session-dashboard"
HIST = f"{HIST_DIR}/history.json"
GAP_CAP = 15 * 60          # a gap between two transcript events counts up to 15 min
POLL = 60                  # seconds between background snapshots (catches section moves)
HERE = os.path.dirname(os.path.abspath(__file__))
LOCK = threading.Lock()

# Sidebar section name -> stage key. The names come from config.json ("sections"); the older names of the first
# version of the dashboard still work so that nothing breaks after a rename.
STAGE_ALIASES = {
    "cr": "review_others", "reviewing for others": "review_others",
    "in analysis": "analysis", "in po validation": "po", "in dev": "dev",
    "in cr": "my_cr", "my tickets in cr": "my_cr", "done": "completed",
}
for _key, _names in CFG["sections"].items():
    for _name in _names:
        STAGE_ALIASES[_name.strip().lower()] = _key
STAGE_ORDER = ["review_others", "analysis", "po", "dev", "my_cr"]
STAGE_LABEL = {k: (CFG["sections"].get(k) or [k])[0] for k in STAGE_ORDER + ["completed"]}
STAGE_LABEL["none"] = "No section"


APP = find_app_dir()


def jload(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def stage_key(name):
    return STAGE_ALIASES.get((name or "").strip().lower(), "none" if not name else "other:" + name)


def read_sections():
    """-> ({group_id: name}, {local_id: group_id})"""
    cfg = jload(f"{APP}/claude_desktop_config.json", {}) if APP else {}
    prefs = cfg.get("preferences", {}).get("epitaxyPrefs", {})
    groups, assign = {}, {}
    for scope in prefs.get("dframe-group-scopes", {}).values():
        for g in scope.get("groups", []):
            groups[g["id"]] = g["name"]
        for k, v in scope.get("assignments", {}).items():
            assign[k.split(":", 1)[-1]] = v
    return groups, assign


def read_app_sessions():
    out = {}
    if not APP:
        return out
    for f in glob.glob(f"{APP}/claude-code-sessions/*/*/local_*.json"):
        d = jload(f)
        if d and d.get("sessionId"):
            out[d["sessionId"]] = d
    return out


def read_proc_status():
    """hostSessionId -> {status, waitingFor} for live processes."""
    out = {}
    for f in glob.glob(f"{HOME}/.claude/sessions/*.json"):
        d = jload(f)
        if not d or not d.get("hostSessionId") or not pid_alive(d.get("pid")):
            continue
        out[d["hostSessionId"]] = {"status": d.get("status") or "idle", "waitingFor": d.get("waitingFor")}
    return out


def parse_ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


_tcache = {}   # path -> (mtime, size, result)


def scan_transcript(path):
    """-> {'daily': {date: minutes}, 'title': last custom title, 'first': ts, 'last': ts}"""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (st.st_mtime, st.st_size)
    c = _tcache.get(path)
    if c and c[0] == key:
        return c[1]
    ts, title = [], None
    with open(path, "rb") as f:
        for raw in f:
            if b'"timestamp"' in raw and (b'"type":"user"' in raw or b'"type":"assistant"' in raw):
                try:
                    t = parse_ts(json.loads(raw).get("timestamp", ""))
                except Exception:
                    t = None
                if t:
                    ts.append(t)
            elif b'"custom-title"' in raw:
                try:
                    title = json.loads(raw).get("customTitle") or title
                except Exception:
                    pass
    ts.sort()
    daily = {}
    for a, b in zip(ts, ts[1:]):
        secs = min(b - a, GAP_CAP)
        d = datetime.fromtimestamp(a, TZ).strftime("%Y-%m-%d")
        daily[d] = daily.get(d, 0) + secs
    res = {"daily": {d: round(s / 60, 1) for d, s in daily.items()}, "title": title,
           "first": ts[0] if ts else None, "last": ts[-1] if ts else None}
    _tcache[path] = (key, res)
    return res



_acache = {}   # transcript path -> ((mtime, size), result)


def _is_real_user(e):
    """A message typed by the human (not a tool result, a reminder or a notification)."""
    if e.get("type") != "user" or e.get("isMeta"):
        return False
    org = (e.get("origin") or {}).get("kind")
    if org and org != "human":
        return False
    c = (e.get("message") or {}).get("content")
    if isinstance(c, str):
        return not c.lstrip().startswith(("<system-reminder>", "<task-notification>", "<command-name>"))
    if isinstance(c, list):
        return any(isinstance(b, dict) and b.get("type") == "text" and not b.get("text", "").lstrip().startswith("<system-reminder>")
                   for b in c) and not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
    return False


def tail_ask(path):
    """What the session asks of the human at the end of its last turn: text of the question, or None.
    Looks at the last turn only: AskUserQuestion not answered, a wrap_up with an `ask`, or a closing message that ends with '?'."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (st.st_mtime, st.st_size)
    c = _acache.get(path)
    if c and c[0] == key:
        return c[1]
    with open(path, "rb") as f:
        f.seek(max(0, st.st_size - 400_000))
        data = f.read()
    entries = []
    for raw in data.split(b"\n")[1:] if st.st_size > 400_000 else data.split(b"\n"):
        if b'"type":"user"' in raw or b'"type":"assistant"' in raw:
            try:
                entries.append(json.loads(raw))
            except Exception:
                pass
    turn = []
    for e in reversed(entries):
        if _is_real_user(e):
            break
        turn.append(e)
    turn.reverse()
    uses, results, last_text, ask = {}, set(), "", None
    for e in turn:
        c_ = (e.get("message") or {}).get("content")
        if not isinstance(c_, list):
            continue
        for b in c_:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                uses[b.get("id")] = b
            elif b.get("type") == "tool_result":
                results.add(b.get("tool_use_id"))
            elif b.get("type") == "text" and e.get("type") == "assistant":
                last_text = b.get("text", "")
    for tid, b in uses.items():
        nm = b.get("name", "")
        inp = b.get("input") or {}
        if nm == "AskUserQuestion" and tid not in results:
            qs = inp.get("questions") or []
            ask = (qs[0].get("question") if qs and isinstance(qs[0], dict) else None) or "Question for you"
        elif nm.endswith("wrap_up") and inp.get("ask"):
            ask = str(inp["ask"])
    if not ask and turn:
        t = " ".join(last_text.split())
        if t.endswith("?"):
            ask = t[max(t.rfind(". ", 0, -2), t.rfind("! ", 0, -2)) + 2:] if len(t) > 140 else t
    if ask:
        ask = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", ask)          # [text](url) -> text
        ask = re.sub(r"[*_`]{1,3}", "", ask).replace("Next:", "").strip()
        ask = " ".join(ask.split())[:140]
    _acache[path] = (key, ask or None)
    return ask

def transcript_paths(uuid):
    return glob.glob(f"{HOME}/.claude/projects/*/{uuid}.jsonl")


# ---- work item extraction from titles -------------------------------------------------------
def classify(title):
    """-> (kind, workitem or None, pr or None)"""
    t = (title or "").strip()
    m = re.match(r"PR\s+(\d+)\s+#(\d+)", t, re.I)
    if m:
        return "review", m.group(2), m.group(1)
    m = re.match(r"PR\s+(\d+)\b", t, re.I)
    if m:
        return "review", None, m.group(1)
    m = re.match(r"(?:\[[^\]]+\]\s*)?(?:/?implement|/?refine|Ticket|US|U\.S\.|Bug)?\s*#?(\d{4,6})\b", t, re.I)
    if m:
        return "story", m.group(1), None
    m = re.search(r"#(\d{4,6})\b", t)
    if m:
        return "story", m.group(1), None
    return "other", None, None


# ---- history -----------------------------------------------------------------------------------
def load_history():
    return jload(HIST, {"sessions": {}})


def save_history(h):
    os.makedirs(HIST_DIR, exist_ok=True)
    tmp = HIST + ".tmp"
    with open(tmp, "w") as f:
        json.dump(h, f, indent=1)
    os.replace(tmp, HIST)


def _start_match(kind, n, t):
    """Does the title of a new session belong to the review of PR n / the implementation of ticket n?"""
    n = re.escape(n)
    sk = re.escape(CFG["skills"].get("review" if kind == "review" else "implement", ""))
    if kind == "review":
        return bool(re.match(rf"PR\s+{n}\b", t, re.I) or re.search(rf"{sk}\D{{0,40}}?\b{n}\b", t, re.I))
    return bool(re.match(rf"(?:\[[^\]]+\]\s*)?(?:/?{sk}\s+)?#?{n}\b", t, re.I)
                or re.search(rf"{sk}\D{{0,40}}?\b{n}\b", t, re.I))


def snapshot():
    """Merge the live state into the history and return (history, live_ids, proc, groups)."""
    now = time.time()
    groups, assign = read_sections()
    app = read_app_sessions()
    proc = read_proc_status()
    h = load_history()
    S = h["sessions"]
    known_uuids = set()

    for sid, d in app.items():
        title = d.get("title") or ""
        kind, wi, pr = classify(title)
        g = groups.get(assign.get(sid))
        stage = stage_key(g) if g else "none"
        r = S.setdefault(sid, {"id": sid, "firstSeen": now, "stages": [], "daily": {}})
        r.update(title=title, kind=kind, workItem=wi, pr=pr, cwd=d.get("cwd"),
                 createdAt=(d.get("createdAt") or 0) / 1000, lastActivity=(d.get("lastActivityAt") or 0) / 1000,
                 archived=bool(d.get("isArchived")), live=True, lastSeen=now, turns=d.get("completedTurns"))
        summ = d.get("postTurnSummary")
        if isinstance(summ, dict):
            summ = summ.get("summary") or summ.get("text") or json.dumps(summ)[:200]
        r["summary"] = (summ or r.get("summary") or "")[:300] if isinstance(summ, (str, type(None))) else r.get("summary", "")
        r["group"] = g
        if not r["stages"] or r["stages"][-1]["stage"] != stage:
            r["stages"].append({"stage": stage, "label": g or STAGE_LABEL["none"], "since": now})
        r["turnEdge"] = (d.get("lastTurnEdgeAt") or 0) / 1000
        r["focused"] = (d.get("lastFocusedAt") or 0) / 1000
        cur = d.get("cliSessionId")
        ps = transcript_paths(cur) if cur else []
        r["ask"] = tail_ask(max(ps, key=os.path.getmtime)) if ps else None
        uuids = [d.get("cliSessionId")] + list(d.get("priorRemoteCliSessionIds") or [])
        r["uuids"] = sorted(set(u for u in uuids if u) | set(r.get("uuids", [])))
        _merge_activity(r)
        known_uuids.update(r["uuids"])

    for sid, r in S.items():
        if sid not in app and r.get("live"):
            r["live"] = False           # deleted from the app: keep it
            r["deletedSeen"] = now
        known_uuids.update(r.get("uuids", []))

    _backfill_orphans(S, known_uuids)

    # sessions started from the dashboard's "+" buttons: file them under their section once they appear
    pend = h.setdefault("pendingStarts", {})
    old_rv = h.pop("pendingReviews", None)              # first version of the feature
    for n, ts in (old_rv or {}).items():
        pend.setdefault("review:" + n, ts)
    for k in [k for k, ts in pend.items() if now - ts > 7200]:
        del pend[k]
    if pend:
        gids = {}
        for g, name in groups.items():
            gids.setdefault(stage_key(name), g)
        for sid, r in S.items():
            if not r.get("live") or r.get("archived"):
                continue
            if (r["stages"][-1]["stage"] if r.get("stages") else "none") != "none":
                continue
            t = r.get("title") or ""
            for key in list(pend):
                kind, n = key.split(":", 1)
                target = "review_others" if kind == "review" else "dev"
                gid = gids.get(target)
                if not gid or not _start_match(kind, n, t):
                    continue
                q = read_queue()
                if not any(x["id"] == sid and x.get("action", "move") == "move" for x in q):
                    q.append({"id": sid, "action": "move", "title": t, "toSection": gid,
                              "label": "File under " + STAGE_LABEL[target], "fromStage": "none",
                              "requestedAt": now, "approved": now})
                    with open(QUEUE + ".tmp", "w") as f:
                        json.dump(q, f, indent=1)
                    os.replace(QUEUE + ".tmp", QUEUE)
                del pend[key]
                break
    h["updated"] = now
    save_history(h)
    return h, set(app), proc, groups


def _merge_activity(r):
    daily = {}
    last = r.get("lastActivity") or 0
    for u in r.get("uuids", []):
        for p in transcript_paths(u):
            s = scan_transcript(p)
            if not s:
                continue
            for d, m in s["daily"].items():
                daily[d] = daily.get(d, 0) + m
            if s["last"]:
                last = max(last, s["last"])
    if daily:
        # transcripts win; days no longer on disk are kept from the stored values
        merged = dict(r.get("daily", {}))
        merged.update({d: round(m, 1) for d, m in daily.items()})
        r["daily"] = merged
    r["lastActivity"] = max(r.get("lastActivity") or 0, last)


def _backfill_orphans(S, known_uuids):
    """Transcripts of sessions deleted from the app before the dashboard existed: recover title + time."""
    cutoff = time.time() - 45 * 86400
    for p in glob.glob(f"{HOME}/.claude/projects/*/*.jsonl"):
        u = os.path.basename(p)[:-6]
        if u in known_uuids or os.path.getmtime(p) < cutoff:
            continue
        s = scan_transcript(p)
        if not s or not s["daily"] or not s["title"]:
            continue
        kind, wi, pr = classify(s["title"])
        if kind == "other":
            continue        # only tickets/reviews matter for the timesheet
        sid = "orphan_" + u
        r = S.setdefault(sid, {"id": sid, "firstSeen": time.time(), "stages": [], "daily": {}})
        r.update(title=s["title"], kind=kind, workItem=wi, pr=pr, live=False, archived=False,
                 createdAt=s["first"], lastActivity=s["last"], group=None, uuids=[u], recovered=True)
        r["daily"] = s["daily"]


# ---- API payloads --------------------------------------------------------------------------------
def week_bounds(offset=0):
    today = datetime.now(TZ).date()
    mon = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    return mon, mon + timedelta(days=6)


ORG = CFG["adoOrg"]            # https://dev.azure.com/<organization>; empty = no Azure DevOps links


def item_url(r):
    if r.get("prUrl"):
        return r["prUrl"]
    if r.get("workItem") and ORG:
        return f"{ORG}/_workitems/edit/{r['workItem']}"
    return None


def resolve_prs():
    """Fill prUrl/prState from Azure DevOps (az) for review sessions; retried at most every 10 min."""
    import subprocess
    if not ORG:
        return
    h = load_history()
    changed = False
    for r in h["sessions"].values():
        pr = r.get("pr")
        if not pr or not r.get("live"):
            continue
        if r.get("prUrl") and r.get("prState") in ("completed", "abandoned"):
            continue
        if time.time() - r.get("prChecked", 0) < 600:
            continue
        r["prChecked"] = time.time()
        changed = True
        try:
            out = subprocess.run(["az", "repos", "pr", "show", "--id", pr, "--org", ORG, "-o", "json"],
                                 capture_output=True, text=True, timeout=40)
            d = json.loads(out.stdout)
            rp = d["repository"]
            from urllib.parse import quote
            r["prUrl"] = f"{ORG}/{quote(rp['project']['name'])}/_git/{quote(rp['name'])}/pullrequest/{pr}"
            r["prState"] = d.get("status")
        except Exception:
            pass
    if changed:
        with LOCK:
            h2 = load_history()
            for k, r in h["sessions"].items():
                if k in h2["sessions"]:
                    for f in ("prUrl", "prState", "prChecked"):
                        if f in r:
                            h2["sessions"][k][f] = r[f]
            save_history(h2)


WORKER_PROMPT = "Use the dashboard-queue-worker skill to serve the dashboard queue."


def worker_running():
    import subprocess
    try:
        return subprocess.run(["pgrep", "-f", "[p]ing_watch.py"], capture_output=True, timeout=3).returncode == 0
    except Exception:
        return False


def payload(offset=0):
    global QUEUED, ARCHIVING, PINGS
    with LOCK:
        h, live_ids, proc, groups = snapshot()
        q = read_queue()
        def pending(x):
            r = h["sessions"].get(x["id"])
            if not r or not r.get("live"):
                return False
            if x.get("action") == "ping":
                now_ = time.time()
                if x.get("sentAt"):
                    return now_ - x["sentAt"] < 1800
                return now_ - x["requestedAt"] < 7200
            if x.get("action") == "archive":
                return not r.get("archived")
            return r["stages"][-1]["stage"] == x.get("fromStage", "review_others")
        keep = [x for x in q if pending(x)]
        if len(keep) != len(q):
            with open(QUEUE + ".tmp", "w") as f:
                json.dump(keep, f, indent=1)
            os.replace(QUEUE + ".tmp", QUEUE)
        QUEUED = {x["id"] for x in keep if x.get("action", "move") == "move"}
        ARCHIVING = {x["id"] for x in keep if x.get("action") == "archive"}
        PINGS = {x["id"]: {"sent": bool(x.get("sentAt")), "at": x.get("sentAt") or x["requestedAt"]}
                 for x in keep if x.get("action") == "ping"}
    now = time.time()
    mon, sun = week_bounds(offset)
    days = [(mon + timedelta(days=i)).isoformat() for i in range(7)]

    muted_set = set(h.get("muted", {}))
    muted_base = {k: (m_.get("turnEdge") if isinstance(m_, dict) else m_) for k, m_ in h.get("muted", {}).items()}
    wake = []
    board = {k: [] for k in STAGE_ORDER + ["completed", "none"]}
    others = {}
    for sid, r in h["sessions"].items():
        if not r.get("live") or r.get("archived") or sid in ARCHIVING or (r.get("title") or "").strip().lower() == "queue worker":
            continue
        st = proc.get(sid, {})
        status = st.get("status", "closed")
        idle_ = status in ("idle", "closed")
        needs = None
        if idle_ and r.get("ask"):
            needs = "ask"
        elif idle_ and (r.get("turnEdge") or 0) > (r.get("focused") or 0) + 1:
            needs = "news"
        if sid in muted_set and needs and (r.get("turnEdge") or 0) > (muted_base.get(sid) or 0) + 1:
            muted_set.discard(sid)           # a newer turn ended with a question or unread results: unmute
            wake.append(sid)
        if needs == "ask":
            status, st = "waiting", {"status": "waiting", "waitingFor": r["ask"]}
        item = {"muted": sid in muted_set, "needs": needs, "unreadMin": round((now - (r.get("turnEdge") or now)) / 60), "id": sid, "title": r.get("title"), "workItem": r.get("workItem"), "pr": r.get("pr"),
                "kind": r.get("kind"), "status": status, "waitingFor": st.get("waitingFor"),
                "lastActivity": r.get("lastActivity"), "ageMin": round((now - (r.get("lastActivity") or now)) / 60),
                "queued": sid in QUEUED, "ping": ({"sent": PINGS[sid]["sent"], "agoMin": round((now - PINGS[sid]["at"]) / 60)} if sid in PINGS else None), "url": item_url(r), "prState": r.get("prState"), "open": "claude://claude.ai/epitaxy/" + sid, "stageSince": r["stages"][-1]["since"] if r.get("stages") else None,
                "minutesToday": r.get("daily", {}).get(datetime.now(TZ).strftime("%Y-%m-%d"), 0)}
        cur = r["stages"][-1]["stage"] if r.get("stages") else "none"
        if cur in board:
            board[cur].append(item)
        else:
            others.setdefault(r.get("group") or "Other", []).append(item)
    if wake:
        with LOCK:
            h2 = load_history()
            for s_ in wake:
                h2.get("muted", {}).pop(s_, None)
            save_history(h2)
    for lst in list(board.values()) + list(others.values()):
        lst.sort(key=lambda x: -(x["lastActivity"] or 0))

    # weekly: one row per work item (a review session of a PR is grouped under its work item)
    rows = {}
    for sid, r in h["sessions"].items():
        mins = {d: r.get("daily", {}).get(d, 0) for d in days}
        if not any(mins.values()):
            continue
        key = r.get("workItem") or ("PR " + r["pr"] if r.get("pr") else r.get("title") or sid)
        row = rows.setdefault(key, {"key": key, "workItem": r.get("workItem"), "title": r.get("title"), "url": item_url(r), "last": 0,
                                    "kinds": set(), "min": {d: 0 for d in days}, "stages": [], "sessions": [],
                                    "state": "deleted"})
        for d, m in mins.items():
            row["min"][d] += m
        row["kinds"].add(r.get("kind"))
        row["last"] = max(row["last"], r.get("lastActivity") or 0)
        row["url"] = row["url"] or item_url(r)
        row["sessions"].append({"id": sid, "title": r.get("title"), "live": bool(r.get("live")),
                                "recovered": bool(r.get("recovered"))})
        if r.get("live") and not r.get("archived") and sid not in ARCHIVING:
            row["state"] = "open"
        for s in r.get("stages", []):
            if not row["stages"] or row["stages"][-1] != s["label"]:
                row["stages"].append(s["label"])
        if r.get("kind") == "story" or not row["title"]:
            row["title"] = r.get("title")
    week = []
    for row in rows.values():
        row["kinds"] = sorted(k for k in row["kinds"] if k)
        row["total"] = round(sum(row["min"].values()), 1)
        row["min"] = {d: round(m, 1) for d, m in row["min"].items()}
        if row["total"] >= 1:
            week.append(row)
    week.sort(key=lambda r: -r["total"])
    done = sorted(({"key": r["key"], "workItem": r["workItem"], "title": r["title"], "url": r["url"],
                    "total": r["total"], "kinds": r["kinds"], "last": r["last"]}
                   for r in week if r["state"] == "deleted"), key=lambda x: -x["last"])
    totals = {d: round(sum(r["min"][d] for r in week), 1) for d in days}

    return {"now": now, "app": APP, "days": days, "week": week, "weekTotals": totals,
            "weekStart": mon.isoformat(), "weekEnd": sun.isoformat(), "offset": offset,
            "projectsDir": CFG["projectsDir"],
            "start": {k: {"skill": CFG["skills"][k], "template": CFG["startMessages"][k],
                          "section": STAGE_LABEL["review_others" if k == "review" else "dev"]} for k in ("review", "implement")}, "worker": worker_running(), "workerPrompt": WORKER_PROMPT, "homeDir": HOME, "pending": [{"action": x.get("action", "move"), "id": x["id"], "title": x.get("title"), "approved": bool(x.get("approved")), "error": x.get("error"), "label": x.get("label")} for x in read_queue() if x.get("action", "move") in ("move", "archive")], "board": board, "done": done, "others": others, "stageLabels": STAGE_LABEL, "stageOrder": STAGE_ORDER}


QUEUE = f"{HIST_DIR}/move-queue.json"
QUEUED = set()
PINGS = {}
PING_TEXT = ("Something new? Check what you wait on (PR comments and votes, new commits, builds, work item state) "
             "and tell me in one line, even if nothing changed.")
ARCHIVING = set()


def read_queue():
    return jload(QUEUE, [])


def complete_session(sid, action="move"):
    """Queue 'move to Completed' for a review session whose PR is merged.
    Claude Desktop only accepts section changes through its own tools (editing its config file
    is ignored by the running app), so a Claude session applies the queue (see README)."""
    with LOCK:
        h, live_ids, proc, groups = snapshot()
        r = h["sessions"].get(sid)
        if not r or not r.get("live"):
            return 404, "session not found"
        cur = r["stages"][-1]["stage"] if r.get("stages") else "none"
        if action == "ping":
            if r.get("archived"):
                return 409, "session is archived"
            q = [x for x in read_queue() if not (x["id"] == sid and x.get("action") == "ping")]   # a new click replaces the old ask
            q.append({"id": sid, "action": "ping", "title": r.get("title"), "requestedAt": time.time(),
                      "text": PING_TEXT})
            os.makedirs(HIST_DIR, exist_ok=True)
            with open(QUEUE + ".tmp", "w") as f:
                json.dump(q, f, indent=1)
            os.replace(QUEUE + ".tmp", QUEUE)
            return 200, "queued"
        if action == "archive":
            if cur != "completed" or r.get("archived"):
                return 409, "session is not in Completed"
        else:
            if cur != "review_others":
                return 409, "session is not in Reviewing for others"
            if r.get("prState") != "completed":
                return 409, "its PR is not merged"
        gid = next((g for g, n in groups.items() if n.strip().lower() == "completed"), None)
        if not gid:
            return 409, "no 'Completed' section in the sidebar"
        q = read_queue()
        if not any(x["id"] == sid and x.get("action", "move") == action for x in q):
            q.append({"id": sid, "action": action, "title": r.get("title"), "toSection": gid, "requestedAt": time.time()})
            os.makedirs(HIST_DIR, exist_ok=True)
            with open(QUEUE + ".tmp", "w") as f:
                json.dump(q, f, indent=1)
            os.replace(QUEUE + ".tmp", QUEUE)
    return 200, "queued"


def approve(sid, action):
    """The user clicked 'do it' on a queued move/archive: mark it approved for the Claude session that watches the queue."""
    if action not in ("move", "archive"):
        return 400, "bad action"
    with LOCK:
        q = read_queue()
        hit = False
        for x in q:
            if x["id"] == sid and x.get("action", "move") == action:
                x["approved"] = time.time()
                x.pop("error", None)
                hit = True
        if not hit:
            return 404, "no such queued request"
        with open(QUEUE + ".tmp", "w") as f:
            json.dump(q, f, indent=1)
        os.replace(QUEUE + ".tmp", QUEUE)
    return 200, "approved"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        path = self.path.partition("?")[0]
        if path not in ("/api/complete", "/api/archive", "/api/ping", "/api/apply", "/api/review", "/api/mute") or self.headers.get("X-Dashboard") != "1" \
                or self.headers.get("Host", "").split(":")[0] not in ("localhost", "127.0.0.1"):
            return self.send(403, json.dumps({"error": "forbidden"}), "application/json")
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n))
            if path == "/api/review":
                kind = body.get("kind", "review")
                num = str(body.get("n", body.get("pr", ""))).strip()
                if kind not in ("review", "implement") or not re.fullmatch(r"\d{1,7}", num):
                    return self.send(400, json.dumps({"ok": False, "message": "kind must be review/implement and the number digits"}), "application/json")
                with LOCK:
                    h = load_history()
                    h.setdefault("pendingStarts", {})[f"{kind}:{num}"] = time.time()
                    save_history(h)
                return self.send(200, json.dumps({"ok": True, "message": "registered"}), "application/json")
            sid = body["id"]
            if path == "/api/mute":
                with LOCK:
                    h = load_history()
                    mu = h.setdefault("muted", {})
                    if body.get("muted"):
                        r_ = h.get("sessions", {}).get(sid, {})
                        mu[sid] = {"at": time.time(), "turnEdge": r_.get("turnEdge") or time.time()}
                    else:
                        mu.pop(sid, None)
                    save_history(h)
                return self.send(200, json.dumps({"ok": True, "message": "saved"}), "application/json")
            if path == "/api/apply":
                code, msg = approve(sid, body.get("action", "move"))
                return self.send(code, json.dumps({"ok": code == 200, "message": msg}), "application/json")
            code, msg = complete_session(sid, {"/api/archive": "archive", "/api/ping": "ping"}.get(path, "move"))
        except Exception as e:
            code, msg = 500, repr(e)
        self.send(code, json.dumps({"ok": code == 200, "message": msg}), "application/json")

    def do_GET(self):
        path, _, qs = self.path.partition("?")
        if path in ("/", "/index.html"):
            return self.send(200, open(f"{HERE}/index.html", "rb").read(), "text/html; charset=utf-8")
        if path == "/api/state":
            m = re.search(r"week=(-?\d+)", qs)
            try:
                return self.send(200, json.dumps(payload(int(m.group(1)) if m else 0)), "application/json")
            except Exception as e:
                return self.send(500, json.dumps({"error": repr(e)}), "application/json")
        self.send(404, "not found", "text/plain")


def poller():
    while True:
        time.sleep(POLL)
        try:
            with LOCK:
                snapshot()
            resolve_prs()
        except Exception:
            pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else CFG["port"]
    if not APP:
        print("Claude Desktop data folder not found")
    threading.Thread(target=poller, daemon=True).start()
    threading.Thread(target=lambda: (resolve_prs()), daemon=True).start()
    print(f"Dashboard on http://localhost:{port}  (app data: {APP})")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
