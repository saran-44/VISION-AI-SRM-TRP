# Workspace sync — when the editor sees a different tree than GitHub

A recurring failure on this project: the VS Code assistant reports that files are
missing, or that `main` is a commit the repository left behind hours ago. Nothing
is wrong with the repository. The editor is reading a **stale checkout or a stale
index**, and the fix is on the machine, not in Git.

This page exists so the next occurrence is a two-minute fix instead of a
detour.

---

## 1. The signature

```
HEAD: 0fc4c77
docs/MASTER_PROMPT.md is missing
docs/TASK_ANPR_VSCODE.md is missing
af65914 is not available in the checkout
```

Read it as: *"I am looking at a snapshot from before those commits existed."*
It is never a reason to create the files.

## 2. Why `0fc4c77` is a real answer — just an old one

`0fc4c77` is the merge of **PR #24** (2026-11-14 08:00 UTC). At that commit:

| File | Exists at `0fc4c77`? | Added by |
| --- | --- | --- |
| `docs/COLLAB_VSCODE.md` | ❌ | #27, `d5cc329` |
| `docs/MASTER_PROMPT.md` | ❌ | #28, `31b818a` (08:47 UTC) |
| `docs/TASK_ANPR_VSCODE.md` | ❌ | #30, `a191f47` (09:08 UTC) |

So a checkout pinned at `0fc4c77` is *supposed* to be missing all three. The
repository is not broken; the checkout is 18 commits behind `main`.

## 3. How to tell a stale checkout from a stale index

Run these in the **integrated terminal**, not through the assistant's file
search — the terminal reads the real disk, the index may not:

```bash
cd ~/VISION-AI-SRM-TRP
pwd
git rev-parse --short HEAD
git status -sb
ls docs/
```

| Terminal says | File search says | Verdict |
| --- | --- | --- |
| `HEAD: a1ef06c` or later | files missing | **stale index** — reload the window |
| `HEAD: 0fc4c77` | files missing | **stale checkout** — pull |
| `pwd` is not the repo | anything | **wrong folder** — reopen the right one |

## 4. The three fixes

**Stale checkout.**

```bash
cd ~/VISION-AI-SRM-TRP
git fetch origin
git pull --ff-only origin main
git rev-parse --short HEAD      # a1ef06c or newer
```

**Stale index.** `Ctrl+Shift+P` → **Developer: Reload Window**, then start a
**new chat** — an old conversation carries the old context with it.

**Wrong folder.** `File → Close Folder`, then `File → Open Folder` →
`C:\Users\<you>\VISION-AI-SRM-TRP` (the folder that contains `.git`, `backend/`,
`frontend/` and `docs/`). Confirm with `git rev-parse --show-toplevel`.

If there are two clones on the machine, delete or archive the one you are not
using. A duplicate checkout is how this starts.

## 5. Prove the repository is fine

From any machine with `gh` configured:

```bash
gh api repos/saran-44/VISION-AI-SRM-TRP/commits/main --jq .sha
gh api "repos/saran-44/VISION-AI-SRM-TRP/compare/0fc4c77...main" --jq '"ahead \(.ahead_by), behind \(.behind_by)"'
gh api "repos/saran-44/VISION-AI-SRM-TRP/commits?path=docs/TASK_ANPR_VSCODE.md&per_page=1" --jq '.[0].sha'
```

`behind 0` means history was never rewritten — `0fc4c77` is an ancestor of
`main`, not a competing branch. `ahead 18` is how far the snapshot is behind.

## 6. Rules that keep this from wasting a session

- **The terminal wins.** `ls docs/` beats any codebase index. If they disagree,
  the index is wrong.
- **Never create a file to satisfy a gate.** A placeholder that makes a check
  pass hides the real fault and then gets committed.
- **Report, don't repair.** "My index does not include X, the listing does" is a
  complete, actionable report. "X is missing" is not.
- **One clone per machine.** Name it, and point the editor at it.
