# Live Codex Review

Use this watcher when Claude Code is actively editing and Codex should review
the current worktree as changes settle.

```powershell
python scripts/live_codex_review.py
```

The watcher checks `git status` and the full staged, unstaged, and untracked
diff. After changes remain stable for 10 seconds, it runs:

```powershell
codex review --uncommitted
```

Review output is written to:

- `.agents/live-review/latest.md`
- `.agents/live-review/latest.json`
- `.agents/live-review/history/`

These files are local runtime artifacts and are ignored by git.

Useful options:

```powershell
python scripts/live_codex_review.py --settle-seconds 5 --cooldown-seconds 30
python scripts/live_codex_review.py --once --settle-seconds 0
```

Claude also has a project hook in `.claude/settings.json` that runs
`codex review --uncommitted` when Claude stops after editing. The live watcher is
for earlier feedback while Claude is still working.
