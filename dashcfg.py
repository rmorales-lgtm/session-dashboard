"""Shared configuration for the dashboard server and its worker tools (standard library only).

Settings come from, in increasing priority: the defaults below, `config.json` next to this file (or the file named in
$DASHBOARD_CONFIG), then a few environment variables (DASHBOARD_ADO_ORG, DASHBOARD_APP_DIR).
Keys starting with "_" in the JSON file are comments and ignored.
"""
import glob, json, os, sys

HOME = os.path.expanduser("~")
HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULTS = {
    "port": 8787,
    "timezone": "",                        # IANA name such as "America/Toronto"; empty = this computer's local time
    "projectsDir": "~/dev/projects",       # folder where sessions started with the + buttons open
    "adoOrg": "",                          # https://dev.azure.com/<organization>; empty = no Azure DevOps links
    "appDataDir": "",                      # Claude Desktop data folder; empty = auto-detect
    # sidebar section names per stage (case-insensitive); the first one is the label shown on the board
    "sections": {
        "review_others": ["Peer code reviews"],
        "analysis": ["Story analysis"],
        "po": ["PO sign-off"],
        "dev": ["Development"],
        "my_cr": ["My PRs in review"],
        "completed": ["Completed"],
    },
    # skills the + buttons ask Claude to use, and the sentence they prefill ({skill} {section} {n} are replaced)
    "skills": {"review": "my-code-review", "implement": "implement"},
    "startMessages": {
        "review": 'Use the {skill} skill to review PR {n} and place this session in the "{section}" section.',
        "implement": 'Use the {skill} skill for ticket {n} and place this session in the "{section}" section.',
    },
}


def load():
    cfg = json.loads(json.dumps(DEFAULTS))
    path = os.environ.get("DASHBOARD_CONFIG") or os.path.join(HERE, "config.json")
    user = {}
    try:
        with open(path) as f:
            user = json.load(f)
    except FileNotFoundError:
        pass
    except Exception as e:                                   # a typo must not take the dashboard down
        print(f"dashcfg: ignoring {path}: {e}", file=sys.stderr)
    for k, v in user.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    if os.environ.get("DASHBOARD_ADO_ORG"):
        cfg["adoOrg"] = os.environ["DASHBOARD_ADO_ORG"]
    if os.environ.get("DASHBOARD_APP_DIR"):
        cfg["appDataDir"] = os.environ["DASHBOARD_APP_DIR"]
    cfg["adoOrg"] = (cfg["adoOrg"] or "").rstrip("/")
    cfg["projectsDir"] = os.path.expanduser(cfg["projectsDir"])
    cfg["port"] = int(cfg["port"])
    return cfg


CFG = load()


def find_app_dir():
    """Claude Desktop's data folder (it holds claude_desktop_config.json and claude-code-sessions/)."""
    cands = []
    if CFG["appDataDir"]:
        cands.append(os.path.expanduser(CFG["appDataDir"]))
    cands += glob.glob("/mnt/c/Users/*/AppData/Roaming/Claude")          # Windows app, dashboard in WSL
    cands += [f"{HOME}/.config/Claude", f"{HOME}/Library/Application Support/Claude"]   # Linux, macOS
    for base in cands:
        if os.path.exists(f"{base}/claude_desktop_config.json"):
            return base
    return None


def pid_alive(pid):
    if not pid:
        return False
    if os.path.isdir("/proc"):
        return os.path.exists(f"/proc/{pid}")
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False
