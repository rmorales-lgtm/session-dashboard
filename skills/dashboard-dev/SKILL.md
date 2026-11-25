---
name: dashboard-dev
description: Change, debug or extend the Session Control dashboard (~/session-dashboard: server.py, index.html, the worker scripts) - back up, edit, validate, restart the service, test with fake data and a headless screenshot. Use when the user asks to change the dashboard, add a card/button/section, fix the needs-you detection, or when the dashboard misbehaves.
---

# Developing the dashboard

Read `~/session-dashboard/AGENTS.md` first (rules and concepts). This is the recipe.

## Edit loop

1. **Back up** the file you will change to the session scratchpad (`cp server.py <scratchpad>/server.before-<what>.py`).
2. **Edit** with small, exact replacements. For `index.html` keep everything in the one file; escape every inserted string with `esc()`.
3. **Validate**
   * `python3 -m py_compile ~/session-dashboard/server.py`
   * extract the script and check it: `python3 -c "import re;s=open('index.html').read();open('<scratchpad>/p.js','w').write(re.search(r'<script>(.*)</script>',s,re.S).group(1))" && node --check <scratchpad>/p.js`
4. **Apply**: `systemctl --user restart session-dashboard`, then wait until `curl -s localhost:8787/api/state` answers.
5. **Look**: headless screenshot, then Read the PNG:
   `~/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome --headless=new --no-sandbox --disable-gpu --window-size=1700,700 --virtual-time-budget=4000 --screenshot=<scratchpad>/shot.png http://localhost:8787/`
   (adjust the `chromium-*` folder if it changed; `--dump-dom | grep -o '<title>…'` reads the tab title).

## Testing without touching live data

* **UI states**: save `curl -s localhost:8787/api/state > state.json`, edit it (set some `status`, `needs`, `muted`…), copy
  `index.html` into a scratch folder replacing `fetch('/api/state?week='+week)` with `fetch('/state.json')`, serve the folder
  with `python3 -m http.server 8788 --bind 127.0.0.1`, screenshot `http://127.0.0.1:8788/<copy>.html`, then
  `fuser -k 8788/tcp`. To force a theme set `let theme='dark'` in the copy.
* **Server logic** (snapshot, filing rules): import `server.py` with `importlib`, point `HIST_DIR`, `HIST`, `QUEUE` at a temp
  folder, monkeypatch `read_app_sessions`, `read_sections`, `read_proc_status`, `_backfill_orphans`, call `snapshot()` and
  inspect the queue file. Run it with `python3 -I`.
* **API**: `curl -s -X POST -H 'X-Dashboard: 1' localhost:8787/api/<endpoint> -d '{…}'`. A POST without the header must return 403.
  A test that queues a real request (archive, move) changes the user's data: undo it (`mark_many.py … `) and say so.
* **Worker scripts**: set `QUEUE_FILE=<temp>.json` to run `queue_todo.py` / `mark_many.py` against a fake queue.

## Where things are in `server.py`

`read_sections` / `read_app_sessions` / `read_proc_status` (inputs) → `snapshot()` (history merge, needs-you inputs, self-filing
of started sessions) → `payload()` (board, week, pending, flags) → `H` (HTTP). The needs-you detection is `tail_ask()`;
timesheet minutes come from `scan_transcript()`; PR links from `resolve_prs()` (uses `az`, every 10 min).

## Pitfalls we already hit

* A broken `server.py` takes the whole dashboard down: validate before restarting.
* `pkill -f "<text in your own command>"` kills your shell. Use `fuser -k <port>/tcp` or `[b]racketed` patterns.
* `cmd.exe /c start "<url with &>"` splits the link at `&`; open `claude://` links from the browser (an `<a>` click).
* Claude Desktop turns a leading `/` in a link prompt into `／`: write prompts as plain sentences.
* CSS inserted at the first `.empty{` once landed inside another rule: append new CSS before `</style>` instead.
* Keep the Write/Edit tools' "read first" rule in mind: open the file with Read before overwriting it.

## Finish

Update `README.md` / `AGENTS.md` (and the skills) in the same change, then tell the user what changed in two or three lines.
