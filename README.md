# Git 分支浏览器

在 Codex 右侧面板查看 Git 分支、提交历史和文件差异，并通过预览确认执行 Git 操作。

A local Git workspace and history panel for Codex Desktop. Browse branches, commits and diffs, then preview and confirm repository changes.

这是独立开发的第三方插件，目前通过本仓库分发，尚未上架 OpenAI 官方插件目录。无需修改 Codex 本体。

## 安装

需要 Git、Python 3.9+ 和支持 MCP thread entrypoints 的 Codex 桌面客户端。当前已在 macOS、客户端附带 CLI `0.154.0-alpha.6.2` 上验证；其他平台与版本尚未完成兼容验证。

从 [Releases](https://github.com/Winlifes/codex-git-branch-explorer/releases) 下载安装包并解压，在插件目录执行：

```sh
python3 scripts/install.py
```

也可以克隆源码安装：

```sh
git clone https://github.com/Winlifes/codex-git-branch-explorer.git
cd codex-git-branch-explorer
python3 scripts/install.py
```

安装器将插件复制到 `~/plugins/git-branch-explorer`，配置本机 MCP 启动路径，再注册并安装到个人插件市场。无需第三方 Python 包、npm、API Key 或云端服务。若找不到 `codex` 命令，会显示可手动执行的安装命令。

在现有任务或新任务中，打开右侧面板，点击 **＋ → Git 分支**。若安装后入口未出现，等正在运行的任务完成，再退出并重新打开 Codex，然后回到原任务。

尚未发送消息的新任务可能无法提供项目目录。面板会提示检查消息状态；发送消息后关闭并重新打开 Git 分支，或手动选择仓库。已有任务可以继续使用。

**已安装用户：** 安装器不会覆盖已有插件目录。重复从其他目录安装时会停止并说明原因；请保留现有源码，按 [更新说明](docs/architecture.md#验证与更新) 操作。当前不支持自动更新。

## 功能

- 本地和远程跟踪分支、当前分支、提交搜索、分页历史与逐文件差异。
- 提交显示完整日期时间，以及新增、删除行数；合并提交可选择父提交查看差异。
- 工作区按文件或批量暂存、取消暂存；只提交暂存区内容。
- 单文件或全部撤回未暂存改动，保留暂存区内容，撤回前保存本地备份。
- 创建、切换、合并分支，撤销提交，以及删除已合并的本地分支。
- 获取、快进拉取和普通推送；冲突解决后可继续或中止合并/撤销。
- 随 Codex 切换浅色与深色主题，使用统一下拉菜单、滚动条和窄面板布局。

浏览分支不会 checkout，刷新不会 fetch。每次写操作先显示预览；确认凭据有效期为 5 分钟，执行前重新核对仓库状态。暂不提供强制推送、硬重置、强制删除或删除远程分支。

撤回备份位于对应工作树的 Git 数据目录下 `codex-git-explorer/discard-backups/`。界面显示实际位置，`manifest.json` 对应原路径及备份内容；备份不会自动删除，可据此手动恢复。

## English quick start

Install Git, Python 3.9+ and a Codex Desktop build supporting MCP thread entrypoints. Clone this repository or extract a release, then run `python3 scripts/install.py`. Open the right panel and select **+ → Git 分支**. Reload Codex if the installed entry is missing. The interface currently uses Chinese.

Git runs locally using your existing identity, credentials, hooks and signing configuration. Repository writes require an explicit preview and confirmation in the panel. The plugin does not run a developer-hosted cloud service or collect telemetry. See [Privacy](PRIVACY.md) for data handling and [architecture and limitations](docs/architecture.md) for compatibility details.

## 开发与测试

```sh
python3 -m unittest discover -s tests -v
python3 scripts/build_release.py
```

写操作测试使用临时仓库和本机临时远程。构建产物位于 `dist/`，包含 ZIP 与 SHA-256 校验文件；构建器仅收集插件代码、测试和公开文档，不包含 Git 历史或本机安装配置。

## 文档和支持

- [功能、实现与兼容性](docs/architecture.md)
- [数据与隐私](PRIVACY.md)
- [发布记录](CHANGELOG.md)
- [OpenAI 上架准备与复现场景](docs/openai-submission.md)
- [问题反馈](https://github.com/Winlifes/codex-git-branch-explorer/issues)

反馈时请使用可分享的示例，不要附上凭据、私有源码或包含敏感路径的完整日志。

## 授权

目前公开源码和安装包，暂未附加开源许可证。
