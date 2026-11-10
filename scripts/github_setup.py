"""Previewed GitHub bootstrap for a directory that is not yet a Git repository.

GitHub authentication stays in the official gh CLI. No token enters the panel.
Creation runs as a polled job: network failures never cause an automatic retry.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

from git_explorer import GitError, decode
from git_operations import run, safe_output, branch_name
from i18n import ui

BASE_IGNORE = """# GitHub project: local files
.DS_Store
Thumbs.db
.env
.env.*
!.env.example
!.env.sample
!.env.template
*.pem
*.p12
*.pfx
*.key
.npmrc
.pypirc
credentials.json
service-account*.json
"""
TEMPLATES = {
    "existing": "",
    "common": BASE_IGNORE,
    "unity": BASE_IGNORE + "\n# Unity generated files\n/[Ll]ibrary/\n/[Tt]emp/\n/[Oo]bj/\n/[Bb]uild/\n/[Bb]uilds/\n/[Ll]ogs/\n/[Uu]ser[Ss]ettings/\n/.vs/\n*.csproj\n*.sln\n",
    "node": BASE_IGNORE + "\n# Node generated files\nnode_modules/\ndist/\nbuild/\ncoverage/\n.next/\n.nuxt/\n*.log\n",
    "python": BASE_IGNORE + "\n# Python generated files\n__pycache__/\n*.py[cod]\n.venv/\nvenv/\n.pytest_cache/\n.mypy_cache/\ndist/\nbuild/\n*.egg-info/\n",
}
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
LOGIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}\Z")
MAX_FILE = 100 * 1024 * 1024
MAX_FILES = 20000


def find_gh():
    candidates = [shutil.which("gh"), "/opt/homebrew/bin/gh", "/usr/local/bin/gh", str(Path.home() / ".local/bin/gh")]
    if os.name == "nt" and os.environ.get("ProgramFiles"):
        candidates.append(str(Path(os.environ["ProgramFiles"]) / "GitHub CLI/gh.exe"))
    return next((value for value in candidates if value and Path(value).is_file()), None)


def project_path(value):
    if not isinstance(value, str) or "\0" in value or len(value) > 8192 or not Path(value).expanduser().is_absolute():
        raise GitError(ui("请输入项目的绝对路径。"))
    path = Path(value).expanduser().resolve()
    if not path.is_dir() or path.parent == path or path == Path.home().resolve():
        raise GitError(ui("请选择具体的项目目录，不能使用主目录或磁盘根目录。"))
    # Refuse existing repositories, worktrees, bare repos and subdirectories of
    # any repository. Never turn an existing repository into a second project.
    if os.path.lexists(path / ".git") or not run(SimpleNamespace(path=str(path)), "rev-parse", "--git-dir", check=False)[0]:
        raise GitError(ui("该目录已属于 Git 仓库，请打开已有仓库。"))
    return path


class GithubClient:
    def __init__(self, executable=None):
        self.executable = executable or find_gh()

    def request(self, endpoint, payload=None, missing_ok=False):
        self.executable = self.executable or find_gh()
        if not self.executable:
            raise GitError(ui("未安装 GitHub CLI。请安装 gh 后重新检查。"), "gh_missing")
        command = [self.executable, "api", "--hostname", "github.com", "--include", "--method",
                   "POST" if payload is not None else "GET", endpoint]
        if payload is not None:
            command += ["--input", "-"]
        env = {key: value for key, value in os.environ.items() if key not in {"GH_DEBUG", "DEBUG"}}
        env.update(GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1", NO_COLOR="1")
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            process = subprocess.Popen(command, stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
                                       stdout=out, stderr=err, env=env)
            try:
                process.communicate(json.dumps(payload).encode() if payload is not None else None, timeout=25)
            except subprocess.TimeoutExpired:
                process.kill(); process.communicate()
                raise GitError(ui("GitHub 请求超时，请检查实际结果后再操作。"))
            out.seek(0); err.seek(0)
            raw, diagnostic = out.read(1024 * 1024 + 1), err.read(6000)
        if len(raw) > 1024 * 1024:
            raise GitError(ui("GitHub 返回的数据过大。"))
        match = re.match(rb"HTTP/\S+ (\d+)", raw)
        code = int(match[1]) if match else None
        if missing_ok and code == 404:
            return None
        if process.returncode or (code and not 200 <= code < 300):
            if code == 401 or (not code and b"auth login" in diagnostic):
                raise GitError(ui("GitHub CLI 尚未登录或登录已过期。请运行 gh auth login 后重新检查。"), "gh_auth")
            # Redact credential-shaped strings as well as URL credentials. Raw
            # API payloads, auth status output and token storage are never shown.
            text = safe_output(decode(diagnostic))
            for key in ("GH_TOKEN", "GITHUB_TOKEN"):
                if os.environ.get(key):
                    text = text.replace(os.environ[key], "***")
            text = re.sub(r"(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)", "***", text)
            raise GitError(ui("GitHub 请求失败：") + (text.strip() or str(code or process.returncode)))
        # gh --include emits response headers, then a blank line and JSON.
        body = re.split(rb"\r?\n\r?\n", raw, maxsplit=1)[-1]
        try:
            return json.loads(body)
        except ValueError:
            raise GitError(ui("GitHub 返回的数据格式无效。"))

    def account(self):
        data = self.request("user")
        if not isinstance(data, dict) or not LOGIN.fullmatch(str(data.get("login", ""))) or type(data.get("id")) is not int:
            raise GitError(ui("无法确认当前 GitHub 账号。"))
        return {"login": data["login"], "id": data["id"], "name": data.get("name") or ""}


def suggest_template(path):
    if (path / "Assets").is_dir() and (path / "ProjectSettings").is_dir():
        return "unity"
    if (path / "package.json").is_file():
        return "node"
    if any((path / name).is_file() for name in ("pyproject.toml", "requirements.txt", "setup.py")):
        return "python"
    return "common"


def ignore_contents(path, template):
    original = b""
    target = path / ".gitignore"
    if os.path.lexists(target):
        if target.is_symlink() or not target.is_file() or target.stat().st_size > 200000:
            raise GitError(ui("现有 .gitignore 无法安全读取，请先检查该文件。"))
        original = target.read_bytes()
    addition = TEMPLATES[template].encode()
    content = original
    if addition:
        content += (b"\n" if original and not original.endswith(b"\n") else b"") + addition
    return original, content


def excluded_reason(relative, full):
    name = full.name.lower()
    if full.is_symlink():
        return ui("符号链接")
    if full.is_dir():
        return ui("嵌套仓库")
    if (name == ".env" or (name.startswith(".env.") and name not in {".env.example", ".env.sample", ".env.template"}) or
            name in {".npmrc", ".pypirc", "credentials.json", "id_rsa", "id_ed25519"} or
            any(fnmatch.fnmatch(name, pattern) for pattern in ("*.pem", "*.p12", "*.pfx", "*.key", "service-account*.json"))):
        return ui("凭据文件")
    if ".git" in Path(relative).parts:
        return ui("Git 内部文件")
    return None


def snapshot(path, template, upload):
    original, content = ignore_contents(path, template)
    digest = hashlib.sha256(original + b"\0" + content)
    files, excluded, total = [], [], 0
    if upload:
        deadline = time.monotonic() + 40
        # Use a disposable index with the real worktree. Git evaluates existing
        # nested .gitignore files and global excludes without initializing it.
        with tempfile.TemporaryDirectory(prefix="github-preview-") as directory:
            temporary = SimpleNamespace(path=directory)
            run(temporary, "init", "--quiet")
            extra = Path(directory) / "extra-ignore"
            extra.write_bytes(TEMPLATES[template].encode())
            raw = run(temporary, "--work-tree=" + str(path), "ls-files", "--others", "--exclude-standard",
                      "--exclude-from=" + str(extra), "-z")
            if content or (path / ".gitignore").exists():
                code, _, _ = run(temporary, "--work-tree=" + str(path), "check-ignore", "--no-index", "--", ".gitignore", check=False)
                if code == 0:
                    raise GitError(ui("现有规则忽略了 .gitignore，请先调整规则后重新预览。"))
                if code != 1:
                    raise GitError(ui("无法检查 .gitignore 的忽略状态。"))
            entries = raw.split(b"\0")
            if len(entries) > MAX_FILES + 1:
                raise GitError(ui("待上传文件过多，请先完善 .gitignore，再重新预览。"))
            for value in sorted(item for item in entries if item):
                try:
                    relative = value.decode("utf-8", "strict").rstrip("/")
                except UnicodeDecodeError:
                    raise GitError(ui("文件名无法以 UTF-8 表示，请先重命名后再上传。"))
                if time.monotonic() > deadline:
                    raise GitError(ui("文件检查超时，请先排除生成文件和大型资源后重试。"))
                full = path / relative
                reason = excluded_reason(relative, full)
                if reason:
                    excluded.append({"path": relative, "reason": reason}); continue
                if relative == ".gitignore":
                    continue
                size = full.stat().st_size
                if not stat.S_ISREG(full.lstat().st_mode):
                    raise GitError(ui("不支持上传此文件类型：") + relative)
                if size >= MAX_FILE:
                    raise GitError(ui("文件达到 GitHub 的 100 MiB 限制，请先配置 Git LFS 或忽略该文件：") + relative)
                file_digest = hashlib.sha256()
                descriptor = os.open(full, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                with os.fdopen(descriptor, "rb") as source:
                    mode = os.fstat(source.fileno()).st_mode
                    if not stat.S_ISREG(mode):
                        raise GitError(ui("不支持上传此文件类型：") + relative)
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        file_digest.update(chunk)
                        if time.monotonic() > deadline:
                            raise GitError(ui("文件检查超时，请先排除生成文件和大型资源后重试。"))
                files.append(relative); total += size
                digest.update(json.dumps([relative, size, bool(mode & 0o111), file_digest.hexdigest()]).encode())
        if content or (path / ".gitignore").exists():
            files.append(".gitignore"); total += len(content)
    return {"files": sorted(files), "excluded": excluded, "bytes": total,
            "fingerprint": digest.hexdigest(), "original": original, "ignore": content}


def check_push_destination(path, url):
    # --get-url expands Git URL rewrites without contacting any remote. A
    # global HTTPS-to-SSH rewrite could use a different authenticated account.
    resolved = decode(run(SimpleNamespace(path=str(path)), "ls-remote", "--get-url", url)).strip()
    if resolved != url:
        raise GitError(ui("Git 配置重定向了首次上传地址，请先检查 URL 重写规则：") + safe_output(resolved))


class GithubSetup:
    def __init__(self, client=None):
        self.client = client or GithubClient()
        self.plans, self.jobs = {}, {}
        self.lock = threading.RLock()

    def inspect(self, project):
        path = project_path(project)
        data = {"project": {"path": str(path), "name": path.name}, "ready": False,
                "suggested_name": re.sub(r"[^A-Za-z0-9._-]+", "-", path.name).strip(".-_")[:100] or "my-project",
                "suggested_template": suggest_template(path), "has_gitignore": (path / ".gitignore").is_file(),
                "account": None, "auth_state": "ready"}
        data["install_command"] = "brew install gh" if sys.platform == "darwin" else "winget install --id GitHub.cli" if os.name == "nt" else "https://cli.github.com/"
        try:
            data["account"] = self.client.account(); data["ready"] = True
        except GitError as error:
            data["auth_state"] = error.kind or "error"
            data["message"] = error.ui_message or str(error)
        executable = self.client.executable or "gh"
        data["login_command"] = shlex.quote(executable) + " auth login --hostname github.com --git-protocol https --web"
        data["switch_command"] = shlex.quote(executable) + " auth switch --hostname github.com --user USERNAME"
        return data

    def prepare(self, project, params, owner=""):
        allowed = {"name", "description", "visibility", "branch", "template", "upload", "message", "account", "account_confirmed"}
        if set(params) - allowed:
            raise GitError(ui("无效的 GitHub 创建参数。"))
        path = project_path(project)
        account = self.client.account()
        if params.get("account_confirmed") is not True or params.get("account") != account["login"]:
            raise GitError(ui("请确认当前 GitHub 账号后重新预览。"))
        name = params.get("name", "")
        if not NAME.fullmatch(name) or name in {".", ".."} or name.lower().endswith(".git"):
            raise GitError(ui("仓库名须以字母或数字开头，仅包含字母、数字、点、下划线或连字符，最多 100 个字符。"))
        visibility, template, upload = params.get("visibility"), params.get("template"), params.get("upload")
        if visibility not in {"private", "public"} or template not in TEMPLATES or type(upload) is not bool:
            raise GitError(ui("请选择可见性、忽略规则和首次上传选项。"))
        branch = branch_name(SimpleNamespace(path=str(path)), params.get("branch", "main"))
        description = params.get("description", "").strip()
        message = params.get("message", "Initial commit").strip()
        if len(description) > 350 or "\0" in description or len(message) > 10000 or "\0" in message or (upload and not message):
            raise GitError(ui("请检查仓库描述和首次提交说明。"))
        full_name = account["login"] + "/" + name
        if upload:
            check_push_destination(path, "https://github.com/" + full_name + ".git")
        if self.client.request("repos/" + full_name, missing_ok=True) is not None:
            raise GitError(ui("同名 GitHub 仓库已存在，请使用其他名称；不会覆盖或连接已有仓库。"))
        # git var includes a current timestamp and timezone after the identity.
        # Those naturally change while the user reads the preview.
        identity = decode(run(SimpleNamespace(path=str(path)), "var", "GIT_AUTHOR_IDENT")).strip().rsplit(" ", 2)[0] if upload else ""
        manifest = snapshot(path, template, upload)
        if upload and not manifest["files"]:
            raise GitError(ui("没有可上传的文件，请添加文件或取消首次上传。"))
        details = [ui("GitHub 账号：") + account["login"], ui("目标仓库：") + full_name,
                   ui("可见性：") + (ui("私有，仅授权成员可访问") if visibility == "private" else ui("公开，任何人均可查看上传内容")),
                   ui("本地目录：") + str(path), ui("初始分支：") + branch]
        if description:
            details.append(ui("仓库描述：") + description)
        if template != "existing":
            details.append(ui("将保留现有 .gitignore，并补充所选忽略规则。"))
        details.append(ui("将创建首次提交并推送以下文件，设置 origin 和上游分支。") if upload else
                       ui("仅初始化本地 Git 并创建空的 GitHub 仓库，设置 origin；项目文件不会上传。"))
        if upload:
            details += [ui("提交身份：") + identity, ui("首次提交：") + message]
        if manifest["excluded"]:
            details.append(ui("首次上传已排除凭据文件、符号链接和嵌套仓库；具体路径列于下方。"))
        token = secrets.token_urlsafe(32)
        settings = dict(name=name, description=description, visibility=visibility, branch=branch, template=template, upload=upload, message=message)
        with self.lock:
            now = time.monotonic()
            self.plans = {key: value for key, value in self.plans.items() if value["expires"] > now}
            if len(self.plans) >= 100:
                raise GitError(ui("操作预览过多，请稍后重试。"))
            self.plans[token] = {"path": str(path), "owner": owner, "expires": now + 300, "account": account,
                                 "settings": settings, "manifest": manifest, "identity": identity}
        return {"action": "github_create", "title": ui("确认创建 GitHub 仓库"), "token": token,
                "project": {"path": str(path), "name": path.name}, "details": details,
                "files": manifest["files"], "excluded": manifest["excluded"], "bytes": manifest["bytes"],
                "visibility": visibility, "full_name": full_name, "upload": upload}

    def apply(self, project, token, owner=""):
        with self.lock:
            plan = self.plans.get(token)
            if not plan or plan["owner"] != owner or plan["path"] != str(Path(project).expanduser().resolve()):
                raise GitError(ui("创建预览不存在或不属于当前任务，请重新预览。"))
            self.plans.pop(token)
            if plan["expires"] <= time.monotonic():
                raise GitError(ui("创建预览已过期，请重新预览。"))
            if any(job["state"] == "running" and job["project"]["path"] == plan["path"] for job in self.jobs.values()):
                raise GitError(ui("该项目正在创建 GitHub 仓库，请等待结果。"))
            # Retain results for the lifetime of the server, with a bounded cache.
            if len(self.jobs) >= 100:
                oldest = next((key for key, value in self.jobs.items() if value["state"] != "running"), None)
                if oldest is None:
                    raise GitError(ui("当前创建任务过多，请稍后重试。"))
                self.jobs.pop(oldest)
            identifier = secrets.token_urlsafe(32)
            job = {"action": "github_create", "job": identifier, "owner": owner, "state": "running",
                   "project": {"path": plan["path"], "name": Path(plan["path"]).name}, "steps": [],
                   "message": ui("正在检查账号和文件…"), "url": None, "remote_state": "not_created", "local_initialized": False}
            self.jobs[identifier] = job
            threading.Thread(target=self._execute, args=(job, plan), daemon=True).start()
            return self._public(job)

    def progress(self, project, identifier, owner=""):
        with self.lock:
            job = self.jobs.get(identifier)
            if not job or job["owner"] != owner or job["project"]["path"] != str(Path(project).expanduser().resolve()):
                raise GitError(ui("创建任务不存在或不属于当前任务。"))
            return self._public(job)

    def _public(self, job):
        return {key: list(value) if key == "steps" else value for key, value in job.items() if key != "owner"}

    def _update(self, job, **values):
        with self.lock:
            job.update(values)

    def _step(self, job, message):
        with self.lock:
            job["steps"].append(message); job["message"] = message

    def _execute(self, job, plan):
        try:
            path = project_path(plan["path"])
            settings, expected = plan["settings"], plan["manifest"]
            account = self.client.account()
            if (account["login"], account["id"]) != (plan["account"]["login"], plan["account"]["id"]):
                raise GitError(ui("GitHub 账号已变化，请重新确认账号并预览。"))
            current = snapshot(path, settings["template"], settings["upload"])
            if current["fingerprint"] != expected["fingerprint"]:
                raise GitError(ui("项目文件或忽略规则已变化，请重新预览。"))
            local = SimpleNamespace(path=str(path))
            if settings["upload"] and decode(run(local, "var", "GIT_AUTHOR_IDENT")).strip().rsplit(" ", 2)[0] != plan["identity"]:
                raise GitError(ui("Git 提交身份已变化，请重新预览。"))
            full_name = account["login"] + "/" + settings["name"]
            if settings["upload"]:
                check_push_destination(path, "https://github.com/" + full_name + ".git")
            if self.client.request("repos/" + full_name, missing_ok=True) is not None:
                raise GitError(ui("同名 GitHub 仓库已存在，请使用其他名称；不会覆盖或连接已有仓库。"))
            self._update(job, message=ui("正在初始化本地 Git…"))
            run(local, "init", "-b", settings["branch"])
            self._update(job, local_initialized=True)
            if current["ignore"] != current["original"]:
                if ignore_contents(path, settings["template"])[0] != current["original"]:
                    raise GitError(ui("项目文件或忽略规则已变化，请重新预览。"))
                descriptor = os.open(path / ".gitignore", os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o644)
                with os.fdopen(descriptor, "wb") as target:
                    target.write(current["ignore"])
            self._step(job, ui("本地 Git 已初始化。"))
            if settings["upload"]:
                self._update(job, message=ui("正在创建首次提交…"))
                # Only paths from the reviewed manifest enter the index. Use
                # literal pathspecs, NUL separators and stdin for arbitrary names.
                data = b"\0".join((":(top,literal)" + name).encode() for name in current["files"]) + b"\0"
                run(local, "add", "--pathspec-from-file=-", "--pathspec-file-nul", input_data=data)
                run(local, "commit", "-m", settings["message"])
                self._step(job, ui("首次提交已创建。"))
            confirmed = self.client.account()
            if (confirmed["id"], confirmed["login"]) != (account["id"], account["login"]):
                raise GitError(ui("GitHub 账号已变化，请重新确认账号并预览。"))
            self._update(job, message=ui("正在创建 GitHub 仓库…"), remote_state="unknown")
            remote = self.client.request("user/repos", {"name": settings["name"], "description": settings["description"],
                "private": settings["visibility"] == "private", "auto_init": False})
            expected_url = "https://github.com/" + full_name
            if (not isinstance(remote, dict) or remote.get("full_name", "").lower() != full_name.lower() or
                    remote.get("private") is not (settings["visibility"] == "private") or remote.get("html_url") != expected_url):
                raise GitError(ui("创建结果与预览不一致，请在 GitHub 检查仓库；不会上传文件。"))
            self._update(job, url=expected_url, remote_state="created")
            self._step(job, ui("GitHub 仓库已创建。"))
            run(local, "remote", "add", "origin", expected_url + ".git")
            # Keep subsequent fetch/pull/push usable even when gh login did not
            # install a global Git helper. This new repository alone uses gh.
            helper = "!" + shlex.quote(self.client.executable) + " auth git-credential"
            run(local, "config", "--local", "--replace-all", "credential.https://github.com.helper", "")
            run(local, "config", "--local", "--add", "credential.https://github.com.helper", helper)
            self._step(job, ui("origin 已连接到新仓库。"))
            if settings["upload"]:
                confirmed = self.client.account()
                if (confirmed["id"], confirmed["login"]) != (account["id"], account["login"]):
                    raise GitError(ui("GitHub 账号已变化，请重新确认账号并预览。"))
                check_push_destination(path, expected_url + ".git")
                self._update(job, message=ui("正在推送首次提交…"))
                run(local, "push", "--set-upstream", "origin", "HEAD:refs/heads/" + settings["branch"])
                self._step(job, ui("首次提交已推送，上游分支已设置。"))
            self._update(job, state="succeeded", ok=True, message=ui("GitHub 仓库创建完成。"))
        except Exception as error:
            message = error.ui_message if isinstance(error, GitError) and error.ui_message else safe_output(str(error))
            self._update(job, state="failed", ok=False, message=message,
                         local_initialized=job["local_initialized"] or os.path.lexists(Path(plan["path"]) / ".git"),
                         recovery=ui("已完成的步骤会保留，不会自动重试或删除仓库。请先检查本地与 GitHub 状态。"))
