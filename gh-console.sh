#!/usr/bin/env bash
#
# gh-console — a friendly console helper for everyday GitHub work.
#   - checks gh is installed
#   - logs you in if needed (gh auth login)
#   - lets you pick a repo from your account (remembers last choice)
#   - status, pull, push, quick commit+push, branches, commits, PRs, issues,
#     stash, deploy-to-test (repo-aware), open in browser
#
# Usage: ./gh-console.sh
# Clones go to ${GH_CONSOLE_REPOS:-~/repos}.  Last repo remembered in ~/.config/gh-console/
# Env: GH_CONSOLE_REPOS — override the local clones directory.

set -euo pipefail

CONFIG_DIR="${HOME}/.config/gh-console"
LAST_REPO_FILE="${CONFIG_DIR}/last_repo"
CLONE_ROOT="${GH_CONSOLE_REPOS:-${HOME}/repos}"
REPO=""

# ── prerequisites ──────────────────────────────────────────────────────────

need_gh() {
  if ! command -v gh >/dev/null 2>&1; then
    echo ""
    echo "  GitHub CLI (gh) isn't installed."
    echo "  Install it with:  brew install gh"
    echo ""
    exit 1
  fi
}

ensure_auth() {
  if gh auth status >/dev/null 2>&1; then
    local user
    user="$(gh api user -q .login 2>/dev/null || echo "unknown")"
    echo "  ✓ Logged in to GitHub as ${user}"
    return 0
  fi
  echo ""
  echo "  You're not logged into GitHub yet — let's fix that."
  echo ""
  gh auth login
}

# ── repo picker ──────────────────────────────────────────────────────────────

pick_repo() {
  echo ""
  echo "  Fetching your repositories…"
  local repos
  mapfile -t repos < <(gh repo list --limit 100 --json nameWithOwner --jq '.[].nameWithOwner')
  if [ "${#repos[@]}" -eq 0 ]; then
    echo "  No repositories found on your account."
    exit 1
  fi
  echo ""
  echo "  Choose a repository:"
  select repo in "${repos[@]}"; do
    if [ -n "${repo:-}" ]; then
      mkdir -p "$CONFIG_DIR"
      echo "$repo" > "$LAST_REPO_FILE"
      REPO="$repo"
      break
    fi
    echo "  Pick a number from the list."
  done
}

resolve_repo() {
  if [ -f "$LAST_REPO_FILE" ]; then
    local last
    last="$(cat "$LAST_REPO_FILE")"
    echo ""
    read -rp "  Use last repo (${last})? [Y/n] " ans
    if [[ ! "$ans" =~ ^[Nn] ]]; then
      REPO="$last"
      return 0
    fi
  fi
  pick_repo
}

repo_dir() {
  echo "${CLONE_ROOT}/$(basename "$REPO")"
}

ensure_cloned() {
  local dir
  dir="$(repo_dir)"
  if [ -d "${dir}/.git" ]; then
    return 0
  fi
  echo ""
  echo "  No local copy yet. Cloning ${REPO} → ${dir}"
  mkdir -p "$CLONE_ROOT"
  gh repo clone "$REPO" "$dir"
}

# ── actions ──────────────────────────────────────────────────────────────────

act_status() {
  ensure_cloned
  echo ""
  git -C "$(repo_dir)" status -sb
  echo ""
  echo "  ── last 5 commits ──"
  git -C "$(repo_dir)" log --oneline -5
}

act_pull() {
  ensure_cloned
  echo ""
  git -C "$(repo_dir)" pull --ff-only
}

act_push() {
  ensure_cloned
  local dir
  dir="$(repo_dir)"
  echo ""
  git -C "$dir" status -sb | head -10
  echo ""
  read -rp "  Push $(git -C "$dir" rev-parse --abbrev-ref HEAD) to origin? [y/N] " ans
  if [[ "$ans" =~ ^[Yy] ]]; then
    git -C "$dir" push
  else
    echo "  Cancelled."
  fi
}

act_quick_commit() {
  ensure_cloned
  local dir
  dir="$(repo_dir)"
  echo ""
  if git -C "$dir" diff --quiet && git -C "$dir" diff --cached --quiet; then
    echo "  Nothing to commit — working tree is clean."
    return 0
  fi
  git -C "$dir" status -s | head -20
  echo ""
  read -rp "  Stage everything and commit? [y/N] " ans
  [[ "$ans" =~ ^[Yy] ]] || { echo "  Cancelled."; return 0; }
  git -C "$dir" add -A
  read -rp "  Commit message: " msg
  if [ -z "$msg" ]; then
    echo "  Empty message — cancelled (nothing committed)."
    return 0
  fi
  git -C "$dir" commit -m "$msg"
  echo ""
  read -rp "  Push now? [Y/n] " ans2
  if [[ ! "$ans2" =~ ^[Nn] ]]; then
    git -C "$dir" push
  fi
}

act_branch() {
  ensure_cloned
  local dir
  dir="$(repo_dir)"
  echo ""
  echo "  Current: $(git -C "$dir" rev-parse --abbrev-ref HEAD)"
  echo "  Recent branches:"
  git -C "$dir" branch --sort=-committerdate | head -8
  echo ""
  echo "  1) Create new branch   2) Switch branch   3) Back"
  read -rp "  Choice: " c
  case "$c" in
    1)
      read -rp "  New branch name: " name
      [ -n "$name" ] && git -C "$dir" checkout -b "$name"
      ;;
    2)
      read -rp "  Switch to branch: " target
      [ -n "$target" ] && git -C "$dir" checkout "$target"
      ;;
  esac
}

act_commits() {
  ensure_cloned
  local dir
  dir="$(repo_dir)"
  echo ""
  git -C "$dir" log --oneline --decorate -12
  echo ""
  read -rp "  Show full diff for a commit? (sha, blank to skip): " sha
  if [ -n "$sha" ]; then
    git -C "$dir" show --stat "$sha" | head -30
    echo ""
    read -rp "  Show the actual diff? [y/N] " ans
    [[ "$ans" =~ ^[Yy] ]] && git -C "$dir" show "$sha" | head -200
  fi
}

act_pr_create() {
  ensure_cloned
  local dir br
  dir="$(repo_dir)"
  br="$(git -C "$dir" rev-parse --abbrev-ref HEAD)"
  echo ""
  if [ "$br" = "main" ] || [ "$br" = "master" ] || [ "$br" = "dev" ]; then
    echo "  You're on '${br}'. PRs usually come from a feature branch."
    read -rp "  Create the PR from '${br}' anyway? [y/N] " ans
    [[ "$ans" =~ ^[Yy] ]] || return 0
  fi
  ( cd "$dir" && gh pr create --repo "$REPO" )
}

act_pr_list() {
  echo ""
  gh pr list --repo "$REPO" --limit 10
  echo ""
  read -rp "  Check out a PR locally? (number, blank to skip): " num
  if [ -n "$num" ]; then
    ensure_cloned
    git -C "$(repo_dir)" fetch origin "pull/${num}/head:pr-${num}" 2>/dev/null || \
      ( cd "$(repo_dir)" && gh pr checkout "$num" --repo "$REPO" )
  fi
}

act_issues() {
  echo ""
  echo "  ── open issues ──"
  gh issue list --repo "$REPO" --limit 10
  echo ""
  read -rp "  View an issue? (number, blank to skip): " num
  [ -n "$num" ] && gh issue view "$num" --repo "$REPO"
}

act_stash() {
  ensure_cloned
  local dir
  dir="$(repo_dir)"
  echo ""
  echo "  1) Stash current changes   2) Pop latest stash   3) List stashes   4) Back"
  read -rp "  Choice: " c
  case "$c" in
    1)
      read -rp "  Stash message (optional): " msg
      git -C "$dir" stash push -m "${msg:-wip}"
      ;;
    2) git -C "$dir" stash pop ;;
    3) git -C "$dir" stash list | head -10 ;;
  esac
}

act_deploy() {
  ensure_cloned
  local dir script
  dir="$(repo_dir)"
  local scripts
  mapfile -t scripts < <(ls "${dir}"/deploy-*.sh 2>/dev/null || true)
  if [ "${#scripts[@]}" -eq 0 ]; then
    echo ""
    echo "  No deploy-*.sh script in ${REPO} — nothing to deploy."
    echo "  (Drop a deploy script named deploy-<target>.sh in the repo root"
    echo "   to light up this shortcut.)"
    return 0
  fi
  if [ "${#scripts[@]}" -eq 1 ]; then
    script="${scripts[0]}"
  else
    echo ""
    echo "  Multiple deploy scripts found:"
    select script in "${scripts[@]}"; do
      [ -n "${script:-}" ] && break
      echo "  Pick a number from the list."
    done
  fi
  script="$(basename "$script")"
  local target="${script#deploy-}"
  target="${target%.sh}"
  local br
  br="$(git -C "$dir" rev-parse --abbrev-ref HEAD)"
  # many deploy scripts guard the branch themselves; we just confirm
  echo ""
  echo "  Deploy script: ${script}  (target: ${target}, branch: ${br})"
  # scripts often hardcode an SSH key path — make sure it exists here
  local key
  key="$(grep -m1 '^SSH_KEY=' "${dir}/${script}" | cut -d'"' -f2)"
  if [ -n "$key" ] && [ ! -f "$key" ]; then
    echo ""
    echo "  Deploy script expects SSH key at:"
    echo "    ${key}"
    echo "  …which doesn't exist on this machine."
    read -rp "  Enter the correct key path (blank to abort): " newkey
    [ -z "${newkey:-}" ] && return 0
    if [ ! -f "$newkey" ]; then
      echo "  That file doesn't exist either — aborting."
      return 0
    fi
    # portable in-place edit (macOS + GNU sed)
    sed -i.bak "s|^SSH_KEY=.*|SSH_KEY=\"${newkey}\"|" "${dir}/${script}"
    echo "  Updated SSH_KEY (backup: ${script}.bak)"
  fi
  echo ""
  read -rp "  Deploy ${REPO} (${target}) now? [y/N] " ans
  if [[ "$ans" =~ ^[Yy] ]]; then
    bash "${dir}/${script}"
  else
    echo "  Cancelled."
  fi
}

act_open() {
  gh repo view "$REPO" --web
}

act_where() {
  ensure_cloned
  echo ""
  echo "  Local copy: $(repo_dir)"
}

# ── menu ─────────────────────────────────────────────────────────────────────

menu() {
  while true; do
    echo ""
    echo "  ══ ${REPO} ══════════════════════════════"
    echo "  1) Status              8) Create pull request"
    echo "  2) Pull latest         9) List pull requests"
    echo "  3) Quick commit+push  10) Issues"
    echo "  4) Push               11) Stash"
    echo "  5) Branch             12) Deploy (repo script)"
    echo "  6) Recent commits     13) Open in browser"
    echo "                        14) Local path"
    echo "                        15) Switch repository"
    echo "                        16) Quit"
    echo ""
    read -rp "  Choice [1-16]: " choice
    case "$choice" in
      1) act_status ;;
      2) act_pull ;;
      3) act_quick_commit ;;
      4) act_push ;;
      5) act_branch ;;
      6) act_commits ;;
      7) act_pr_create ;;
      8) act_pr_list ;;
      9) act_issues ;;
      10) act_stash ;;
      11) act_deploy ;;
      12) act_open ;;
      13) act_where ;;
      14) pick_repo; echo ""; echo "  ✓ Working with ${REPO}" ;;
      15) echo ""; echo "  Bye."; exit 0 ;;
      16) echo ""; echo "  Bye."; exit 0 ;;
      *) echo "  Pick 1-16." ;;
    esac
  done
}

# ── main ─────────────────────────────────────────────────────────────────────

echo ""
echo "  ┌─ gh-console ─────────────────────────────"
echo "  │  GitHub without the tab-switching."
echo "  └──────────────────────────────────────────"

need_gh
ensure_auth
resolve_repo
echo ""
echo "  ✓ Working with ${REPO}"
menu
