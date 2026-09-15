# 数据与隐私 / Privacy

生效日期：2026-09-15。维护者：[Winlifes](https://github.com/Winlifes)。适用于本仓库发布的 Git 分支浏览器本地插件。

## 插件读取的数据

插件在用户电脑上调用 Git，读取选定仓库的路径、分支、提交作者与时间、提交信息、文件差异、暂存区及工作区状态。为定位当前项目，会只读查询本机 Codex 的任务目录和项目关联，并读取已有消息标记；不读取任务消息正文。

这些查询结果经本地 MCP 传给 Codex 宿主及插件面板。本地运行不表示数据不会传给 Codex；Codex 对数据的处理由用户与 OpenAI 的设置和条款决定。

## 网络与第三方

本插件没有维护者运营的云端数据服务、遥测或分析追踪。面板使用随插件提供的资源。原生模式无需 HTTP 端口。

用户确认获取、拉取或推送后，Git 会连接所选仓库中已经配置的远程地址。远程服务可接收相应 Git 数据及认证请求。插件使用已有 Git 凭据、签名和钩子配置；这些辅助程序由本机配置决定。

从 GitHub 下载、克隆或提交问题时，GitHub 会按其自身服务规则处理这些交互。公开 Issue 中提交的内容会对外可见，请勿发送私有仓库内容或凭据。

## 本地备份

撤回工作区改动前，插件将文件内容、原路径、文件模式或符号链接目标保存在该工作树 Git 数据目录的 `codex-git-explorer/discard-backups/` 中。备份不上传给维护者，也不会自动删除。操作结果会显示备份位置；用户可手动恢复或删除这些备份。

操作预览和确认凭据保存在 MCP 进程内存中，预览有效期为 5 分钟。已完成操作的结果会在进程内暂存以避免重复执行；进程退出后不保留该内存状态。

## 联系

有关此说明的问题可通过[仓库 Issue](https://github.com/Winlifes/codex-git-branch-explorer/issues)提出。需要讨论敏感内容时，先请求合适的私密联系渠道，不要将敏感内容放入公开 Issue。

## English

The plugin runs Git locally and reads the selected repository's paths, branches, commit metadata, file diffs, index and working tree. It also reads local Codex task/project metadata and message-presence flags to identify the active project, without reading message bodies.

Query results are passed to the Codex host and panel through MCP. There is no maintainer-operated cloud service, telemetry or analytics. Confirmed Git remote operations use the repository's configured remotes and the user's Git credentials, hooks and signing settings.

Discard operations create local backups under the worktree's Git metadata directory. These backups contain file data and paths, are not sent to the maintainer and are not deleted automatically. Users can restore or delete them manually. GitHub downloads and public issue submissions are handled by GitHub; never post private code or credentials in an issue.
