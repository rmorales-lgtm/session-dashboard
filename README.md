# Session Control — a local dashboard for Claude Desktop sessions

A web page that shows every Claude Desktop (Code tab) session as a card on a small kanban board, tells you which ones need
you (a question to answer, unread results), and keeps a weekly record of the User Stories you worked on for your timesheet.

* Page: **http://localhost:8787** (the server only listens on `127.0.0.1`)
* Code: this folder, `~/session-dashboard` (WSL Ubuntu; from Windows: `\\wsl.localhost\Ubuntu\home\<you>\session-dashboard`)
* It is **not** in a git repository yet.

## 1. Quick start

The server is a systemd user service that starts with WSL, so normally there is nothing to do: open the page.

```bash
systemctl --user status session-dashboard      # is it running?
systemctl --user restart session-dashboard     # after changing server.py or index.html
journalctl --user -u session-dashboard -n 30   # its log
```

Run it by hand (for debugging): `python3 server.py [port]` (default 8787).

Skills (used by the worker sessions, see section 5): run `./install-skills.sh` once.

## 2. The board

| Section (Claude Desktop sidebar name) | Purpose |
|---|---|
| **Peer code reviews** (strip on top) | PRs you review for others |
| **Story analysis** | User Stories you are analysing |
| **PO sign-off** | Definitions waiting for the Product Owner |
| **Development** | Stories you are implementing |
| **My PRs in review** | Your own PRs waiting for code review |
| **Completed** | Done; close the session from here |

The dashboard reads the section of each session from the app, so you organise sessions in the sidebar as before. The old
names (`CR`, `In analysis`, `In PO validation`, `In dev`, `In CR`, `Reviewing for others`, `My tickets in CR`) still map to the
same stages.

### What a card tells you

* **Avatar and bubble**: the mood of the session (smile = fresh, bell = waiting for you, alert = waiting too long, mail =
  unread results, spinner = working, moon / snowflake = idle for hours / a day, power = not open, trophy = PR merged).
* **Badge**: `Needs you`, `New`, `Working`, `Idle`, `Not open`, `Merged`, `Muted`.
* **Age dot**: green under 30 min since the last activity, yellow under 4 h, red older.
* **Number**: links to the PR (reviews) or to the work item in Azure DevOps.
* **Action row** (icons only, under a thin line): open the session in Claude Desktop, refresh ("Something new?"), mute.

### When a session "needs you"

The detection reads the end of the session's last turn in its transcript:

1. **Question**: an unanswered `AskUserQuestion`, a `wrap_up` with an `ask`, or a closing message ending with `?` → badge `Needs you`.
2. **Unread results**: the session finished a turn after you last focused it (`lastTurnEdgeAt > lastFocusedAt` in the app's
   session file) → badge `New`, blue glowing card.
3. The process status (`busy`, `idle`, `waiting`) from `~/.claude/sessions/*.json`.

Mute (bell icon) hides a card from To do, counters, title and icon. A muted card **unmutes itself** when its session finishes a
newer turn that leaves a question or unread results.

### To do panel (right) and header

* **To do** lists only things that need an action: questions for you, unread results, merged reviews to move to Completed,
  completed sessions to close, and requests waiting for the worker (**Waiting for Claude**, with a **Do it** button).
* The header counters, the tab title (`● #12345 needs you (5 min) | Session Control`) and the page icon badge follow the same rules.
* **Worker** button: green = a queue worker session is running, orange = none (click to start one).
* Theme button: System → Light → Dark. Animations switch for calm days.

### Starting work from the board

* **+ in Peer code reviews**: asks for a PR number, opens a new session in `~/dev/projects` with
  *"Use the my-code-review skill to review PR N and place this session in the "Peer code reviews" section."*
* **+ in Development**: asks for a ticket number, opens a session with
  *"Use the implement skill for ticket N and place this session in the "Development" section."*
* The link only **prefills** the prompt: press Enter in the new session. (Claude Desktop turns a leading `/` in a link prompt
  into a look-alike character on purpose, so the dashboard asks in plain words instead of typing a slash command.)
* The session files itself; as a backup the server queues the move once a matching unfiled session appears (within 2 h).

### Week / timesheet tab

One row per User Story or PR with the active minutes per day (gaps between transcript events count up to 15 min), the sections
it went through and whether it is still open. Closed or deleted sessions stay (kept in `history.json`; transcripts of sessions
deleted before the dashboard existed are recovered for the last 45 days). "Copy summary" puts the week on the clipboard.

## 3. How it works

```
 Claude Desktop (Windows)                 WSL
 ├─ claude_desktop_config.json  ──┐
 ├─ claude-code-sessions/*.json ──┼──►  server.py ──► index.html (browser, polls /api/state every 10 s)
 ~/.claude/sessions/*.json (status)┤        │  ▲
 ~/.claude/projects/*/*.jsonl (transcripts)┘ │  │ POST /api/ping|archive|complete|apply|review|mute
                                              ▼  │
                         ~/.local/share/session-dashboard/{history,move-queue}.json
                                              │
                          ping_watch.py ◄─────┘   (watched by the Queue worker session)
                                              ▼
                  Queue worker (a Claude session) ── MCP tools ──► Claude Desktop
                  send_message · move_sessions · archive_session
```

The dashboard only **reads** Claude's files. Anything that changes the app — moving a session to another section, archiving,
sending a message to a session — can only be done by a Claude session through its tools (editing `claude_desktop_config.json`
while the app runs is ignored and gets overwritten). So the buttons write a request into the **queue** and a **Queue worker**
session carries it out.

## 4. Files

| Path | What |
|---|---|
| `server.py` | Server: reads sessions, builds the board, needs-you detection, queue, API (Python 3 standard library only) |
| `index.html` | The whole UI (HTML, CSS, JS, icons; no build step, no external requests) |
| `queue_todo.py` | Worker tool: prints the pending work, one compact line each |
| `mark_many.py` | Worker tool: marks requests sent / done (or failed) in one silent call |
| `ping_watch.py` | Worker tool: prints one line per burst of new requests (run it in a Monitor) |
| `mark_done.py`, `mark_sent.py` | Older single-request helpers (still work) |
| `skills/` | `dashboard-queue-worker`, `dashboard-dev` (installed by `install-skills.sh`) |
| `AGENTS.md`, `CLAUDE.md` | Instructions for AI sessions working here |
| `~/.config/systemd/user/session-dashboard.service` | Runs `python3 -I server.py 8787` |
| `~/.local/share/session-dashboard/history.json` | Sessions seen (title, stages, daily minutes, PR links), `muted`, `pendingStarts` |
| `~/.local/share/session-dashboard/move-queue.json` | Requests for the worker |

## 5. Running the workers

There are three things that "run": the server, the **Queue worker** session, and the sessions you start with **+**.

### 5.1 The dashboard server

Already a service (see section 1). Port 8787 is hard-coded in `server.py` and in the service file.

### 5.2 The Queue worker (needed for Refresh, Do it, moves and closes)

**Start it**
1. Click the orange **Start worker** button in the dashboard header (or run the command below).
2. A new session composer opens in your home folder with *"Use the dashboard-queue-worker skill to serve the dashboard queue."* Press **Enter**.
3. The session renames itself **Queue worker** and starts a Monitor on `ping_watch.py`. The header turns green.

By hand, from any Claude Code session: ask it *"Use the dashboard-queue-worker skill to serve the dashboard queue."*

**Keep it cheap**
* Use a small model for it (Haiku or Sonnet) and leave it alone; it replies with one line per batch.
* A Monitor lasts at most 30 minutes; the worker re-arms it with a one-line reply. If it stops, the header turns orange.
* Only one worker at a time (two would send each message twice).
* The dashboard hides the session titled "Queue worker" from the board.

**What it does** (skill `dashboard-queue-worker`)
1. Event `QUEUE n new` → run `python3 ~/session-dashboard/queue_todo.py` (one compact line per request).
2. One message with all calls in parallel: `PING` → `send_message` "Something new?…", `MOVE` → `move_sessions`,
   `ARCHIVE` → `archive_session` (using the printed session string verbatim).
3. One silent command: `mark_many.py sent|move|archive <ids>` (`--err "<reason>"` for refused ones).
4. One short reply.

**Process by hand** (no worker): `python3 queue_todo.py --all` lists everything, including requests you have not approved
with **Do it**. Say "process the queue" to a worker session to have it use `--all`.

**Stop it**: archive the Queue worker session (or stop its Monitor). The header turns orange.

### 5.3 Sessions started with + (review / implement)

They are normal Claude sessions. After pressing **+**: Enter in the new composer; the session runs the skill and moves itself
to its section. If it does not, the worker files it (a `MOVE` request, label "File under …"). Requests the dashboard does not
see a session for are dropped after 2 hours.

### 5.4 Troubleshooting

| Symptom | Check |
|---|---|
| Page does not load | `systemctl --user status session-dashboard`; port 8787 free? (`ss -ltnp | grep 8787`) |
| Header is orange / clicks stay "Asking…" | No worker: click **Start worker**. `pgrep -af ping_watch.py` should show one process |
| A click produced no event | `python3 queue_todo.py --all`; look at `move-queue.json`; the worker's Monitor may have expired |
| Archive refused "live work" | The session has a running watcher or background task; stop it or archive from the app sidebar |
| `+` opens nothing | The browser must be allowed to open `claude://` links; the registered handler is the app in `C:\ProgramData\<user>\AnthropicClaude`. From WSL, `cmd.exe /c start` breaks on `&` in the link: use the browser |
| Card shows the wrong section | The sidebar section changed: reload; names are matched by `STAGE_ALIASES` in `server.py` |
| Needs-you looks wrong | Detection is a heuristic (`tail_ask` in `server.py`); a closing message ending with `?` counts as a question |

## 6. API (localhost only)

`GET /api/state?week=N` → everything the page shows (`board`, `done`, `pending`, `week`, `worker`, …).
`POST` endpoints need the header `X-Dashboard: 1` and a `localhost` Host; body is JSON:

| Endpoint | Body | Effect |
|---|---|---|
| `/api/ping` | `{id}` | Queue a "Something new?" for that session |
| `/api/complete` | `{id}` | Queue "move to Completed" (review whose PR is merged) |
| `/api/archive` | `{id}` | Queue "close session" (session in Completed) |
| `/api/apply` | `{id, action}` | Approve a queued move/archive (the **Do it** button) |
| `/api/review` | `{kind: review\|implement, n}` | Remember a session you are starting so it is filed when it appears |
| `/api/mute` | `{id, muted}` | Mute / unmute a card |

Queue entry (`move-queue.json`): `{id, action: move|archive|ping, title, requestedAt, approved?, sentAt?, toSection?, label?, fromStage?, error?}`.

## 7. Settings worth knowing (top of `server.py`)

**Azure DevOps links** (optional): set `DASHBOARD_ADO_ORG=https://dev.azure.com/<organization>` in the environment of the service
(`Environment=` line in `~/.config/systemd/user/session-dashboard.service`, then `systemctl --user daemon-reload && systemctl --user restart session-dashboard`).
It turns work-item numbers into links and resolves the PR of each review session with the `az` CLI. Without it the dashboard works the same but those numbers are plain text.

`TZ` (America/Toronto), `GAP_CAP` (15 min of activity per gap), `POLL` (60 s background snapshot), `STAGE_ALIASES` / `STAGE_LABEL`
(section names), `WORKER_PROMPT`, the port in `__main__`. Thresholds for moods and the age dot are in `index.html`.

## 8. Developing

See `AGENTS.md` and the `dashboard-dev` skill: back up before editing, `python3 -m py_compile server.py`, check the page script
with `node --check`, restart the service, look at a headless screenshot.

## 9. Known limits

* Nothing is sent to a session unless the worker session is running (the Claude-only tools).
* The `claude://code/new` link only prefills the prompt; you press Enter.
* The needs-you detection is a heuristic; the "unread" signal depends on the app updating `lastFocusedAt`.
* Not under version control; the data folder is not backed up.
