# Git Branch Explorer

**English** · [简体中文](README.zh-CN.md)

Browse Git branches, commit history and file diffs in the Codex right panel. Manage your working tree and branches with a preview before every change.

[Download](https://github.com/Winlifes/codex-git-branch-explorer/releases/latest) · [Report an issue](https://github.com/Winlifes/codex-git-branch-explorer/issues) · [MIT License](LICENSE)

![English UI: branch folders, current branch and commit history](docs/screenshots/branch-folders-en.jpg)

*The v0.5.0 workbench captures use the disposable Unity demo repository `orbit-studio` in a local MCP development host. Older captures remain below for reference. The panel follows the Codex language automatically.*

![Dark workbench: branch tree, commit graph and file details](docs/screenshots/workbench-log-dark.jpg)

This is an independently developed, third-party plugin distributed through this repository. It is not currently listed in the official OpenAI plugin directory. Installation does not modify the Codex application.

[Features](#features) · [Install](#install) · [Screenshots](#screenshots) · [How operations work](#how-operations-work) · [Compatibility](#compatibility) · [Development](#development)

## Features

| Area | What you can do |
| --- | --- |
| Branches | Browse local and remote-tracking branches in collapsible folders, search full branch paths, identify the current branch and see upstream ahead/behind status. |
| History | Compact commit rows with a colored topology graph, ref badges, authors, dates and hashes; pagination, search and first-parent filtering. |
| Commit details | See the full message, author, SHA, date and time, added/deleted line counts, changed files and per-file diffs. Choose a parent for merge commit diffs. |
| Working tree | Persistent Commit tab with directory checkboxes, tracked/untracked groups, staging controls and a bottom composer; commit selected files or staged content. |
| Stashes | Inspect staged, working-tree and untracked snapshots separately; save changes, apply while retaining the record, or preview deleting a stash. |
| Layout and diffs | Resizable branch/details panes, unified or side-by-side working diffs with line numbers, expanded history diffs and responsive narrow layouts. |
| Discard changes | Discard one file's or all files' unstaged changes while preserving the index. Local backups are created before discarding. |
| Branch operations | Create, switch and merge branches; revert commits with a new reverse commit; delete merged local branches. |
| Remotes and conflicts | Fetch, pull with fast-forward only, push without force and set an upstream. Stage resolved conflicts, then continue or abort a merge/revert. |
| New projects | Initialize a project without Git, confirm the GitHub account, choose private/public visibility and ignore rules, then create an empty repository or commit and upload reviewed files. |
| Appearance | Follow the Codex theme or select light/dark mode, with themed menus, thin scrollbars and a branch drawer for narrow panels. |
| Language | Follow the Codex language with English and Simplified Chinese UI, including menus, previews, errors, dates and number formatting. Live changes preserve drafts and selections. |

Selecting a branch changes the history you are browsing; it does not check it out. **Refresh** rereads local Git data; use **Fetch** to update remote-tracking branches.

### Branch folders

Branch names are grouped by `/`: `codex/card-collection` appears inside **codex**, and `codex/fixes/scrollbars` appears inside **codex → fixes**. Remote-tracking branches are grouped under their remote, such as **origin**. Names without `/` stay at the group root.

- Click a folder to expand or collapse it. Counts include all branches below it; a dot marks folders containing the current branch.
- Expansion is remembered separately for each repository when local storage is available. On first opening, the current branch's path is expanded.
- Search matches the full branch name and temporarily expands matching paths. Clearing the search restores your previous folder state.
- Use **↑/↓** to move, **→/←** to expand or collapse and move between levels, **Home/End** to jump, and **Enter/Space** to open a folder or browse a branch. Hover a branch to see its full name.

## Create a GitHub repository for a new project

When the current project is not a Git repository, choose **Create GitHub repository** in the empty-state page. Confirm the account, repository name, description, visibility (private by default), initial branch, ignore rules, and whether to upload an initial commit. Existing `.gitignore` content is retained. Common, Unity, Node.js, and Python templates are available.

![Creation form with a demo account and private visibility selected by default](docs/screenshots/github-create-dark.jpg)

The preview shows the target account/repository and exact upload paths. Public uploads require an explicit confirmation of the listed files. Common credential filenames, symlinks, and nested repositories are excluded from this initial upload; this is not a full secret-content scan. Files at or above 100 MiB are blocked before initialization. Only reviewed files are staged; the user's Git author identity, signing, and hooks remain in use.

This optional feature needs the official [GitHub CLI](https://cli.github.com/), signed in with [gh auth login](https://cli.github.com/manual/gh_auth_login). The panel detects missing or expired authentication and provides the command to run. Account switching requires a new confirmation. The plugin never accepts or displays account tokens.

Creation progress is shown while it runs. Completed local/remote steps are retained after a failure; the plugin never automatically repeats a creation request or deletes the new repository. On success, `origin` is connected and the optional initial upload sets the upstream branch. A GitHub CLI credential helper is configured only in the new repository for subsequent fetch/pull/push operations. The new repository opens in the Git panel. If only an empty repository was requested, no project files are staged, committed, or pushed.

## Install

### Requirements

- Git and Python **3.9+**.
- Optional: GitHub CLI for creating new GitHub repositories. Existing Git workflows do not need it.
- Codex Desktop with support for **MCP thread entrypoints**. Validated on macOS with the desktop-bundled Codex CLI `0.154.0-alpha.6.2`; other versions and platforms have not been verified.

No third-party Python packages, npm, API key or developer-hosted cloud service are required.

### From this repository

```sh
git clone https://github.com/Winlifes/codex-git-branch-explorer.git
cd codex-git-branch-explorer
python3 scripts/install.py
```

Alternatively, download and extract a ZIP from [Releases](https://github.com/Winlifes/codex-git-branch-explorer/releases/latest), then run `python3 scripts/install.py` from the extracted plugin directory.

The installer copies the plugin to `~/plugins/git-branch-explorer`, configures the local MCP launch path, registers it in your personal plugin marketplace and runs `codex plugin add`. If it cannot find the Codex CLI, it prints the command to run manually.

### Open the panel

1. Open an existing or new Codex task for your Git project.
2. Open the right panel, click **＋**, then select **Git**. Hosts that provide a language during tool discovery may label it **Git Branches** or **Git 分支**.
3. Select a branch to browse its history. Open **Working tree** to inspect and manage local changes.

If the entry is missing after installation, let running tasks finish, quit and reopen Codex, then return to your task. Existing tasks are supported; there is no need to recreate them.

The plugin uses the current task's project directory when available, including its worktree. A new task may not expose that directory before its first message. The panel then displays message/context checks: send a message, close and reopen the Git panel, or choose a repository manually. Once the project directory is available, the panel checks it for Git repositories and shows any specific error.

### Language

The panel uses the language supplied by Codex. English locales use English UI; Chinese locales use Simplified Chinese UI. Other languages currently fall back to English. If the host does not supply a locale, the panel uses the host's HTML language or the browser language.

When Codex sends a language change, open menus, error messages and confirmation previews update in place. Commit drafts, form values and selections stay intact; switching language does not repeat Git requests. Branch names, commit messages, authors, paths and file contents remain exactly as stored in Git. Dates and numbers follow the selected locale, with times shown in the local time zone.

The native tab label is controlled and may be cached by Codex. After installing an update, close and reopen the Git panel to load its new UI.

### Existing installations

Updates are manual. The installer stops if `~/plugins/git-branch-explorer` already exists and is different from the installation source, so running it from another checkout does not overwrite your files. The current developer update workflow is described in [Architecture: validation and updates (Chinese)](docs/architecture.md#验证与更新).

## Screenshots

### Commit details in dark mode

Inspect the commit metadata and changed files alongside a text diff. Commit rows show added and deleted line counts and the local date/time; the time tooltip includes seconds and the time zone.

![Dark theme: commit metadata, changed files and a JavaScript diff](docs/screenshots/commit-diff-dark.jpg)

<details>
<summary><strong>Working tree: staged and unstaged files</strong></summary>

Stage or unstage individual files, use the bulk actions, and write a message to preview a commit. Only staged content is committed.

![Working tree with three unstaged files, one staged file and commit controls](docs/screenshots/workspace-light.jpg)

</details>

<details>
<summary><strong>Discard preview: review the exact affected files</strong></summary>

The confirmation lists the repository, current branch and affected paths. Staged changes are preserved, and current file contents are backed up before the discard runs.

![Discard confirmation for three demo files, explaining index preservation and backups](docs/screenshots/discard-preview.jpg)

</details>

## How operations work

Every write operation first shows a concrete preview. Confirmation tokens expire after five minutes, and the plugin rechecks the repository state before execution. If the state changes, generate and confirm a new preview.

![Editable draft generated for two C# files in a disposable demo repository](docs/screenshots/commit-message-draft-dark.jpg)

- **Commit selected** includes every current change in the selected files while preserving other staged and unstaged files. The preview lists exact paths. If a hook fails, refresh to inspect the selected files' index state.
- **Commit staged** includes only staged content, preserving unstaged edits in the same file. Both modes use your existing identity, credentials, hooks and signing configuration.
- **Draft a message**: when the message is empty or whitespace-only, either commit button opens an editable local draft based on that commit's files, line changes, and recognized code symbols or configuration keys. No external AI service is called. Edit it, choose **Preview commit**, review the scope and message, then **Confirm commit**. Cancelling retains the draft. Large or numerous files are marked as partially summarized. Existing messages open the preview directly and remain editable; editing requires a refreshed preview before confirmation.
- **Stash changes** can include untracked files. Applying requires a clean working tree, restores the index and retains the stash. Deletion previews identify the exact record.
- **Discard** applies to unstaged changes. Partially staged files are restored to their index version. To discard staged edits, unstage them first.
- **Untracked files** are backed up, then removed only at the exact paths listed in the preview. Ignored files are excluded; submodules, nested repositories and conflicted paths require separate handling.
- **Switch, merge, pull and revert** require a clean working tree. Pull is fast-forward only; branch deletion is limited to local branches merged into the current branch.
- **Revert** creates a reverse commit and preserves history. Hard reset, force push, force deletion and remote branch deletion are not available.

Discard backups are stored under `codex-git-explorer/discard-backups/` inside the worktree's Git metadata directory. The result shows the actual location. Each backup's `manifest.json` maps original paths, file modes and symlink targets to the saved data. Backups are retained for manual recovery; they are not deleted automatically.

## Compatibility

- The native panel entry and automatic project lookup depend on the Codex client's MCP entrypoint support and local metadata formats. These may vary between versions. A manual repository picker is available when project context cannot be resolved.
- There is currently no application-level keyboard shortcut for opening this plugin panel.
- Worktrees, repository subdirectories, empty repositories and detached HEAD are supported. Bare repositories are read-only.
- Remote-tracking branches reflect the last fetch. Shallow clones expose only locally available history.
- Binary files show a diff notice. Renames appear as deletion/addition, and individual text diffs larger than 800 KB are truncated with a notice.
- Git operations that need interactive authentication or signing may need to be completed in a terminal. After an operation timeout, refresh to inspect the state before attempting another operation.

## Data and privacy

Git runs locally. Repository queries and project metadata are passed to the Codex host and panel through MCP. The plugin has no maintainer-operated data service, telemetry or analytics. Confirmed remote operations use your repository's configured Git remotes; Git hooks and credential helpers follow your local configuration. See [Privacy](PRIVACY.md) for details.

## Development

Run the test suite and build a portable release archive:

```sh
python3 -m unittest discover -s tests -v
node --test tests/*.test.cjs
python3 scripts/build_release.py
```

Node.js 18+ is needed only for the branch tree tests, not to run the plugin. These tests cover folder grouping, ref identity, search and per-repository expansion preferences. Write-operation tests use disposable repositories and local bare remotes. The build creates a ZIP and SHA-256 checksum in `dist/`, including both READMEs and the screenshots. Git history and local installation configuration are excluded.

A standalone, read-only browser mode is also available for debugging:

```sh
python3 scripts/git_explorer.py start --repo "/path/to/your/repository"
```

It prints a temporary localhost URL. Browser mode can inspect the working tree and stashes; all write controls remain disabled. Git mutations require the MCP panel environment.

## Documentation and support

- [Chinese README](README.zh-CN.md)
- [Architecture, implementation and detailed limitations (Chinese)](docs/architecture.md)
- [Privacy](PRIVACY.md)
- [Changelog](CHANGELOG.md)
- [OpenAI directory review preparation](docs/openai-submission.md)
- [Screenshot capture notes](docs/screenshots/README.md)
- [Report a bug or request a feature](https://github.com/Winlifes/codex-git-branch-explorer/issues)

When reporting a problem, include your operating system, Codex version and steps using a shareable example. Keep credentials, private source code and sensitive paths out of public issues.

## License

[MIT](LICENSE) · Copyright (c) 2026 Winlifes.
