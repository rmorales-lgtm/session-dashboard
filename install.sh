#!/usr/bin/env bash
# Install Session Control for the current user.
#   ./install.sh                 config + skills + systemd user service (starts it)
#   ./install.sh --no-service    config + skills only (run it yourself: python3 server.py)
#   ./install.sh --print-service print the service unit that would be installed, change nothing
# Safe to run again: it never overwrites an existing config.json or a different skill/service.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mode="${1:-}"
python="$(command -v python3 || true)"

render_service() { sed "s#@PYTHON@#${python}#g; s#@DIR@#${here}#g" "$here/session-dashboard.service.template"; }

if [ "$mode" = "--print-service" ]; then render_service; exit 0; fi

[ -n "$python" ] || { echo "python3 not found" >&2; exit 1; }
"$python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || { echo "Python 3.9 or newer is required" >&2; exit 1; }

# 1. config
if [ ! -f "$here/config.json" ]; then
  cp "$here/config.example.json" "$here/config.json"
  echo "created  config.json (edit it: your section names, skills, time zone, folders)"
else
  echo "ok       config.json already exists"
fi

# 2. is Claude Desktop's data visible?
app="$("$python" -c "import sys; sys.path.insert(0, '$here'); import dashcfg; print(dashcfg.find_app_dir() or '')")"
if [ -n "$app" ]; then echo "found    Claude Desktop data: $app"
else echo "WARNING  Claude Desktop data not found. Set \"appDataDir\" in config.json (folder with claude_desktop_config.json)." >&2; fi

# 3. skills (the queue worker and the dashboard developer)
"$here/install-skills.sh"

# 4. service
port="$("$python" -c "import sys; sys.path.insert(0, '$here'); import dashcfg; print(dashcfg.CFG['port'])")"
if [ "$mode" = "--no-service" ]; then
  echo "skipped  service. Run it with:  $python $here/server.py"
elif command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  unit="$HOME/.config/systemd/user/session-dashboard.service"
  mkdir -p "$(dirname "$unit")"
  if [ -f "$unit" ] && ! diff -q <(render_service) "$unit" >/dev/null; then
    echo "SKIPPED  service: $unit exists and differs (compare with: ./install.sh --print-service)" >&2
  else
    render_service > "$unit"
    systemctl --user daemon-reload
    systemctl --user enable --now session-dashboard.service
    echo "started  service session-dashboard"
  fi
else
  echo "no systemd user session: run it with  $python $here/server.py"
fi

echo
echo "Open http://localhost:${port}"
echo "Then click 'Start worker' in the header to run the queue worker (see README, section 5)."
