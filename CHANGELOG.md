# Changelog

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
