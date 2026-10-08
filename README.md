# gh-console

GitHub without the tab-switching. Two small, dependency-free tools for everyday repo work — pick your flavor:

- **`gh-console.sh`** — an interactive terminal helper (login, repo picker, status/pull/push, quick commit, branches, PRs, issues, stash, one-click deploys)
- **`gh-console-gui.py`** — a local browser dashboard showing all your repos at a glance, with one-click Pull / Push / Commit+Push / Status

No frameworks, no build step, no accounts. Just `gh` and Python 3.

![MIT](https://img.shields.io/badge/license-MIT-green)

## Quick start

**1. Install the GitHub CLI** (the only dependency):

```bash
brew install gh
```

**2. Grab the tools** — clone this repo or download `gh-console.sh` and `gh-console-gui.py`.

**3a. Terminal version:**

```bash
chmod +x gh-console.sh
./gh-console.sh
```

On first run it checks your GitHub login (and walks you through `gh auth login` if needed), then lets you pick a repo. Your choice is remembered next time.

```
  ══ gam-gee/luxelive ══════════════════════
  1) Status              8) Create pull request
  2) Pull latest         9) List pull requests
  3) Quick commit+push  10) Issues
  4) Push               11) Stash
  5) Branch             12) Deploy (repo script)
  6) Recent commits     13) Open in browser
                        14) Local path
                        15) Switch repository
                        16) Quit
```

**3b. GUI version:**

```bash
python3 gh-console-gui.py
```

Opens `http://127.0.0.1:8471` automatically. Each repo gets a card with its branch, clean/dirty state, ahead/behind counts, and last commit — plus buttons for Pull, Push, Commit+Push, Status, Reveal in Finder, and Open on GitHub. Cards refresh every 30 seconds.

## Configuration

Both tools keep local clones in `~/repos` by default. Override with environment variables:

| Variable | Default | Used by |
|---|---|---|
| `GH_CONSOLE_REPOS` | `~/repos` | both |
| `GH_CONSOLE_PORT` | `8471` | GUI only |

```bash
GH_CONSOLE_REPOS=~/code python3 gh-console-gui.py
```

## The Deploy shortcut

If a repo's root contains a script named `deploy-*.sh` (e.g. `deploy-staging.sh`), the terminal tool lights up a **Deploy** option for it. It shows you the script and target, sanity-checks any hardcoded `SSH_KEY=` path (and offers to fix it if the key moved machines), then runs it with your confirmation. Multiple deploy scripts? You pick from a list.

## Notes

- Pushes always ask for confirmation. Nothing destructive runs without you saying so.
- The GUI binds to `127.0.0.1` only — it's not reachable from your network.
- `gh auth login` handles authentication; no tokens are stored by these tools.

## Contributing

Issues and PRs welcome. Keep it dependency-free: if a feature needs `pip install` or `npm install`, it's probably out of scope.

## License

MIT — see [LICENSE](LICENSE).
