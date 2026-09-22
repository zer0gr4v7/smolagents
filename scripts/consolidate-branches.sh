#!/usr/bin/env bash
# consolidate-branches.sh -- keep one line of history: fold agent branches into main.
#
# Why: every agent session (Claude Code, Codex, Cursor, a routine) pushes its own branch and
# opens a draft PR that nobody merges; eleven piled up here in one week. This script is the
# broom. Run it by hand or from a manual workflow; docs/BRANCH-POLICY.md is the rule.
#
# Rules, in order, for every remote branch except main:
#   1. already contained in main            -> delete the branch (PR shows as merged)
#   1b. its pull request is merged or closed -> delete the branch (squash merges and
#       superseded work; the PR keeps the history and the closing note)
#   2. merges cleanly AND touches only       -> merge into main, push, delete the branch
#      allow-listed paths (docs, logs)
#   3. anything else                         -> leave it, list it in the summary
# The routine log merges by union so two days' entries never conflict.
#
#   scripts/consolidate-branches.sh            # dry-run: print the plan
#   scripts/consolidate-branches.sh --apply    # merge, push main, delete folded branches
#
# Rule 1b needs `gh` with GH_TOKEN (GitHub Actions provides both); without it the rule is
# skipped and those branches are listed under "left alone". The manual workflow
# .github/workflows/branch-broom.yml runs this with --apply on a button press: the session
# git proxies agents push through refuse ref deletion, so the broom runs where it can.
set -euo pipefail
APPLY=0; [[ "${1:-}" == "--apply" ]] && APPLY=1
ALLOW='^(docs/|runtime/memory/|README\.md$|AGENTS\.md$)'
UNION_PATHS=("runtime/memory/MEMORY.md")

git fetch -q --prune origin
git checkout -q -B main origin/main
mkdir -p .git/info; for p in "${UNION_PATHS[@]}"; do echo "$p merge=union"; done > .git/info/attributes
git config user.name  "${GIT_AUTHOR_NAME:-consolidate-branches}"
git config user.email "${GIT_AUTHOR_EMAIL:-consolidate-branches@users.noreply.github.com}"

pr_state_for() {  # prints "merged #N" / "closed #N" when every PR for this head is finished; empty otherwise
  command -v gh >/dev/null 2>&1 && [[ -n "${GH_TOKEN:-}" ]] || return 1
  local json; json="$(gh pr list --repo "${GITHUB_REPOSITORY:-$(git remote get-url origin | sed -E 's#.*github.com[:/]##; s#\.git$##')}" \
      --head "$1" --state all --json number,state,mergedAt 2>/dev/null)" || return 1
  python3 - "$json" <<'PY'
import json, sys
prs = json.loads(sys.argv[1] or "[]")
if not prs or any(p["state"] == "OPEN" for p in prs): sys.exit(0)
p = prs[0]; print(("merged" if p.get("mergedAt") else "closed") + f" #{p['number']}")
PY
}

folded=(); deleted=(); kept=()
while IFS= read -r ref; do
  b="${ref#origin/}"
  [[ "$b" == "main" || "$b" == HEAD* ]] && continue
  if [[ "$(git rev-list --count main.."$ref")" == 0 ]]; then
    deleted+=("$b"); (( APPLY )) && git push -q origin --delete "$b" || true; continue
  fi
  if pr_state="$(pr_state_for "$b")" && [[ -n "$pr_state" ]]; then
    deleted+=("$b (PR $pr_state)"); (( APPLY )) && git push -q origin --delete "$b" || true; continue
  fi
  files="$(git diff --name-only "$(git merge-base main "$ref")" "$ref")"
  if printf '%s\n' "$files" | grep -qvE "$ALLOW"; then kept+=("$b (code changes; needs a human or the owning agent)"); continue; fi
  if git merge --no-edit -q "$ref" >/dev/null 2>&1; then
    folded+=("$b")
    (( APPLY )) || git reset -q --hard origin/main
  else
    git merge --abort 2>/dev/null || true
    kept+=("$b (conflict)")
  fi
done < <(git for-each-ref --format='%(refname:short)' refs/remotes/origin | sort)

if (( APPLY )); then
  git push -q origin main
  for b in "${folded[@]}"; do git push -q origin --delete "$b" || true; done
fi
printf 'consolidate-branches (%s)\n' "$([[ $APPLY == 1 ]] && echo applied || echo dry-run)"
printf '  folded into main : %s\n' "${#folded[@]}";  for b in "${folded[@]}";  do printf '    + %s\n' "$b"; done
printf '  already merged   : %s\n' "${#deleted[@]}"; for b in "${deleted[@]}"; do printf '    - %s\n' "$b"; done
printf '  left alone       : %s\n' "${#kept[@]}";    for b in "${kept[@]}";    do printf '    ? %s\n' "$b"; done
