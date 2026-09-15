"""Explicit, previewed Git operations for the native panel. No shell commands."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit, urlunsplit

from git_explorer import GitError, Repository, decode, MAX_PATCH
from worktree_discard import prepare_discard, create_backup, remove_untracked

ACTIONS = ("switch", "create", "stage", "unstage", "discard", "commit", "fetch", "pull", "push",
           "merge", "revert", "delete", "continue", "abort")
FIELDS = {
    "switch": {"ref"}, "create": {"ref", "name", "checkout"},
    "stage": {"paths"}, "unstage": {"paths"}, "discard": {"paths", "all"}, "commit": {"message"},
    "fetch": {"remote"}, "pull": {"remote", "branch"},
    "push": {"remote", "branch", "set_upstream"}, "merge": {"ref"},
    "revert": {"sha", "mainline"}, "delete": {"ref"}, "continue": set(), "abort": set(),
}


def run(repo, *args, input_data=None, check=True):
    # Preserve the user's identity, credential helpers, signing and hooks. Make
    # editors and terminal authentication noninteractive; do not bypass hooks.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_EDITOR="true", GIT_SEQUENCE_EDITOR="true",
               GCM_INTERACTIVE="never", LC_ALL="C")
    command = ["git", "--no-pager", "-C", repo.path, "-c", "color.ui=false",
               "-c", "core.quotePath=false", "-c", "core.fsmonitor=false", *args]
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = subprocess.Popen(command, stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
                                   stdout=out, stderr=err, env=env, start_new_session=os.name != "nt")
        try:
            process.communicate(input_data, timeout=55)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.communicate()
            raise GitError("Git 操作超时，结果可能已部分生效。请刷新检查后再操作；需要交互认证时请先在终端完成认证。")
        out.seek(0); err.seek(0)
        stdout, stderr = out.read(24 * 1024 * 1024 + 1), err.read(24 * 1024 * 1024 + 1)
        if len(stdout) > 24 * 1024 * 1024 or len(stderr) > 24 * 1024 * 1024:
            raise GitError("Git 输出过大，请刷新检查仓库状态。")
        if check and process.returncode:
            raise GitError(safe_output(decode(stderr or stdout).strip()) or "Git 操作未完成。")
        return stdout if check else (process.returncode, stdout, stderr)


def safe_output(value):
    # Remotes and Git errors may contain URL credentials. Never show them in UI.
    value = re.sub(r"([a-z][a-z0-9+.-]*://)[^/@\s]+@", r"\1***@", value, flags=re.I)
    return re.sub(r"(https?://[^\s?'\"<>]+)\?[^\s'\"<>]*", r"\1?…", value, flags=re.I)[:6000]


def remote_url(value):
    value = safe_output(value)
    if "://" in value:
        try:
            p = urlsplit(value)
            return urlunsplit((p.scheme, p.netloc, p.path, "", ""))
        except ValueError:
            return "（远程地址格式无效）"
    return value


def git_path(repo, name):
    path = Path(decode(repo.git("rev-parse", "--git-path", name)).strip())
    return path if path.is_absolute() else Path(repo.path) / path


def branch_name(repo, name):
    if (not isinstance(name, str) or not name or len(name) > 240 or name.startswith(("-", "/"))
            or name == "HEAD" or "\0" in name or "@{" in name):
        raise GitError("请输入有效的分支名称。")
    run(repo, "check-ref-format", "refs/heads/" + name)
    return name


def status(repo):
    info = repo.info()
    if repo.bare:
        return {"repository": info, "changes": [], "remotes": [], "operation": None,
                "clean": True, "staged_count": 0, "unstaged_count": 0, "conflict_count": 0,
                "fingerprint": "bare", "writable": False}
    raw = run(repo, "--no-optional-locks", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames")
    changes, stat_data = [], []
    for record in raw.split(b"\0"):
        if not record:
            continue
        if len(record) < 4 or record[2:3] != b" ":
            raise GitError("无法读取工作区文件状态。")
        xy, path_bytes = record[:2].decode("ascii"), record[3:]
        try:
            path, operable = path_bytes.decode("utf-8"), True
        except UnicodeDecodeError:
            path, operable = decode(path_bytes), False
        conflict = xy in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
        changes.append({"path": path, "index_status": xy[0], "worktree_status": xy[1],
                        "staged": xy[0] not in " ?" and not conflict,
                        "unstaged": xy[1] != " " or conflict, "untracked": xy == "??",
                        "conflict": conflict, "operable": operable})
        try:
            full = os.path.join(os.fsencode(repo.path), path_bytes)
            st = os.lstat(full)
            stat_data.append((path_bytes.hex(), st.st_mode, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns,
                              os.readlink(full).hex() if os.path.islink(full) else None))
            if os.path.isdir(full) and not os.path.islink(full):
                # Submodule commits can change without changing their directory's
                # timestamps or the superproject's porcelain status code.
                nested = Repository(os.fsdecode(full)).info()
                stat_data.append((path_bytes.hex(), nested["head"], nested["current_ref"]))
        except FileNotFoundError:
            stat_data.append((path_bytes.hex(), None))
    operation = next((label for name, label in (("rebase-merge", "rebase"), ("rebase-apply", "rebase"),
                      ("MERGE_HEAD", "merge"), ("REVERT_HEAD", "revert"), ("sequencer", "sequencer"),
                      ("CHERRY_PICK_HEAD", "cherry-pick")) if git_path(repo, name).exists()), None)
    remotes = []
    for name in decode(run(repo, "remote")).splitlines():
        if not name or name.startswith("-"):
            continue
        urls = {}
        for kind, flag in (("fetch_urls", []), ("push_urls", ["--push"])):
            urls[kind] = [remote_url(v) for v in decode(run(repo, "remote", "get-url", *flag, "--all", name)).splitlines()]
        remotes.append({"name": name, **urls})
    upstream = None
    if info["current_ref"]:
        local = info["current_ref"][len("refs/heads/"):]
        _, r, _ = run(repo, "config", "--get", "branch." + local + ".remote", check=False)
        _, b, _ = run(repo, "config", "--get", "branch." + local + ".merge", check=False)
        if r.strip() and b.strip():
            upstream = {"remote": decode(r).strip(), "ref": decode(b).strip()}
    digest = hashlib.sha256(raw)
    digest.update(repo.git("for-each-ref", "--format=%(refname)%00%(objectname)"))
    digest.update(json.dumps([info, stat_data, remotes, upstream, operation], sort_keys=True).encode())
    for name in ("index", "config", "MERGE_HEAD", "REVERT_HEAD", "MERGE_MSG", "sequencer/todo"):
        path = git_path(repo, name)
        if path.is_file():
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    digest.update(chunk)
    return {"repository": info, "changes": changes, "remotes": remotes, "upstream": upstream,
            "operation": operation, "clean": not changes,
            "staged_count": sum(c["staged"] for c in changes),
            "unstaged_count": sum(c["unstaged"] for c in changes),
            "conflict_count": sum(c["conflict"] for c in changes),
            "fingerprint": digest.hexdigest(), "writable": True}


def working_patch(repo, path, staged=False):
    current = status(repo)
    item = next((c for c in current["changes"] if c["path"] == path and c["operable"]), None)
    if not item:
        raise GitError("文件状态已变化，请刷新工作区。")
    if item["untracked"] and not staged:
        full = Path(repo.path) / path
        if full.is_symlink():
            raw = os.readlink(full).encode("utf-8", "replace")
        elif full.is_dir():
            return {"patch": "此路径为嵌套仓库，请进入该仓库查看变更。", "truncated": False}
        else:
            fd = os.open(full, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as f:
                raw = f.read(MAX_PATCH + 1)
        if b"\0" in raw:
            return {"patch": "二进制文件，无法显示文本差异。", "truncated": False}
        return {"patch": "未跟踪文件\n" + "\n".join("+" + line for line in decode(raw[:MAX_PATCH]).splitlines()),
                "truncated": len(raw) > MAX_PATCH}
    raw, truncated = repo.git("diff", *( ["--cached"] if staged else []), "--no-ext-diff", "--no-textconv",
                              "--no-renames", "--no-color", "--", ":(top,literal)" + path,
                              cap=MAX_PATCH, truncate=True)
    return {"patch": decode(raw), "truncated": truncated}


class Operations:
    def __init__(self):
        self.plans = {}
        self.lock = threading.RLock()

    def prepare(self, repo, action, params, owner=""):
        if action not in ACTIONS or set(params) - FIELDS[action]:
            raise GitError("无效的 Git 操作参数。")
        s = status(repo)
        info = s["repository"]
        if not s["writable"]:
            raise GitError("裸仓库仅支持浏览；请打开工作树执行操作。")
        operation = s["operation"]
        if operation and action not in {"stage", "unstage", "continue", "abort", "commit"}:
            raise GitError("请先完成或中止当前 Git 操作。")
        if operation not in (None, "merge", "revert"):
            raise GitError("当前有未完成的 " + operation + "，请在终端处理后刷新。")
        if action in {"switch", "pull", "merge", "revert"} or (action == "create" and params.get("checkout", True)):
            if not s["clean"]:
                raise GitError("当前工作区有未提交的更改，请先提交后再执行此操作。")
        if action in {"commit", "push", "pull", "merge", "revert"} and not info["current_ref"]:
            raise GitError("当前是游离 HEAD，请先创建并切换到本地分支。")
        local = (info["current_ref"] or "游离 HEAD").removeprefix("refs/heads/")
        title, detail, commands, files = "", [], [], []
        target = None
        discard = None
        if action in {"switch", "create", "merge", "delete"}:
            ref = params.get("ref", "HEAD")
            target = repo.oid(ref)
            source = ref.removeprefix("refs/heads/").removeprefix("refs/remotes/")
            if action in {"switch", "delete"} and not ref.startswith("refs/heads/"):
                raise GitError("请选择本地分支。远程分支可作为新建本地分支的起点。")
            if action in {"switch", "delete"} and ref == info["current_ref"]:
                raise GitError("已经位于该分支。" if action == "switch" else "不能删除当前分支。")
            if action == "switch":
                title = "切换到 " + source
                detail = ["工作区将从 " + local + " 切换到 " + source + "。", "目标提交：" + target[:12]]
                commands = [["switch", "--no-guess", "--", source]]
            elif action == "create":
                name = branch_name(repo, params.get("name"))
                if repo.git("show-ref", "--verify", "refs/heads/" + name, optional=True):
                    raise GitError("该本地分支已存在。")
                checkout = params.get("checkout", True)
                if type(checkout) is not bool:
                    raise GitError("无效的切换选项。")
                title = "创建分支 " + name
                detail = ["起点：" + source + " · " + target[:12], "创建后" + ("切换到新分支。" if checkout else "保留当前工作区分支。")]
                commands = [["switch", "--no-track", "-c", name, target] if checkout else ["branch", "--no-track", name, target]]
            elif action == "merge":
                title = "合并到 " + local
                detail = ["来源：" + source + " · " + target[:12], "合并到当前分支 " + local + "；必要时创建合并提交。",
                          "如出现冲突，可在工作区解决后继续，也可中止合并。"]
                commands = [["merge", "--ff", "--no-edit", "--no-autostash", "-m",
                             "Merge branch '" + source + "' into " + local, target]]
            else:
                code, _, _ = run(repo, "merge-base", "--is-ancestor", target, "HEAD", check=False)
                if code != 0:
                    raise GitError("此分支包含尚未合并到当前分支的提交，不能直接删除。请先合并需要保留的提交。")
                title = "删除本地分支 " + source
                detail = ["分支指向：" + target[:12], "已检查其提交包含在当前分支 " + local + " 中。", "只删除本地分支名称，远程分支不受影响。"]
                commands = [["branch", "-d", "--", source]]
        elif action in {"stage", "unstage"}:
            paths = params.get("paths")
            if (not isinstance(paths, list) or not paths or len(paths) > 500
                    or any(not isinstance(p, str) for p in paths) or len(set(paths)) != len(paths)):
                raise GitError("请选择 1 至 500 个不同的文件。")
            key = "unstaged" if action == "stage" else "staged"
            available = {c["path"] for c in s["changes"] if c[key] and c["operable"]}
            if not set(paths) <= available:
                raise GitError("所选文件状态已变化或文件名无法处理，请刷新工作区。")
            files = paths
            title = ("暂存" if action == "stage" else "取消暂存") + " " + str(len(paths)) + " 个文件"
            detail = ["当前分支：" + local, "工作区文件会保留。" if action == "unstage" else "将所选文件的当前内容加入下一次提交。"]
            literals = [":(top,literal)" + p for p in paths]
            commands = [["add", "--", *literals] if action == "stage" else
                        (["restore", "--staged", "--source=HEAD", "--", *literals] if info["head"] else
                         ["rm", "--cached", "-f", "--", *literals])]
        elif action == "discard":
            discard = prepare_discard(repo, s["changes"], params)
            files = discard["paths"]
            title = "撤回 " + str(len(files)) + " 个文件的工作区改动"
            detail = ["当前分支：" + local,
                      "恢复到暂存区中的文件版本；没有暂存改动的文件恢复到当前提交。已暂存的内容会保留。"]
            if discard["untracked"]:
                detail.append(str(len(discard["untracked"])) + " 个未跟踪的新文件将从工作区移除（执行前保存本地备份）。")
            detail.append("执行前会备份所选文件的当前内容。备份保存在本仓库的 Git 数据目录中，完成后显示位置。忽略的文件不受影响。")
            if discard["tracked"]:
                commands = [["--no-optional-locks", "--literal-pathspecs", "restore", "--worktree",
                             "--no-recurse-submodules", "--pathspec-from-file=-", "--pathspec-file-nul"]]
        elif action == "commit":
            message = params.get("message")
            if not isinstance(message, str) or not message.strip() or len(message) > 10000 or "\0" in message:
                raise GitError("请输入提交说明（最多 10000 个字符）。")
            if s["conflict_count"]:
                raise GitError("请先解决冲突并暂存对应文件。")
            if operation == "revert":
                raise GitError("请使用「继续撤销」完成正在进行的操作。")
            if not s["staged_count"] and operation != "merge":
                raise GitError("还没有暂存的更改。")
            title = "提交到 " + local
            detail = ["仅提交暂存区；未暂存文件保持原状。", "提交说明：\n" + message.strip()]
            files = [c["path"] for c in s["changes"] if c["staged"]]
            commands = [["commit", "--file=-"]]
        elif action in {"fetch", "pull", "push"}:
            remote = next((r for r in s["remotes"] if r["name"] == params.get("remote")), None)
            if not remote:
                raise GitError("请选择已配置的远程仓库。")
            name = remote["name"]
            detail = ["远程：" + name, *(remote["push_urls"] if action == "push" else remote["fetch_urls"])]
            if action == "fetch":
                title = "获取远程更新"
                detail.append("更新本地远程跟踪记录，不合并工作区。")
                commands = [["fetch", "--no-recurse-submodules", "--", name]]
            else:
                dest = "refs/heads/" + branch_name(repo, params.get("branch"))
                if action == "pull":
                    title = "拉取到 " + local
                    detail += ["来源分支：" + dest.removeprefix("refs/heads/"), "仅快进更新；分叉时停止，交由你选择合并。"]
                    commands = [["pull", "--ff-only", "--no-rebase", "--no-autostash", "--no-recurse-submodules", "--", name, dest]]
                else:
                    if not info["head"]:
                        raise GitError("请先创建首条提交。")
                    if type(params.get("set_upstream", False)) is not bool:
                        raise GitError("无效的上游选项。")
                    title = "推送 " + local
                    detail += ["目标分支：" + dest.removeprefix("refs/heads/"), "提交：" + info["head"][:12], "将当前本地分支发布到上述远程，不强制覆盖远程历史。"]
                    extra = ["--set-upstream"] if params.get("set_upstream") else []
                    if extra:
                        detail.append("成功后将此远程分支设为当前分支的上游。")
                    commands = [["-c", "remote." + name + ".mirror=false", "push", "--porcelain", "--no-force",
                                 "--no-follow-tags", "--recurse-submodules=no", *extra, "--", name, info["current_ref"] + ":" + dest]]
        elif action == "revert":
            target = repo.oid(params.get("sha", ""))
            code, _, _ = run(repo, "merge-base", "--is-ancestor", target, "HEAD", check=False)
            if code:
                raise GitError("所选提交不在当前分支历史中，请先切换到对应分支。")
            item = repo.commit(target)
            extra = []
            if len(item["parents"]) > 1:
                mainline = params.get("mainline")
                if type(mainline) is not int or not 1 <= mainline <= len(item["parents"]):
                    raise GitError("撤销合并提交时，需要选择保留的父提交主线。")
                extra = ["--mainline", str(mainline)]
                detail.append("保留主线：父提交 " + str(mainline) + " · " + item["parents"][mainline - 1][:12])
            title = "撤销提交 " + target[:7]
            detail += [item["subject"], "在 " + local + " 上创建一条反向提交，保留原有历史。"]
            commands = [["revert", "--no-edit", *extra, target]]
        elif action in {"continue", "abort"}:
            if operation not in {"merge", "revert"}:
                raise GitError("当前没有可继续或中止的合并 / 撤销操作。")
            label = "合并" if operation == "merge" else "撤销"
            title = ("继续" if action == "continue" else "中止") + label
            if action == "continue":
                if s["conflict_count"]:
                    raise GitError("请先解决冲突并暂存对应文件。")
                detail = ["在 " + local + " 上提交当前冲突解决结果。"]
                commands = [["commit", "--no-edit"] if operation == "merge" else ["revert", "--continue"]]
            else:
                detail = ["放弃本次" + label + "过程中尚未提交的修改（包括已编辑的冲突解决结果），恢复到操作开始前。"]
                commands = [[operation, "--abort"]]
            files = [c["path"] for c in s["changes"]]
        now = time.monotonic()
        token = secrets.token_urlsafe(32)
        preview = {"token": token, "action": action, "title": title, "details": detail, "files": files,
                   "repository": info, "expires_in": 300}
        with self.lock:
            self.plans = {k: p for k, p in self.plans.items() if now - p["created"] < 300}
            if len(self.plans) >= 128:
                raise GitError("待确认操作过多，请稍后重试。")
            self.plans[token] = {"created": now, "owner": owner, "repo": repo.path,
                                 "fingerprint": s["fingerprint"], "commands": commands,
                                 "discard": discard,
                                 "input": (b"".join(p.encode("utf-8") + b"\0" for p in discard["tracked"]) if discard else
                                           params.get("message", "").strip().encode() if action == "commit" else None),
                                 "preview": preview}
        return preview

    def apply(self, repo, token, owner=""):
        with self.lock:
            plan = self.plans.get(token)
            if (not plan or time.monotonic() - plan["created"] > 300
                    or plan["repo"] != repo.path or plan["owner"] != owner):
                raise GitError("操作确认已失效，请重新预览。")
            if "result" in plan:
                return plan["result"]  # A lost host response must not duplicate a commit.
            if status(repo)["fingerprint"] != plan["fingerprint"]:
                del self.plans[token]
                raise GitError("仓库状态已变化，已取消本次操作。请刷新并重新确认。")
            # Store a non-repeatable result before starting any mutating process.
            result = {"ok": False, "message": "操作结果暂不明确，请刷新检查。", "action": plan["preview"]["action"]}
            plan["result"] = result
            try:
                if plan["discard"]:
                    result["backup_path"] = create_backup(repo, plan["discard"]["paths"])
                    if status(repo)["fingerprint"] != plan["fingerprint"]:
                        raise GitError("备份期间仓库状态已变化，未执行撤回。请刷新并重新确认。")
                outputs = [decode(run(repo, *cmd, input_data=plan["input"])) for cmd in plan["commands"]]
                if plan["discard"]:
                    discard = plan["discard"]
                    if discard["intents"]:
                        run(repo, "update-index", "--force-remove", "-z", "--stdin",
                            input_data=b"".join(p.encode("utf-8") + b"\0" for p in discard["intents"]))
                    remove_untracked(repo, discard["untracked"], discard["signatures"])
                result.update(ok=True, message=plan["preview"]["title"] + "，已完成。", output=safe_output("\n".join(outputs)))
            except (GitError, OSError) as err:
                result["message"] = safe_output(str(err))
            try:
                result["status"] = status(repo)
                if not result["ok"] and result["status"]["conflict_count"]:
                    result["message"] = "出现合并冲突。请打开工作区处理冲突文件，暂存解决结果后继续，或中止本次操作。\n" + result["message"]
            except (GitError, OSError):
                result["refresh_required"] = True
            return result
