from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


DEFAULT_OUTPUT_DIR = Path(".agents/live-review")


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    root = _repo_root(Path(args.repo).resolve())
    output_dir = (root / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    state = WatchState()
    print(f"Watching {root}", flush=True)
    print(f"Writing review artifacts to {output_dir}", flush=True)

    while True:
        try:
            _tick(root, output_dir, args, state)
            time.sleep(args.poll_seconds)
        except KeyboardInterrupt:
            print("Stopped live Codex review watcher.", flush=True)
            return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Codex review when git changes settle.",
    )
    parser.add_argument("--repo", default=".", help="Repository root to watch.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for latest.md, latest.json, and history artifacts.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=3.0,
        help="How often to check git diff state.",
    )
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=10.0,
        help="Run review after changes stay unchanged for this many seconds.",
    )
    parser.add_argument(
        "--cooldown-seconds",
        type=float,
        default=45.0,
        help="Minimum gap between two review runs.",
    )
    parser.add_argument(
        "--codex-timeout-seconds",
        type=float,
        default=600.0,
        help="Maximum runtime for codex review.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one settled review check and exit.",
    )
    return parser


class WatchState:
    def __init__(self) -> None:
        self.last_digest: str | None = None
        self.last_seen_at = 0.0
        self.last_reviewed_digest: str | None = None
        self.last_review_at = 0.0


def _tick(
    root: Path,
    output_dir: Path,
    args: argparse.Namespace,
    state: WatchState,
) -> None:
    snapshot = _git_snapshot(root)
    now = time.monotonic()

    if not snapshot.has_changes:
        _write_status(output_dir, root, snapshot, "clean", "No uncommitted changes.")
        if args.once:
            raise KeyboardInterrupt
        return

    if snapshot.digest != state.last_digest:
        state.last_digest = snapshot.digest
        state.last_seen_at = now
        _write_status(
            output_dir,
            root,
            snapshot,
            "waiting",
            f"Waiting {args.settle_seconds:g}s for changes to settle.",
        )
        if args.once:
            _run_review(root, output_dir, args, snapshot, state)
            raise KeyboardInterrupt
        return

    age = now - state.last_seen_at
    cooldown = now - state.last_review_at
    if snapshot.digest == state.last_reviewed_digest:
        _write_status(output_dir, root, snapshot, "reviewed", "Latest diff already reviewed.")
        return
    if age < args.settle_seconds:
        _write_status(
            output_dir,
            root,
            snapshot,
            "waiting",
            f"Changes stable for {age:.1f}s; waiting for {args.settle_seconds:g}s.",
        )
        return
    if cooldown < args.cooldown_seconds:
        _write_status(
            output_dir,
            root,
            snapshot,
            "cooldown",
            f"Review cooldown active for {args.cooldown_seconds - cooldown:.1f}s.",
        )
        return

    _run_review(root, output_dir, args, snapshot, state)


class GitSnapshot:
    def __init__(
        self,
        status: str,
        diff_name_status: str,
        diff_stat: str,
        diff_digest_input: str,
    ) -> None:
        self.status = status
        self.diff_name_status = diff_name_status
        self.diff_stat = diff_stat
        self.digest = hashlib.sha256(diff_digest_input.encode("utf-8")).hexdigest()
        self.has_changes = bool(status.strip())


def _git_snapshot(root: Path) -> GitSnapshot:
    status = _run_git(root, "status", "--porcelain=v1").stdout
    diff_name_status = _run_git(root, "diff", "--name-status").stdout
    diff_stat = _run_git(root, "diff", "--stat").stdout
    diff_digest_input = "\n".join(
        [
            "--status--",
            status,
            "--worktree-diff--",
            _run_git(root, "diff", "--binary", "--no-ext-diff").stdout,
            "--staged-diff--",
            _run_git(root, "diff", "--cached", "--binary", "--no-ext-diff").stdout,
            "--untracked--",
            _untracked_digest_input(root),
        ]
    )
    return GitSnapshot(
        status=status,
        diff_name_status=diff_name_status,
        diff_stat=diff_stat,
        diff_digest_input=diff_digest_input,
    )


def _untracked_digest_input(root: Path) -> str:
    completed = _run_git(root, "ls-files", "--others", "--exclude-standard", "-z")
    paths = [part for part in completed.stdout.split("\0") if part]
    lines: list[str] = []
    for relative_path in sorted(paths):
        path = root / relative_path
        if not path.is_file():
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            digest = f"unreadable:{exc.__class__.__name__}"
        lines.append(f"{relative_path}\t{digest}")
    return "\n".join(lines)


def _run_review(
    root: Path,
    output_dir: Path,
    args: argparse.Namespace,
    snapshot: GitSnapshot,
    state: WatchState,
) -> None:
    started = _utc_now()
    print(f"[{started}] Running codex review for {snapshot.digest[:12]}", flush=True)
    _write_status(output_dir, root, snapshot, "running", "Codex review is running.")
    try:
        completed = subprocess.run(
            ["codex", "review", "--uncommitted"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=args.codex_timeout_seconds,
            check=False,
        )
        exit_code = completed.returncode
        review_output = completed.stdout
        status = "completed"
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        review_output = (
            f"codex review timed out after {args.codex_timeout_seconds:g}s.\n\n"
            f"{exc.stdout or ''}{exc.stderr or ''}"
        )
        status = "timeout"
    finished = _utc_now()
    state.last_review_at = time.monotonic()
    state.last_reviewed_digest = snapshot.digest

    payload = {
        "repo": str(root),
        "status": status,
        "started_at": started,
        "finished_at": finished,
        "digest": snapshot.digest,
        "exit_code": exit_code,
        "git_status": snapshot.status,
        "git_diff_stat": snapshot.diff_stat,
        "review": review_output,
    }
    _write_json(output_dir / "latest.json", payload)
    _write_markdown(output_dir / "latest.md", payload)

    history_name = f"{finished.replace(':', '').replace('-', '')}-{snapshot.digest[:12]}.md"
    _write_markdown(output_dir / "history" / history_name, payload)
    print(f"[{finished}] Review complete: {output_dir / 'latest.md'}", flush=True)


def _write_status(
    output_dir: Path,
    root: Path,
    snapshot: GitSnapshot,
    status: str,
    message: str,
) -> None:
    payload = {
        "repo": str(root),
        "status": status,
        "message": message,
        "updated_at": _utc_now(),
        "digest": snapshot.digest,
        "git_status": snapshot.status,
        "git_diff_stat": snapshot.diff_stat,
    }
    _write_json(output_dir / "state.json", payload)


def _write_markdown(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    review = str(payload.get("review", "")).rstrip()
    diff_stat = str(payload.get("git_diff_stat", "")).rstrip()
    git_status = str(payload.get("git_status", "")).rstrip()
    content = "\n".join(
        [
            "# Live Codex Review",
            "",
            f"- repo: `{payload['repo']}`",
            f"- status: `{payload['status']}`",
            f"- exit_code: `{payload['exit_code']}`",
            f"- digest: `{payload['digest']}`",
            f"- started_at: `{payload['started_at']}`",
            f"- finished_at: `{payload['finished_at']}`",
            "",
            "## Git Status",
            "",
            "```text",
            git_status,
            "```",
            "",
            "## Diff Stat",
            "",
            "```text",
            diff_stat,
            "```",
            "",
            "## Review",
            "",
            review or "(No review output.)",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _repo_root(path: Path) -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"Not a git repository: {path}")
    return Path(completed.stdout.strip()).resolve()


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(main())
