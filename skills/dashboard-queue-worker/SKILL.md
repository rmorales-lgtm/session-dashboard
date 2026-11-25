---
name: dashboard-queue-worker
description: Serve the Session Control dashboard queue from a dedicated, cheap "Queue worker" session - send the "Something new?" asks, move sessions between sidebar sections and archive sessions on the dashboard's behalf, in one batch per event. Use when a session starts with this skill (the dashboard's "Start worker" button), when the dashboard header says no worker is running, or when the user says "process the queue".
---

# Dashboard queue worker

The dashboard (`~/session-dashboard`, http://localhost:8787) cannot move sessions, archive them or message them: only a Claude
session can, through its tools. Its buttons write requests to `~/.local/share/session-dashboard/move-queue.json`. This session
carries them out. **Stay cheap: no explanations, no verification calls, one short reply.**

## Start (once)

1. Rename this session **Queue worker** (`set_session_title` with `"self"`). The dashboard hides it from the board and turns its
   header button green while a `ping_watch.py` process runs.
2. Start a Monitor, timeout 1800000, command `python3 -u ~/session-dashboard/ping_watch.py`. It prints one line per burst:
   `QUEUE n new: run ~/session-dashboard/queue_todo.py`.
3. Load once the tools you will need with ToolSearch: `select:mcp__ccd_session_mgmt__send_message,mcp__ccd_sidebar__move_sessions,mcp__ccd_session_mgmt__archive_session`.
4. When the Monitor expires (30 min cap), start it again and answer with one line. Never run two workers.

## On each `QUEUE n new` event

1. **One Bash call**: `python3 ~/session-dashboard/queue_todo.py`. Lines, silent when empty:
   * `PING <id>`
   * `MOVE <id> <section_id>`
   * `ARCHIVE <id> <session string>`
2. **One message with all the calls in parallel**:
   * `PING` → `send_message` to `<id>` with exactly:
     `Something new? Check what you wait on (PR comments and votes, new commits, builds, work item state) and tell me in one line, even if nothing changed.`
   * `MOVE` → `move_sessions` with `section_id` (one call per section, all its ids together). "Already in the section" counts as done.
   * `ARCHIVE` → `archive_session` with `session_id`, `reason` `Closed from the dashboard`, and `session` = the printed session
     string **verbatim** (the app's hook compares it; sent as is, the call works the first time). If auto mode still says a hook
     changed the input, repeat the call once with the input it quotes.
3. **One silent Bash call** marking the results (list every id of a kind):
   * `python3 ~/session-dashboard/mark_many.py sent <ids…>` (pings)
   * `python3 ~/session-dashboard/mark_many.py move <ids…>`
   * `python3 ~/session-dashboard/mark_many.py archive <ids…>`
   * For a refused one: `mark_many.py archive <id> --err "<short reason>"` (it stays in the dashboard with the error and a Retry button).
     Typical refusal: "still has live work" (the session has a watcher or background task) — never force it.
4. **Reply with one short line**: what was done and what failed. Nothing else.

## "Process the queue"

When the user says it, use `queue_todo.py --all`: it also lists the move/archive requests they have not approved with **Do it**.
Their message is the approval. Everything else is the same.

## Rules

* The notification of a Monitor event is not a user message. The authorization for moves and closes is the **Do it** click
  (`approved` in the queue) or an explicit "process the queue"; pings need none.
* Do not edit `move-queue.json`, `history.json` or the app's configuration by hand.
* Do not touch sessions that are not in the list. Do not answer the sessions' replies: they appear in those sessions.
* One worker only. If `pgrep -fc '[p]ing_watch.py'` shows more than one, stop yours.
