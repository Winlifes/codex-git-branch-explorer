# OpenAI submission preparation

Status: distribution through this Git repository. No OpenAI approval or official directory listing is claimed. Last updated: 2026-09-15.

## Plugin

- Name: Git 分支浏览器 / Git Branch Explorer
- ID: `git-branch-explorer`
- Maintainer: [Winlifes](https://github.com/Winlifes)
- License: [MIT](../LICENSE), Copyright (c) 2026 Winlifes
- Source: [codex-git-branch-explorer](https://github.com/Winlifes/codex-git-branch-explorer)
- Releases: [download and checksums](https://github.com/Winlifes/codex-git-branch-explorer/releases)
- Support: [issues](https://github.com/Winlifes/codex-git-branch-explorer/issues)
- Privacy: [data handling](../PRIVACY.md)

A third-party Codex Desktop panel for local Git repositories. It displays branches, history, exact commit times, line statistics, file diffs and workspace status. Writes use a separate prepare/confirm/apply workflow. Operations include staging, committing, branch management, merging, reverting, safe branch deletion, fetching, fast-forward pulling, ordinary pushing, and backing up then discarding unstaged changes.

## Why local MCP support is needed

The backend is a Python stdio MCP server running on the user's computer. It accesses that user's local Git index, working tree, worktrees, hooks and credentials. A centrally hosted remote server cannot directly provide these local workspace capabilities.

The [official submission documentation](https://developers.openai.com/plugins/deploy/submission) directs local MCP developers who cannot use a public HTTPS endpoint to contact OpenAI for local MCP support. This project needs that distribution route to be confirmed before a complete store submission. Publishing this repository does not create a store listing.

The current implementation exposes an MCP thread entrypoint. It also reads local Codex task/project metadata to identify the current repository. These client-specific integration details, and the fallback when project context is missing, must be reviewed for compatibility. No Codex application files are modified.

## Runtime and data

- Git and Python 3.9+; no third-party Python dependency or API key.
- Validated on macOS with desktop-bundled Codex CLI 0.154.0-alpha.6.2. Other platforms are unverified.
- Local stdio transport; UI assets are self-contained. No maintainer-operated cloud service or telemetry.
- Repository results pass to the Codex host and panel through MCP. Remote Git operations use the user's configured remotes and Git environment.
- `git_panel`, `git_query` and `git_prepare` are marked read-only; `git_apply` is marked writable, potentially destructive and open-world.
- Writes require a short-lived preview token bound to the repository and calling task. The implementation rechecks repository state before applying it.
- Discard preserves staged contents and creates persistent local file backups before changing the working tree.

## Reviewer scenarios

Use disposable repositories only. The full suite can be run from the plugin root with `python3 -m unittest discover -s tests -v`.

| ID | Fixture and action | Expected outcome | Existing coverage |
| --- | --- | --- | --- |
| P1 | Create two branches and several commits; open the panel and inspect history/diffs | Correct branch history, times and line counts; browsing does not checkout | `test_git_explorer.py`, `test_mcp_server.py` |
| P2 | Stage part of a file, edit it again, preview and confirm a commit | Only staged contents are committed; remaining edits stay; replay does not commit twice | `test_commit_only_staged_content_uses_user_config_and_no_duplicate` |
| P3 | Prepare modified, deleted and untracked files; confirm single/all discard | Backups precede writes; staged contents survive; unselected files survive a single discard | `test_worktree_discard.py` |
| P4 | Create/switch branches, merge, revert a commit and delete a merged branch | Each mutation has its own preview; revert preserves history | `test_create_switch_and_safe_delete`, `test_revert_preserves_history`, merge tests |
| P5 | Use a temporary local bare remote with two clones; push, fetch and pull | Correct remote tracking and fast-forward behavior | `test_push_fetch_and_fast_forward_pull` |
| N1 | Change a file after preview, expire a token, or use a different task's token | Apply is rejected without changing the repository | `test_stale_preview_same_status_code_and_cross_task_are_rejected`, `test_expired_and_wrong_repo_tokens_are_rejected` |
| N2 | Try deleting the current, unmerged or another worktree's checked-out branch | Branch is retained and a reason is shown | `test_unmerged_current_and_checked_out_branch_not_deleted` |
| N3 | Open a task with missing project metadata or a non-Git directory | Explain the missing context or repository and offer manual selection; never choose another task's project | `test_project_context.py` |

These are reproducible review scenarios, not a record of an OpenAI review. Publisher verification, accepted local MCP packaging, listing assets, legal URLs and availability selections remain part of the eventual submission.
