# OpenAI submission preparation

Status: public GitHub distribution; local MCP directory eligibility remains unconfirmed. No OpenAI approval, submitted draft or official directory listing is claimed. Last checked against official documentation: 2026-10-12.

## Plugin

- Name: Git 分支浏览器 / Git Branch Explorer
- ID: `git-branch-explorer`
- Maintainer: [Winlifes](https://github.com/Winlifes)
- License: [MIT](../LICENSE), Copyright (c) 2026 Winlifes
- Source: [codex-git-branch-explorer](https://github.com/Winlifes/codex-git-branch-explorer)
- Releases: [download and checksums](https://github.com/Winlifes/codex-git-branch-explorer/releases)
- Current release: [v0.5.2](https://github.com/Winlifes/codex-git-branch-explorer/releases/tag/v0.5.2)
- Support: [issues](https://github.com/Winlifes/codex-git-branch-explorer/issues)
- Privacy: [data handling](../PRIVACY.md)

A third-party Codex Desktop panel for local Git repositories, with Log, Commit and Stashes views. It displays branch/tag folders, commit topology, exact times, line statistics, unified/side-by-side diffs and workspace status. Writes use a separate prepare/confirm/apply workflow. Operations include staging, selected-file and staged-only commits, branch management, merging, reverting, safe branch deletion, fetching, fast-forward pulling, ordinary pushing, stashing, and backing up then discarding unstaged changes. Stash inspection shows index, working-tree and untracked snapshots separately.

## Why local MCP support is needed

The backend is a Python stdio MCP server running on the user's computer. It accesses that user's local Git index, working tree, worktrees, hooks and credentials. A centrally hosted remote server cannot directly provide these local workspace capabilities.

The [official submission flow](https://developers.openai.com/plugins/deploy/submission) supports ZIP upload, review and publication through the [Plugins dashboard](https://platform.openai.com/plugins). Public listing still depends on approval.

The [official conversion guidance](https://developers.openai.com/plugins/guides/submit-claude-plugin) identifies local execution and local file access as cases requiring OpenAI contact before submission. The [remote MCP review requirements](https://developers.openai.com/plugins/deploy/app-review) describe an externally reachable server. This project's distribution route therefore needs confirmation from OpenAI. A GitHub release or personal marketplace registration does not create an official listing.

Deploying this service centrally would not provide access to each user's local index, worktree and Git configuration. The bundled MCP service is necessary for the panel; submitting only the skill would omit that functionality.

The current implementation exposes an MCP thread entrypoint. It also reads local Codex task/project metadata to identify the current repository. These client-specific integration details, and the fallback when project context is missing, must be reviewed for compatibility. No Codex application files are modified.

## Runtime and data

- Git and Python 3.9+; no third-party Python dependency or API key.
- v0.5.2 was validated on macOS on 2026-10-12: 81 Python tests and 19 Node tests passed, with related localization/MCP tests rerun after the stash-inspection fix. Other platforms are unverified.
- Local stdio transport; UI assets are self-contained. No maintainer-operated cloud service or telemetry.
- Repository results pass to the Codex host and panel through MCP. Remote Git operations use the user's configured remotes and Git environment.
- `git_panel`, `git_query` and `git_prepare` are marked read-only; `git_apply` is marked writable, potentially destructive and open-world.
- Writes require a short-lived preview token bound to the repository and calling task. The implementation rechecks repository state before applying it.
- Discard preserves staged contents and creates persistent local file backups before changing the working tree.
- The panel follows the host locale with English and Simplified Chinese UI, falling back to English for other languages. Locale changes preserve inputs and operation previews; Git names, messages and file contents are never translated.

## Reviewer scenarios

Use disposable repositories only. Run `python3 -m unittest discover -s tests -v` and `node --test tests/*.test.cjs` from the plugin root. The release ZIP was checked for portable launch configuration and successful extracted-package MCP startup.

| ID | Fixture and action | Expected outcome | Existing coverage |
| --- | --- | --- | --- |
| P1 | Create nested branches/tags and commits; browse history/diffs and switch the host language | Correct folders, topology, times and counts; no checkout; English/Chinese UI preserves Git data and input state | `test_git_explorer.py`, `test_mcp_server.py`, `test_i18n.py`, `branch-tree.test.cjs`, `workbench.test.cjs` and local host UI validation |
| P2 | Partially stage files, edit them again and preview each commit mode | Staged-only commits preserve unstaged edits; selected-file commits preserve unrelated staged/unstaged files; replay does not create a second commit | `test_commit_only_staged_content_uses_user_config_and_no_duplicate`, `test_selected_commit_preserves_unselected_staged_and_unstaged_changes` |
| P3 | Prepare modified, deleted and untracked files; confirm single/all discard | Backups precede writes; staged contents survive; unselected files survive a single discard | `test_worktree_discard.py` |
| P4 | Create/switch branches, merge, revert and delete a merged branch; use a temporary bare remote to push/fetch/pull | Separate previews, retained history, correct tracking and fast-forward behavior | `test_create_switch_and_safe_delete`, `test_revert_preserves_history`, merge tests, `test_push_fetch_and_fast_forward_pull` |
| P5 | Save staged, unstaged and untracked content; inspect an index-only stash; apply then delete a stash | All saved snapshots are inspectable; application restores staging and keeps the record; deletion identifies the record | `test_stash_roundtrip_preserves_index_untracked_files_and_original_record`, stash preview tests, `workbench.test.cjs` and index-only UI fixture |
| N1 | Change a file after preview, expire a token, or use a different task's token | Apply is rejected without changing the repository | `test_stale_preview_same_status_code_and_cross_task_are_rejected`, `test_expired_and_wrong_repo_tokens_are_rejected` |
| N2 | Try deleting the current, unmerged or another worktree's checked-out branch | Branch is retained and a reason is shown | `test_unmerged_current_and_checked_out_branch_not_deleted` |
| N3 | Open a task with missing project metadata or a non-Git directory | Explain the missing context or repository and offer manual selection; never choose another task's project | `test_project_context.py` |

These are reproducible review scenarios, not a record of an OpenAI review. Publisher verification, accepted local MCP packaging, listing assets, legal URLs and availability selections remain part of the eventual submission.

## Submission readiness

These findings concern the public directory package, not the operation of the existing local release. Check the [current manifest reference](https://developers.openai.com/plugins/deploy/submission#manifest-fields) again when OpenAI confirms the distribution route.

| Item | Current state / next step |
| --- | --- |
| Local MCP eligibility | Requires confirmation for local stdio, filesystem access and the Codex thread entrypoint. |
| Publisher identity | Must be selected and verified in the owning OpenAI organization; GitHub ownership alone does not establish verification. |
| Listing subtitle | Current `interface.shortDescription` exceeds the documented 30-character submission limit; shorten for a submission package. |
| Listing and composer icons | `interface.logo` and `interface.composerIcon` are absent; add square assets at least 48 × 48 before submission. |
| Public listing URLs | Website and privacy URLs exist. Add support and terms URLs for MCP review; review terms with the publisher rather than treating MIT as a complete service policy. |
| Review material | The scenarios above are prepared. A demo recording, supported platforms and any required reviewer setup still need completion. Existing screenshots use disposable repositories in a local MCP development host. |
| Portal access | The portal required sign-in in the checked browser session; organization permissions, identity and draft availability were not inspected. |

Do not replace the local MCP declaration with a placeholder remote URL or remove it to make an incomplete skills-only package pass validation. Keep the published v0.5.2 archive and tag intact; build any accepted submission package as a separate version.

## Draft request for local MCP distribution support

This request has been prepared but not sent. Use an OpenAI contact or an official support channel; no recipient or application ID is assumed.

Subject: Local MCP public directory eligibility — Git Branch Explorer for Codex

Hello OpenAI team,

I maintain Git Branch Explorer, an MIT-licensed plugin that runs a Python stdio MCP service on the user's computer and renders a Git workbench in the Codex side panel. The plugin needs the current task's local repository, index, working tree, hooks and Git credentials. It does not require a maintainer-operated cloud service or modify Codex application files.

Could you confirm the supported public-directory submission route for this local MCP architecture, and any requirements for filesystem access, the thread panel entrypoint and local project-context discovery? A centrally hosted endpoint would not provide the same local workflow. I would like to preserve these capabilities rather than submit a package containing only the skill.

Source: https://github.com/Winlifes/codex-git-branch-explorer

Release and portable ZIP: https://github.com/Winlifes/codex-git-branch-explorer/releases/tag/v0.5.2

Reviewer scenarios and data handling are documented in this repository. v0.5.2 validation passed 81 Python and 19 Node tests. Git writes require explicit confirmation of a concrete preview; discarding local edits first creates backups and preserves staging.

Thank you for confirming whether local MCP publication is supported for this project and what review steps are required.
