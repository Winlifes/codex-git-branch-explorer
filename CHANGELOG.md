# Changelog

## 0.7.1 — 2026-10-14

- Allow fast-forward pulls with uncommitted changes when Git can retain them. Remove the blanket clean-worktree requirement for pull; keep preview confirmation and state-change checks.
- Preview the presence of local changes and let Git reject tracked/untracked files that would be overwritten. Show the affected paths with guidance; report diverged history separately. Do not auto-stash, commit, discard or rebase local changes.

## 0.7.0 — 2026-10-12

- When a commit message is empty or whitespace-only, open an editable draft based on local file changes, line counts and recognized symbols/configuration keys. Selected-file drafts use the worktree; staged drafts use index blobs.
- Keep edited messages and cancelled drafts. Re-preview after editing before applying a commit, and save the confirmed message through existing Git hooks/signing.
- Bound content inspection for large changes and mark partial summaries; never call external AI services or stage/commit while generating drafts.

## 0.6.0 — 2026-10-12

- Add creation of GitHub repositories from projects without Git: account confirmation, private/public visibility, name/description, initial branch, ignore templates, and optional first commit/upload.
- Preview exact upload paths, retain existing ignore rules, exclude common credential files, links and nested repositories from initial upload, and reject oversized files before initialization.
- Recheck account, Git identity and files before applying; bind short-lived previews and progress jobs to the calling task. Show completed steps after failures without automatic retries or deletion.
- Use the official GitHub CLI for authentication/API requests and a repository-local credential helper for initial and subsequent Git operations; keep tokens out of the panel and retain existing signing/hooks.

## 0.5.2 — 2026-10-12

- Show a stash's index, working-tree and untracked snapshots separately, so index-only changes and different staged/unstaged versions of one file remain inspectable before applying or deleting a stash.
- Restore the stable panel resource URI so cached project entrypoints match fresh tool discovery. A changed URI in v0.5.1 could cause Codex to revoke the iframe before loading it and leave the host spinner visible.
- Keep the alignment and contrast improvements; retain the v0.5.1 resource as a readable alias.
- Add regression coverage for resource identity compatibility with existing project tabs.

## 0.5.1 — 2026-10-12

- Align change groups, folder/file rows and 16 px checkboxes with consistent indentation.
- Improve checkbox borders, checked/mixed indicators and button text contrast in light, dark and host themes.
- Give disabled actions neutral backgrounds, explain empty file selection and clarify the two commit actions.
- Wrap workspace toolbars and commit buttons within narrow panes; retain the previous UI resource for existing tabs.

## 0.5.0 — 2026-10-12

- Add Rider-inspired Log, Commit and Stashes tabs, compact commit rows, colored topology graphs, tag browsing and resizable panes.
- Replace the workspace modal with a persistent directory tree, folder/file checkboxes and a bottom commit composer.
- Add previewed selected-file commits that preserve unrelated index and working-tree content; retain staged-only commits.
- Add stash creation, inspection (including untracked files), index-preserving application and deletion previews; fingerprint stash reflog changes.
- Add numbered unified/side-by-side working diffs, expanded history diffs, keyboard navigation and responsive layouts.
- Extend read-only workspace/stash routes and bundle all UI modules into the self-contained MCP resource.

## 0.4.0 — 2026-09-22

- Group local and remote branches into collapsible folders by `/`, preserving full refs for history and operations.
- Remember expansion per repository; automatically expand matching paths while searching and restore the previous state afterward.
- Add folder counts, a current-branch indicator, keyboard tree navigation and more room for branch names, using the existing Codex theme and localization.
- Add branch tree regression tests and current English/Chinese runtime screenshots.

- 按 `/` 将本地与远程分支组织为可折叠文件夹，历史浏览和操作保留完整引用。
- 按仓库记住展开状态，搜索时自动展开匹配路径，清空后恢复。
- 添加目录分支数量、当前分支标记、键盘导航，增加分支名显示空间，沿用 Codex 主题和语言同步。
- 补充分支树回归测试与中英文运行截图。

## 0.3.0 — 2026-09-16

- Follow the Codex language with English and Simplified Chinese UI, localized dates/numbers, and an English fallback for other languages.
- Update open menus, previews and errors live while preserving drafts, selections and Git data. Language changes do not repeat Git requests.
- Localize MCP tool metadata when the host supplies a locale; use the neutral native entry label `Git` otherwise.
- Add localization regression coverage, bilingual documentation and current English/Chinese runtime screenshots.

- 跟随 Codex 语言切换英文与简体中文，覆盖日期、数字、菜单、预览和错误提示；其他语言回退为英文。
- 实时切换保留输入、选项与 Git 原始内容，不重复发送 Git 请求。
- MCP 元数据使用宿主提供的语言；没有语言信息时，原生入口显示通用名称 `Git`。
- 补充本地化回归验证、中英文文档及新版运行截图。

## 0.2.1 — 2026-09-15

- 添加 MIT 开源许可证，版权归属 Winlifes。
- 在插件清单、README 和上架准备文档中声明 MIT 授权。
- 更新发布包并包含完整 `LICENSE` 文件。

## 0.2.0 — 2026-09-15

首次通过公共 Git 仓库分发。

- 在 Codex 右侧面板打开本地 Git 分支、历史和差异。
- 提交列表显示具体时间及增删行数。
- 统一主题菜单、滚动条、图标和窄面板布局。
- 显示任务消息与项目定位状态，支持现有任务和手动选择仓库。
- 通过预览确认暂存、提交、分支管理、合并、撤销与远程 Git 操作。
- 支持单文件及全部撤回未暂存改动，撤回前备份并保留暂存区。
- 提供可移植安装器、文档和可复现的发布包构建命令。

当前通过本仓库分发，尚未在 OpenAI 官方插件目录发布。本地 MCP 的公开上架方式仍需 OpenAI 确认。
