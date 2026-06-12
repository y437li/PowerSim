# Worktree discipline

Energy GO uses **git worktrees** so multiple feature branches can be worked simultaneously without stashing or switching branches. This page covers the naming convention, where worktrees live, and when to clean them up.

## Where worktrees go

**Worktrees must be outside OneDrive (or any cloud-sync folder).** OneDrive tries to sync every file write, which causes conflicts and corruption with git's index and object store. The canonical location is:

```
~/powersim-wt-<feature>
```

Examples:

```bash
git worktree add ~/powersim-wt-battery-dynamics -b feat/env-battery-dynamics origin/main
git worktree add ~/powersim-wt-serving-api       -b feat/serving-geo-site-api  origin/main
```

The `<feature>` part of the path should match the branch name's `<feature>` segment (hyphens throughout).

> **Do NOT** create worktrees inside the main repo, inside `OneDrive-Personal/`, or inside any path that git would count as part of another worktree. The safe test: `git worktree list` should show your worktree clearly separated from the main checkout.

## Creating a worktree

```bash
# From the repo root (or anywhere — git resolves it):
git fetch origin
git worktree add ~/powersim-wt-<feature> -b <branch-name> origin/main
```

This creates the directory, initialises it on a new branch tracking `origin/main`, and shares the git object store with the main checkout — no clone overhead.

## Removing a worktree

Remove the worktree when its branch merges to `main`:

```bash
# 1. From the repo root, remove the worktree reference:
git worktree remove ~/powersim-wt-<feature>

# 2. Delete the local branch (already merged):
git branch -d feat/<area>-<feature>
```

If the worktree was left in a dirty state by a predecessor, you may need `--force`:

```bash
git worktree remove --force ~/powersim-wt-<feature>
```

List all worktrees to audit strays:

```bash
git worktree list
```

## Working inside a worktree

A worktree is a full working tree. All normal git commands work:

```bash
cd ~/powersim-wt-<feature>
git status
git add ...
git commit -m "..."
git push origin <branch-name>
```

The worktree shares history with the main checkout — `git log`, `git show`, and `git fetch origin` all work correctly. You do **not** need to `cd` back to the main checkout to run git operations.

## CI and tests inside a worktree

Tests run identically from a worktree — the Python virtualenv and `node_modules` are path-relative (`.venv` and `node_modules/` in the worktree root). If you run `install_app.sh` from the worktree, it creates those directories there, not in the main checkout.

```bash
cd ~/powersim-wt-<feature>
uv pip install -e ".[dev]"
pytest tests/<area>/test_<area>_<feature>.py
```

## Predecessor stale worktrees

If you inherit a task from a stalled predecessor, check `git worktree list` and GitHub PR state before creating a new worktree. If a worktree already exists on the right branch, use it directly:

```bash
cd ~/powersim-wt-<feature>
git fetch origin
git rebase origin/main   # bring it up to date
```

If the predecessor's worktree is inside OneDrive (an error), move its branch to a clean worktree:

```bash
# 1. Fetch the existing branch
git fetch origin

# 2. Create a new clean worktree on the same branch
git worktree add ~/powersim-wt-<feature> <branch-name>

# 3. When the PR merges, remove both the old (inside OneDrive) and new worktrees
```
