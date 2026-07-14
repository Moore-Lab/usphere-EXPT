"""
sync_submodules.py

Brings every git submodule in this repo (and its nested submodules,
recursively) up to date with its remote tracking branch, staging and
optionally committing/pushing the updated pointers at each level.

Usage
-----
    python sync_submodules.py              # fetch + update all submodules
    python sync_submodules.py --dry-run    # show what would happen, no changes
    python sync_submodules.py --commit     # commit the updated pointers at each level
    python sync_submodules.py --commit --push   # also push each committed level
    python sync_submodules.py --force-reset     # use `reset --hard origin/<branch>`
                                                # instead of `pull --ff-only` (destructive)

What it does for each submodule (recursively, depth-first per submodule)
------------------------------------------------------------------------
1. Skip if not initialised (directory empty) - prints a hint to init it.
2. Skip with a warning if there are uncommitted local changes (unless
   --force-reset, in which case local changes are discarded).
3. git fetch origin
4. Choose a target branch:
     a. PREFERRED_BRANCH (unified-framework) if it exists on the remote
     b. The branch the submodule is already on (if not detached)
     c. main / master as a last resort
5. git checkout <target_branch>
6. git pull --ff-only  (or reset --hard origin/<target> if --force-reset)
   If ff-only fails and --force-reset is not set, the submodule is skipped
   and the conflict is reported so it can be resolved manually.
7. Recurse into this submodule's own submodules.
8. Back in this submodule, stage any nested pointer updates.  If --commit,
   commit them; if --push, also push.
9. When control returns to the parent, the parent stages this submodule's
   new pointer.

Exit codes
----------
0  all submodules processed without error
1  one or more submodules were skipped or had errors
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent

# Branch to prefer when it exists on the remote.
PREFERRED_BRANCH = "unified-framework"

# Fallback branches tried in order if PREFERRED_BRANCH doesn't exist.
FALLBACK_BRANCHES = ["main", "master"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], cwd: Path, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=capture,
                          text=True, check=False)


def _submodule_paths(path: Path) -> list[str]:
    """Return submodule paths (relative to *path*) from `git submodule status`."""
    r = _run(["git", "submodule", "status"], path)
    paths = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            paths.append(parts[1])
    return paths


def _current_branch(path: Path) -> str | None:
    """Return current branch name, or None if HEAD is detached."""
    r = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], path)
    branch = r.stdout.strip()
    return None if branch == "HEAD" else branch


def _remote_branch_exists(path: Path, branch: str) -> bool:
    r = _run(["git", "ls-remote", "--heads", "origin", branch], path)
    return bool(r.stdout.strip())


def _has_local_changes(path: Path) -> bool:
    """True if there are staged or unstaged changes to non-submodule files.

    Submodule pointer changes are ignored so this script's own intermediate
    output (staged pointer updates) does not block the recursion.  Untracked
    files are also ignored — only tracked-file modifications block.
    """
    r = _run(["git", "status", "--porcelain", "-uno",
              "--ignore-submodules=all"], path)
    return bool(r.stdout.strip())


def _has_staged_changes(path: Path) -> bool:
    r = _run(["git", "diff", "--cached", "--quiet"], path)
    return r.returncode != 0


def _short_hash(path: Path) -> str:
    r = _run(["git", "rev-parse", "--short", "HEAD"], path)
    return r.stdout.strip()


# ---------------------------------------------------------------------------
# Per-submodule sync
# ---------------------------------------------------------------------------

def _sync_one(rel_path: str, parent_path: Path, dry_run: bool,
              force_reset: bool, indent: str) -> tuple[bool, Path | None]:
    """
    Sync a single submodule.  Returns (ok, path).
      ok:   True on success, False if skipped/failed.
      path: absolute path to the submodule (or None if not initialised).
    """
    print(f"\n{indent}{'-' * 60}")
    print(f"{indent}  {rel_path}")
    print(f"{indent}{'-' * 60}")

    path = parent_path / rel_path

    if not path.exists() or not (path / ".git").exists():
        print(f"{indent}  [SKIP] not initialised - run:")
        print(f"{indent}         git submodule update --init {rel_path}")
        return False, None

    if _has_local_changes(path) and not force_reset:
        print(f"{indent}  [SKIP] uncommitted local changes detected.")
        print(f"{indent}         Commit or stash them, or use --force-reset.")
        return False, path

    # --- fetch ---
    print(f"{indent}  Fetching from remote ...")
    if not dry_run:
        r = _run(["git", "fetch", "origin"], path)
        if r.returncode != 0:
            print(f"{indent}  [FAIL] fetch failed:\n{r.stderr.strip()}")
            return False, path

    # --- choose target branch ---
    current = _current_branch(path)
    status_str = "detached HEAD" if current is None else f"branch '{current}'"
    print(f"{indent}  Currently on: {status_str}")

    target = None
    if _remote_branch_exists(path, PREFERRED_BRANCH):
        target = PREFERRED_BRANCH
    elif current is not None and _remote_branch_exists(path, current):
        target = current
    else:
        for fb in FALLBACK_BRANCHES:
            if _remote_branch_exists(path, fb):
                target = fb
                break

    if target is None:
        print(f"{indent}  [FAIL] could not determine a target branch.")
        return False, path

    print(f"{indent}  Target branch: {target}")

    if current != target:
        print(f"{indent}  Checking out '{target}' ...")
        if not dry_run:
            r = _run(["git", "checkout", target], path)
            if r.returncode != 0:
                print(f"{indent}  [FAIL] checkout failed:\n{r.stderr.strip()}")
                return False, path

    before = _short_hash(path)

    # --- pull (ff-only) or hard reset ---
    if force_reset:
        print(f"{indent}  Hard-resetting to origin/{target} (destructive) ...")
        if not dry_run:
            r = _run(["git", "reset", "--hard", f"origin/{target}"], path)
            if r.returncode != 0:
                print(f"{indent}  [FAIL] reset --hard failed:\n{r.stderr.strip()}")
                return False, path
    else:
        print(f"{indent}  Pulling latest commits (ff-only) ...")
        if not dry_run:
            r = _run(["git", "pull", "--ff-only", "origin", target], path)
            if r.returncode != 0:
                print(f"{indent}  [FAIL] pull --ff-only failed.")
                print(f"{indent}         The remote has diverged.  Re-run with")
                print(f"{indent}         --force-reset to discard local commits,")
                print(f"{indent}         or resolve manually in:  {path}")
                if r.stderr.strip():
                    print(f"{indent}\n{r.stderr.strip()}")
                return False, path

    after = _short_hash(path)
    if before != after:
        print(f"{indent}  [OK]  {before} -> {after}")
    else:
        print(f"{indent}  [OK]  already up to date  ({after})")

    return True, path


# ---------------------------------------------------------------------------
# Recursive sync
# ---------------------------------------------------------------------------

def _sync_tree(repo_path: Path, is_root: bool, dry_run: bool,
               force_reset: bool, do_commit: bool, do_push: bool,
               depth: int = 0) -> tuple[int, int]:
    """
    Sync all submodules under *repo_path* depth-first.

    Order for each submodule:
      1. Sync the submodule itself (fetch, checkout, pull/reset).
      2. Recurse into its own submodules.
      3. If nested pointer updates were made, stage them here.  If
         --commit, commit them; if --push, push.

    Returns (updated_count, skipped_count).
    """
    subs = _submodule_paths(repo_path)
    if not subs:
        return 0, 0

    indent = "  " * depth
    updated, skipped = 0, 0

    for rel in subs:
        ok, sub_path = _sync_one(rel, repo_path, dry_run, force_reset, indent)
        if not ok:
            skipped += 1
            continue
        updated += 1

        # Recurse into this submodule's own submodules
        nested_u, nested_s = _sync_tree(
            sub_path, is_root=False, dry_run=dry_run,
            force_reset=force_reset, do_commit=do_commit, do_push=do_push,
            depth=depth + 1)
        updated += nested_u
        skipped += nested_s

        # If nested pointer updates were staged, commit + push them here
        # so the next-higher parent can reference them.
        if not dry_run and _has_staged_changes(sub_path) is False:
            # No staged changes here from nested subs; but there might be
            # working-tree changes to nested submodule pointers not yet staged.
            # Stage them explicitly.
            _run(["git", "add", "-u"], sub_path)

        if not dry_run and _has_staged_changes(sub_path):
            print(f"{indent}  Staged nested pointer updates in {rel}")
            if do_commit:
                msg = f"Update nested submodule refs (auto: sync_submodules.py)"
                r = _run(["git", "commit", "-m", msg], sub_path)
                if r.returncode == 0:
                    print(f"{indent}  Committed nested pointer updates in {rel}")
                    if do_push:
                        r2 = _run(["git", "push"], sub_path)
                        if r2.returncode == 0:
                            print(f"{indent}  Pushed {rel}")
                        else:
                            print(f"{indent}  [WARN] push failed for {rel}")
                else:
                    print(f"{indent}  [WARN] commit failed for {rel}")

    # After all children of *repo_path* are synced, stage their pointer
    # updates in *repo_path* itself so the calling frame can commit.
    if not dry_run and subs:
        _run(["git", "add"] + subs, repo_path)

    return updated, skipped


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Recursively sync all git submodules to their latest remote commits.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--dry-run", action="store_true",
                   help="show what would happen without making any changes")
    p.add_argument("--commit", action="store_true",
                   help="commit staged pointer updates at each level")
    p.add_argument("--push", action="store_true",
                   help="push after committing at each level (implies --commit "
                        "for intermediate levels)")
    p.add_argument("--force-reset", action="store_true",
                   help="destructive: use `reset --hard origin/<target>` instead "
                        "of `pull --ff-only`.  Discards local commits on the "
                        "target branch when the remote has been force-pushed.")
    args = p.parse_args()

    if args.dry_run:
        print("DRY RUN - no changes will be made\n")

    # Push requires commit to be meaningful for intermediate levels
    do_commit = args.commit or args.push

    updated, skipped = _sync_tree(
        REPO_ROOT, is_root=True, dry_run=args.dry_run,
        force_reset=args.force_reset, do_commit=do_commit,
        do_push=args.push, depth=0)

    # --- stage updated pointers in the root repo ---
    print(f"\n{'-' * 60}")
    top_subs = _submodule_paths(REPO_ROOT)
    if not args.dry_run and top_subs:
        r = _run(["git", "status", "--short"], REPO_ROOT)
        staged = [l for l in r.stdout.splitlines() if l.strip()]
        if staged:
            print("  Root repo state after sync:")
            for l in staged:
                print(f"    {l}")
        if args.commit:
            r = _run(["git", "diff", "--cached", "--quiet"], REPO_ROOT)
            if r.returncode != 0:  # staged changes present
                msg = "Update submodule refs (auto: sync_submodules.py)"
                r2 = _run(["git", "commit", "-m", msg], REPO_ROOT, capture=False)
                if r2.returncode == 0:
                    print(f"\n  Committed root: {msg}")
                    if args.push:
                        r3 = _run(["git", "push"], REPO_ROOT, capture=False)
                        if r3.returncode == 0:
                            print(f"  Pushed root")
                        else:
                            print(f"  [WARN] root push failed")
                else:
                    print("\n  [WARN] root commit failed - staged changes remain.")
            else:
                print("\n  Root already had no staged changes to commit.")
    elif args.dry_run:
        print("  (dry run - nothing staged)")

    print(f"\n{'-' * 60}")
    print(f"  Done:    {updated} synced,  {skipped} skipped")
    print(f"{'-' * 60}\n")

    return 0 if skipped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
