#!/usr/bin/env python3
"""
gh-console-gui — a local dashboard for your git repos.

Run:   python3 gh-console-gui.py
Then open: http://127.0.0.1:8471  (opens automatically)

Scans $REPOS_ROOT for git checkouts and gives you per-repo:
  branch, clean/dirty state, ahead/behind vs remote, last commit —
  plus one-click Pull, Push, Commit+Push, Status, Reveal in Finder,
  and Open on GitHub.

Localhost only. No dependencies beyond Python 3.

Env: GH_CONSOLE_REPOS — where your local clones live (default ~/repos)
     GH_CONSOLE_PORT  — port to listen on (default 8471)
"""

import http.server
import json
import os
import subprocess
import threading
import urllib.parse
import webbrowser

PORT = int(os.environ.get("GH_CONSOLE_PORT", "8471"))
REPOS_ROOT = os.path.expanduser(os.environ.get("GH_CONSOLE_REPOS", "~/repos"))


# ── git helpers ──────────────────────────────────────────────────────────────

def run(cmd, cwd=None, timeout=60):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as e:  # noqa: BLE001
        return 1, "", str(e)


def list_repos():
    repos = []
    if not os.path.isdir(REPOS_ROOT):
        return repos
    for entry in sorted(os.listdir(REPOS_ROOT)):
        path = os.path.join(REPOS_ROOT, entry)
        if os.path.isdir(os.path.join(path, ".git")):
            repos.append(path)
    return repos


def repo_info(path):
    name = os.path.basename(path)
    info = {"name": name, "path": path}

    rc, branch, _ = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    info["branch"] = branch if rc == 0 else "?"

    rc, porcelain, _ = run(["git", "status", "--porcelain"], cwd=path)
    info["dirty"] = bool(porcelain)
    info["changed_files"] = len(porcelain.splitlines()) if porcelain else 0

    ahead, behind = 0, 0
    rc, counts, _ = run(["git", "rev-list", "--left-right", "--count", "HEAD...@{u}"], cwd=path)
    if rc == 0 and counts:
        try:
            a, b = counts.split()
            ahead, behind = int(a), int(b)
        except ValueError:
            pass
    info["ahead"] = ahead
    info["behind"] = behind

    rc, log, _ = run(
        ["git", "log", "-1", "--format=%h|%s|%ar|%an"], cwd=path
    )
    if rc == 0 and log:
        h, s, when, who = (log.split("|") + ["", "", "", ""])[:4]
        info["last_commit"] = {"hash": h, "subject": s, "when": when, "author": who}
    else:
        info["last_commit"] = None

    rc, url, _ = run(["git", "config", "--get", "remote.origin.url"], cwd=path)
    info["remote_url"] = url if rc == 0 else ""
    return info


def do_action(repo_name, action, message=""):
    path = os.path.join(REPOS_ROOT, repo_name)
    if not os.path.isdir(os.path.join(path, ".git")):
        return False, f"Not a git repo: {repo_name}"

    if action == "pull":
        rc, out, err = run(["git", "pull", "--ff-only"], cwd=path, timeout=120)
    elif action == "push":
        rc, out, err = run(["git", "push"], cwd=path, timeout=120)
    elif action == "status":
        rc, out, err = run(["git", "status", "-sb"], cwd=path)
        _, diff, _ = run(["git", "diff", "--stat"], cwd=path)
        out = out + ("\n\n" + diff if diff else "")
        err = ""
    elif action == "commit":
        if not message.strip():
            return False, "Commit message is empty."
        run(["git", "add", "-A"], cwd=path)
        rc, out, err = run(["git", "commit", "-m", message.strip()], cwd=path)
        if rc != 0:
            return False, err or out or "Commit failed."
        rc2, out2, err2 = run(["git", "push"], cwd=path, timeout=120)
        out = out + "\n" + out2
        err = err2
        rc = rc2
    elif action == "reveal":
        rc, out, err = run(["open", path])
    elif action == "github":
        _, url, _ = run(["git", "config", "--get", "remote.origin.url"], cwd=path)
        web_url = url
        if web_url.endswith(".git"):
            web_url = web_url[:-4]
        if web_url.startswith("git@github.com:"):
            web_url = "https://github.com/" + web_url[len("git@github.com:"):]
        rc, out, err = run(["open", web_url])
    else:
        return False, f"Unknown action: {action}"

    ok = rc == 0
    detail = (err or out or "done").strip()
    return ok, detail[:2000]


# ── http server ──────────────────────────────────────────────────────────────

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>gh-console · local repos</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, "SF Pro Text", Inter, sans-serif;
         background: #0d1117; color: #e6edf3; padding: 28px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .sub { color: #8b949e; font-size: 13px; margin-bottom: 20px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 16px; }
  .card h2 { font-size: 16px; margin: 0 0 8px; font-family: ui-monospace, monospace; }
  .meta { font-size: 12.5px; color: #8b949e; line-height: 1.7; }
  .meta b { color: #e6edf3; font-weight: 600; }
  .pill { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 20px;
          margin-right: 6px; font-weight: 600; }
  .clean { background: #1a4d2e; color: #7ee2a8; }
  .dirty { background: #5a3a12; color: #f0b35e; }
  .syncbad { background: #5a1f1f; color: #f08a8a; }
  .syncok { background: #1c2f4d; color: #8ab8f0; }
  .commit { margin-top: 10px; font-size: 12px; color: #8b949e; border-top: 1px solid #30363d;
            padding-top: 10px; font-family: ui-monospace, monospace; }
  .commit .hash { color: #d2a8ff; }
  .btns { margin-top: 12px; display: flex; flex-wrap: wrap; gap: 8px; }
  button { background: #21262d; color: #e6edf3; border: 1px solid #30363d; border-radius: 6px;
           padding: 6px 12px; font-size: 12.5px; cursor: pointer; }
  button:hover { background: #30363d; }
  button.primary { background: #1f6feb; border-color: #1f6feb; }
  button.primary:hover { background: #2f81f7; }
  button:disabled { opacity: .45; cursor: default; }
  .log { margin-top: 12px; background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
         padding: 10px; font-family: ui-monospace, monospace; font-size: 11.5px;
         white-space: pre-wrap; max-height: 220px; overflow: auto; display: none; }
  .log.show { display: block; }
  .ok { color: #7ee2a8; } .err { color: #f08a8a; }
  .empty { color: #8b949e; text-align: center; margin-top: 60px; }
  .topbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
  .refresh { font-size: 12px; }
  dialog { background: #161b22; color: #e6edf3; border: 1px solid #30363d; border-radius: 10px;
           padding: 20px; width: 380px; }
  dialog input { width: 100%; padding: 8px; margin: 10px 0; background: #0d1117;
                 border: 1px solid #30363d; border-radius: 6px; color: #e6edf3; }
  dialog .row { display: flex; gap: 8px; justify-content: flex-end; }
</style>
</head>
<body>
<div class="topbar">
  <h1>gh-console</h1>
  <button class="refresh" onclick="load()">Refresh</button>
</div>
<div class="sub">Local repos in <span style="font-family:ui-monospace,monospace">~/repos</span> · localhost only</div>
<div id="grid" class="grid"></div>
<div id="empty" class="empty" style="display:none">
  No git repos found in ~/repos yet.<br>Clone one with <b>./gh-console.sh</b> first.
</div>

<dialog id="commitDlg">
  <b id="commitTitle">Commit</b>
  <input id="commitMsg" placeholder="Commit message…">
  <div class="row">
    <button onclick="dlg.close()">Cancel</button>
    <button class="primary" id="commitGo">Commit &amp; push</button>
  </div>
</dialog>

<script>
const grid = document.getElementById('grid');
const empty = document.getElementById('empty');
const dlg = document.getElementById('commitDlg');
let commitRepo = null;

async function load() {
  const r = await fetch('/api/repos');
  const repos = await r.json();
  grid.innerHTML = '';
  empty.style.display = repos.length ? 'none' : 'block';
  repos.forEach(card);
}

function pill(txt, cls) { return `<span class="pill ${cls}">${txt}</span>`; }

function card(info) {
  const el = document.createElement('div');
  el.className = 'card';
  const sync = (info.ahead || info.behind)
    ? pill(`↑${info.ahead} ↓${info.behind}`, 'syncbad')
    : pill('in sync', 'syncok');
  const state = info.dirty
    ? pill(`${info.changed_files} changed`, 'dirty')
    : pill('clean', 'clean');
  const lc = info.last_commit
    ? `<div class="commit"><span class="hash">${info.last_commit.hash}</span> ${esc(info.last_commit.subject)}<br>${esc(info.last_commit.when)} · ${esc(info.last_commit.author)}</div>`
    : '';
  el.innerHTML = `
    <h2>${esc(info.name)}</h2>
    <div class="meta">branch <b>${esc(info.branch)}</b><br>${state} ${sync}</div>
    ${lc}
    <div class="btns">
      <button onclick="act('${esc(info.name)}','pull',this)">Pull</button>
      <button onclick="act('${esc(info.name)}','push',this)">Push</button>
      <button class="primary" onclick="openCommit('${esc(info.name)}')">Commit+Push</button>
      <button onclick="act('${esc(info.name)}','status',this)">Status</button>
      <button onclick="act('${esc(info.name)}','reveal',this)">Finder</button>
      <button onclick="act('${esc(info.name)}','github',this)">GitHub</button>
    </div>
    <div class="log"></div>`;
  grid.appendChild(el);
}

function esc(s) { return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

async function act(repo, action, btn) {
  const log = btn.closest('.card').querySelector('.log');
  btn.disabled = true;
  log.classList.add('show');
  log.innerHTML = `<span style="color:#8b949e">running ${action}…</span>`;
  try {
    const r = await fetch('/api/action', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({repo, action})
    });
    const j = await r.json();
    log.innerHTML = `<span class="${j.ok ? 'ok' : 'err'}">${j.ok ? '✓' : '✗'} ${esc(action)}</span>\n${esc(j.detail)}`;
    if (j.ok && (action === 'pull' || action === 'push' || action === 'commit')) load();
  } catch (e) {
    log.innerHTML = `<span class="err">✗ ${esc(String(e))}</span>`;
  }
  btn.disabled = false;
}

function openCommit(repo) {
  commitRepo = repo;
  document.getElementById('commitTitle').textContent = `Commit — ${repo}`;
  document.getElementById('commitMsg').value = '';
  dlg.showModal();
  document.getElementById('commitMsg').focus();
}

document.getElementById('commitGo').onclick = async () => {
  const msg = document.getElementById('commitMsg').value;
  dlg.close();
  if (!msg.trim()) return;
  const r = await fetch('/api/action', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({repo: commitRepo, action: 'commit', message: msg})
  });
  const j = await r.json();
  alert((j.ok ? '✓ ' : '✗ ') + j.detail);
  load();
};

load();
setInterval(load, 30000);
</script>
</body>
</html>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the console clean
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            page = PAGE.replace("~/repos", REPOS_ROOT)
            body = page.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/repos":
            try:
                self._json([repo_info(p) for p in list_repos()])
            except Exception as e:  # noqa: BLE001
                self._json({"error": str(e)}, 500)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/api/action":
            return self.send_error(404)
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except Exception:  # noqa: BLE001
            return self._json({"ok": False, "detail": "Bad JSON"}, 400)
        repo = data.get("repo", "")
        action = data.get("action", "")
        message = data.get("message", "")
        # basic safety: repo names are single path components
        if not repo or "/" in repo or repo.startswith("."):
            return self._json({"ok": False, "detail": "Bad repo name"}, 400)
        ok, detail = do_action(repo, action, message)
        self._json({"ok": ok, "detail": detail})


def main():
    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"\n  gh-console-gui → {url}")
    print(f"  watching: {REPOS_ROOT}   (Ctrl-C to stop)\n")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Bye.")


if __name__ == "__main__":
    main()
