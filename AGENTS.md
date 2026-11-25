# AGENTS.md — Session Control dashboard

Local dashboard for Claude Desktop (Code tab) sessions: a kanban board, a "needs you" detector and a weekly timesheet view.
Read `README.md` for the full picture; this file is what an AI session must know before touching the code.

## Layout

* `server.py` — Python 3 standard library only. Reads the app's files, builds the state, serves `/api/*` and `index.html`.
* `index.html` — the whole UI in one file (CSS, JS, SVG icons). No build step, no external requests, no frameworks.
* `queue_todo.py`, `mark_many.py`, `ping_watch.py` (+ `mark_done.py`, `mark_sent.py`) — tools for the **Queue worker** session.
* `skills/` — `dashboard-queue-worker`, `dashboard-dev`; `install-skills.sh` symlinks them into `~/.claude/skills`.
* Config: environment variable `DASHBOARD_ADO_ORG` (set in the systemd unit, never in the repo) enables Azure DevOps links.
* Data: `~/.local/share/session-dashboard/history.json` and `move-queue.json` (outside the repo). Service:
  `~/.config/systemd/user/session-dashboard.service` (runs `python3 -I server.py 8787`).

## Commands

```bash
python3 -m py_compile server.py                     # syntax check the server
systemctl --user restart session-dashboard          # apply a change
systemctl --user status session-dashboard
python3 queue_todo.py [--all]                       # pending worker requests
```

Check the page script: extract `<script>…</script>` from `index.html` to a temp file and run `node --check` on it.
Look at the result with headless Chrome (`~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome --headless=new --no-sandbox
--screenshot=…`). The `dashboard-dev` skill has the full recipe.

## Rules

1. **Read-only on Claude's files.** Never edit `claude_desktop_config.json` or the app's `claude-code-sessions/*` files: the
   running app ignores or overwrites such edits. Changing a section, archiving and messaging a session go through the queue and a
   Claude session's tools (`move_sessions`, `archive_session`, `send_message`).
2. **Never hand-edit `history.json` or `move-queue.json`** while the service runs, except through the scripts or the API (the
   server rewrites them atomically). They are state, not configuration.
3. **Back up before a big edit** (copy `server.py` / `index.html` to the session scratchpad), validate (`py_compile`,
   `node --check`) and restart the service. A broken `server.py` takes the dashboard down.
4. **Do not use `pkill -f '<pattern>'`** or `pgrep` patterns that appear in your own command line (the shell kills itself). Use
   `fuser -k <port>/tcp` or a bracketed pattern like `[p]ing_watch.py`.
5. **POST endpoints** require `X-Dashboard: 1` and a `localhost` Host header, and the server binds `127.0.0.1` only. Keep it so.
6. **No new dependencies.** Python standard library and plain browser JS only; escape every string put into the page (`esc()`).
7. **Privacy (Loi 25).** Cards show session titles that contain ticket/PR numbers and work item titles. Do not add features that
   store or display personal data of clients, insureds or employees (names, plates, claim numbers…); use fictional examples in
   docs and tests. Never put tokens or secrets in this folder.
8. **Be frugal with tokens in the worker.** One listing call, one parallel batch, one silent marking call, one short reply.

## Concepts

* **Stage** of a session = the sidebar section it is filed under (`STAGE_ALIASES` in `server.py` maps names to keys:
  `review_others`, `analysis`, `po`, `dev`, `my_cr`, `completed`, `none`).
* **Needs you**: `tail_ask()` finds an unanswered question at the end of the last turn; **unread** = turn ended after the last
  focus. Both only for sessions that are idle/closed. **Muted** cards are excluded from To do and counters and wake up when a
  newer turn leaves a question or unread results.
* **Queue**: `move-queue.json` entries `{id, action: move|archive|ping, …}`. Pings are served without approval; moves/closes
  wait for **Do it** (`approved`) unless the dashboard created them itself (self-filing of sessions started with **+**).
* **pendingStarts** (`review:<PR>`, `implement:<ticket>`): what the user started with **+**, so the unfiled session can be
  filed under the right section when it appears (matching in `_start_match`).
* **Links** `claude://code/new?folder=…&q=…` only prefill a prompt; a leading `/` is neutralised by the app, so prompts are plain
  sentences ("Use the my-code-review skill…").

## When you change something

Update `README.md` (user-facing) and this file (rules/concepts) in the same change, and the skills if the worker procedure or the
development recipe changed.
