@AGENTS.md

## For Claude Code

* Changing the dashboard: use the `dashboard-dev` skill. Serving the queue (the **Queue worker** session): use the
  `dashboard-queue-worker` skill. Both are in `skills/`; run `./install-skills.sh` if they are not available.
* In the desktop app, the user usually follows your progress in a task list and finishes with `wrap_up`; keep replies short.
* The session titled **"My dashboard"** is where the dashboard was built; **"Queue worker"** is the cheap worker session and is
  hidden from the board. Do not rename them.
* Test with a copy: to try a UI change without touching the live data, serve a copy of `index.html` plus a saved
  `/api/state` JSON from another port (see the skill), then stop that server with `fuser -k <port>/tcp`.
