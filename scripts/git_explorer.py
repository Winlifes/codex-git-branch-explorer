#!/usr/bin/env python3
"""Read-only Git queries and a loopback UI. Python 3.9+, no dependencies."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FORMAT = "%H%x00%P%x00%an%x00%ae%x00%aI%x00%cI%x00%s%x00%B"
MAX_OUTPUT = 24 * 1024 * 1024
MAX_PATCH = 800_000


class GitError(Exception):
    def __init__(self, message, kind=None):
        super().__init__(message)
        self.kind = kind


def decode(value):
    return value.decode("utf-8", "replace")


def bounded_int(value, default, minimum, maximum):
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise GitError("分页参数必须是整数。")
    if not minimum <= number <= maximum:
        raise GitError("参数超出范围。")
    return number


class Repository:
    def __init__(self, path):
        self.path = str(Path(path).expanduser().resolve())
        if not Path(self.path).is_dir():
            raise GitError("仓库目录不存在或无法访问。", "directory_unavailable")
        self.git("rev-parse", "--git-dir")
        self.bare = self.git("rev-parse", "--is-bare-repository").strip() == b"true"
        root = self.git("rev-parse", "--absolute-git-dir" if self.bare else "--show-toplevel")
        self.path = decode(root).strip()

    def git(self, *args, optional=False, cap=MAX_OUTPUT, truncate=False):
        # Commands are read-only; do not invoke hooks, external diff or textconv.
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0",
                   GIT_NO_LAZY_FETCH="1", GIT_NO_REPLACE_OBJECTS="1",
                   GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, LC_ALL="C")
        cmd = ["git", "--no-pager", "--no-optional-locks", "-C", self.path,
               "-c", "color.ui=false", "-c", "core.quotePath=false",
               "-c", "log.showSignature=false", "-c", "core.fsmonitor=false",
               "-c", "diff.renames=false", *args]
        try:
            # File-backed output prevents huge diffs from filling Python memory.
            with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
                process = subprocess.Popen(cmd, stdout=out, stderr=err, env=env)
                deadline = time.monotonic() + 25
                limited = False
                while process.poll() is None:
                    if time.monotonic() > deadline:
                        process.kill()
                        process.wait()
                        raise GitError("Git 查询超时，请缩小查询范围后重试。")
                    if os.fstat(out.fileno()).st_size > cap:
                        limited = True
                        process.kill()
                        process.wait()
                        break
                    time.sleep(0.01)
                out.seek(0)
                data = out.read(cap + 1)
                limited = limited or len(data) > cap
                if limited:
                    if truncate:
                        return data[:cap], True
                    raise GitError("查询结果过大，请缩小查询范围。")
                if process.returncode:
                    if optional:
                        return b""
                    err.seek(0)
                    message = decode(err.read(2000)).strip() or "Git 查询失败。"
                    kind = "not_repository" if message.startswith("fatal: not a git repository") else None
                    raise GitError(message, kind)
                return (data, False) if truncate else data
        except FileNotFoundError:
            raise GitError("找不到 Git，请先安装 Git 并确保它位于 PATH。", "git_unavailable")

    def oid(self, ref):
        # Exact branch names, HEAD and object IDs; never arbitrary rev expressions.
        if not isinstance(ref, str) or len(ref) > 1024 or "\0" in ref:
            raise GitError("无效的分支或提交。")
        if ref != "HEAD" and not re.fullmatch(r"[0-9a-fA-F]{4,64}", ref):
            if not ref.startswith(("refs/heads/", "refs/remotes/")):
                raise GitError("请选择完整分支引用或提交 SHA。")
            if not self.git("show-ref", "--verify", "--hash", ref, optional=True):
                raise GitError("分支不存在，可能已被删除；请刷新分支列表。")
        value = self.git("rev-parse", "--verify", "--end-of-options", ref + "^{commit}")
        result = decode(value).strip()
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", result):
            raise GitError("无法解析提交。")
        return result

    def info(self):
        current = decode(self.git("symbolic-ref", "--quiet", "HEAD", optional=True)).strip()
        head = decode(self.git("rev-parse", "--verify", "--quiet", "HEAD^{commit}", optional=True)).strip()
        return {"path": self.path, "name": Path(self.path).name, "bare": self.bare,
                "current_ref": current or None, "head": head or None,
                "detached": bool(head and not current),
                "shallow": self.git("rev-parse", "--is-shallow-repository").strip() == b"true"}

    def branches(self):
        info = self.info()
        fmt = "%00".join(["%(refname)", "%(objectname)", "%(committerdate:iso-strict)",
                         "%(subject)", "%(authorname)", "%(upstream)",
                         "%(upstream:track)", "%(symref)"])
        raw = self.git("for-each-ref", "--sort=-committerdate", "--format=" + fmt,
                       "refs/heads/", "refs/remotes/")
        branches = []
        for row in raw.split(b"\n"):
            if not row:
                continue
            fields = row.split(b"\0")
            if len(fields) != 8:
                raise GitError("分支元数据格式无法解析。")
            ref, sha, date, subject, author, upstream, tracking, symref = map(decode, fields)
            if symref:  # origin/HEAD is an alias, not another branch.
                continue
            remote = ref.startswith("refs/remotes/")
            branches.append({"ref": ref, "name": ref[len("refs/remotes/" if remote else "refs/heads/"):],
                             "sha": sha, "date": date, "subject": subject, "author": author,
                             "upstream": upstream, "tracking": tracking, "remote": remote,
                             "current": ref == info["current_ref"], "unborn": False})
        if info["current_ref"] and not info["head"]:
            branches.insert(0, {"ref": info["current_ref"], "name": info["current_ref"].removeprefix("refs/heads/"),
                                "sha": None, "date": "", "subject": "尚无提交", "author": "",
                                "upstream": "", "tracking": "", "remote": False, "current": True, "unborn": True})
        return {"repository": info, "branches": branches}

    @staticmethod
    def parse_commits(raw):
        fields = raw.split(b"\0")
        if fields and fields[-1] == b"":
            fields.pop()
        if len(fields) % 8:
            raise GitError("提交元数据格式无法解析。")
        result = []
        for i in range(0, len(fields), 8):
            sha, parents, author, email, date, committed, subject, message = map(decode, fields[i:i+8])
            result.append({"sha": sha, "parents": parents.split(), "author": author,
                           "email": email, "date": date, "committed_date": committed,
                           "subject": subject, "message": message.rstrip("\n")})
        return result

    def commits(self, ref="HEAD", limit=50, offset=0, query="", author="", first_parent=False):
        limit = bounded_int(limit, 50, 1, 200)
        offset = bounded_int(offset, 0, 0, 10_000_000)
        for text in (query, author):
            if not isinstance(text, str) or len(text) > 300 or "\0" in text or "\n" in text:
                raise GitError("搜索词最长 300 个字符，且不能包含换行。")
        if ref == "HEAD" and not self.info()["head"]:
            return {"commits": [], "has_more": False, "next_offset": 0, "snapshot": None}
        snapshot = self.oid(ref)
        args = ["log", "-z", "--topo-order", "--no-decorate", "--encoding=UTF-8", "--format=" + FORMAT,
                "--max-count=" + str(limit + 1), "--skip=" + str(offset), "--fixed-strings", "--regexp-ignore-case"]
        if query:
            args.append("--grep=" + query)
        if author:
            args.append("--author=" + author)
        if first_parent:
            args.append("--first-parent")
        items = self.parse_commits(self.git(*args, snapshot, "--"))
        page = items[:limit]
        try:
            stats = self.commit_stats([item["sha"] for item in page])
            for item in page:
                item["stats"] = stats[item["sha"]]
        except GitError as error:
            # Large or unsupported diffs must not hide the commit history itself.
            for item in page:
                item["stats"] = None
                item["stats_error"] = str(error)
        return {"commits": page, "has_more": len(items) > limit,
                "next_offset": offset + min(len(items), limit), "snapshot": snapshot}

    def commit_stats(self, object_ids):
        """Batch line counts for one page, relative to each commit's first parent."""
        if not object_ids:
            return {}
        if any(not isinstance(oid, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", oid)
               for oid in object_ids):
            raise GitError("无效的提交统计请求。")
        result = {oid: {"additions": 0, "deletions": 0, "files_changed": 0, "binary_files": 0}
                  for oid in object_ids}
        raw = self.git("show", "--no-walk=unsorted", "--root", "--diff-merges=first-parent",
                       "--numstat", "-z", "--format=%x00%H%x00", "--no-renames",
                       "--no-ext-diff", "--no-textconv", *object_ids, "--")
        current = None
        seen = set()
        for record in raw.split(b"\0"):
            # Git inserts a newline before the first numstat record. Paths stay
            # inside their record and may contain tabs, newlines, or arbitrary bytes.
            record = record.lstrip(b"\n")
            if not record:
                continue
            if re.fullmatch(rb"[0-9a-f]{40}|[0-9a-f]{64}", record):
                oid = record.decode("ascii")
                if oid not in result or oid in seen:
                    raise GitError("提交统计记录无法解析。")
                seen.add(oid)
                current = result[oid]
                continue
            counts = record.split(b"\t", 2)
            if current is None or len(counts) != 3:
                raise GitError("提交行数统计无法解析。")
            added, deleted, _path = counts
            if added == deleted == b"-":
                current["binary_files"] += 1
            elif added.isdigit() and deleted.isdigit():
                current["additions"] += int(added)
                current["deletions"] += int(deleted)
            else:
                raise GitError("提交行数统计无法解析。")
            current["files_changed"] += 1
        if seen != set(object_ids):
            raise GitError("部分提交的行数统计缺失。")
        return result

    def commit(self, sha, parent=0):
        oid = self.oid(sha)
        item = self.parse_commits(self.git("show", "-s", "-z", "--encoding=UTF-8", "--format=" + FORMAT, oid, "--"))[0]
        parent = bounded_int(parent, 0, 0, max(0, len(item["parents"]) - 1))
        if item["parents"]:
            args = ["diff", "--no-ext-diff", "--no-textconv", "--no-renames",
                    "--name-status", "-z", item["parents"][parent], oid, "--"]
        else:
            args = ["diff-tree", "--root", "--no-commit-id", "-r", "--no-renames",
                    "--no-ext-diff", "--no-textconv", "--name-status", "-z", oid, "--"]
        fields = self.git(*args).split(b"\0")
        if fields[-1:] == [b""]:
            fields.pop()
        if len(fields) % 2:
            raise GitError("文件列表格式无法解析。")
        item["files"] = [{"status": decode(fields[i]), "path": decode(fields[i+1])}
                         for i in range(0, len(fields), 2)]
        item["parent_index"] = parent
        return item

    def patch(self, sha, path, parent=0):
        item = self.commit(sha, parent)
        if path not in {f["path"] for f in item["files"]}:
            raise GitError("该文件不在所选提交的变更列表中。")
        literal = ":(top,literal)" + path
        common = ["--no-ext-diff", "--no-textconv", "--no-renames", "--no-color", "--unified=3"]
        if item["parents"]:
            args = ["diff", *common, item["parents"][item["parent_index"]], item["sha"], "--", literal]
        else:
            args = ["show", "--format=", "--root", *common, item["sha"], "--", literal]
        raw, truncated = self.git(*args, cap=MAX_PATCH, truncate=True)
        return {"sha": item["sha"], "path": path, "patch": decode(raw), "truncated": truncated,
                "parent_index": item["parent_index"]}


class ExplorerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, repo, port=0, idle_seconds=7200):
        self.repo = repo
        self.prefix = "/s/" + secrets.token_urlsafe(32) + "/"
        self.last_request = time.monotonic()
        self.idle_seconds = idle_seconds
        self.slots = threading.BoundedSemaphore(6)
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = "http://127.0.0.1:" + str(self.server_port)

    @property
    def url(self):
        return self.origin + self.prefix

    def service_actions(self):
        if time.monotonic() - self.last_request > self.idle_seconds:
            threading.Thread(target=self.shutdown, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    server_version = "GitExplorer/0.1"

    def log_message(self, *args):
        pass  # Do not expose session URLs in access logs.

    def send(self, status, value, kind="application/json; charset=utf-8"):
        data = json.dumps(value, ensure_ascii=False).encode("utf-8") if kind.startswith("application/json") else value
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def allowed_path(self):
        if self.headers.get("Host") != urlsplit(self.server.origin).netloc:
            self.send(403, {"error": "无效的请求来源。"})
            return None
        if self.headers.get("Origin") not in (None, self.server.origin):
            self.send(403, {"error": "不接受跨站请求。"})
            return None
        parsed = urlsplit(self.path)
        if not parsed.path.startswith(self.server.prefix):
            self.send(404, {"error": "浏览会话不存在，请从 Codex 重新打开。"})
            return None
        self.server.last_request = time.monotonic()
        return parsed

    def do_POST(self):
        parsed = self.allowed_path()
        if parsed is None:
            return
        if parsed.path == self.server.prefix + "api/stop":
            self.send(200, {"stopped": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self.send(405, {"error": "此浏览器只提供读取操作。"})

    def do_GET(self):
        parsed = self.allowed_path()
        if parsed is None:
            return
        path = parsed.path[len(self.server.prefix):]
        assets = {"": ("index.html", "text/html; charset=utf-8"),
                  "app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "operations.js": ("operations.js", "text/javascript; charset=utf-8"),
                  "controls.js": ("controls.js", "text/javascript; charset=utf-8"),
                  "style.css": ("style.css", "text/css; charset=utf-8")}
        if path in assets:
            name, kind = assets[path]
            self.send(200, (ROOT / "assets" / name).read_bytes(), kind)
            return
        if not self.server.slots.acquire(blocking=False):
            self.send(429, {"error": "查询繁忙，请稍后重试。"})
            return
        try:
            params = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=20)
            def get(key, default=""):
                return params.get(key, [default])[0]
            repo = self.server.repo
            if path == "api/branches":
                value = repo.branches()
            elif path == "api/commits":
                value = repo.commits(get("ref", "HEAD"), get("limit", "50"), get("offset", "0"),
                                     get("query"), get("author"), get("first_parent") == "true")
            elif path == "api/commit":
                value = repo.commit(get("sha"), get("parent", "0"))
            elif path == "api/patch":
                value = repo.patch(get("sha"), get("path"), get("parent", "0"))
            else:
                self.send(404, {"error": "接口不存在。"})
                return
            self.send(200, value)
        except (GitError, ValueError) as error:
            self.send(400, {"error": str(error)})
        except Exception:
            self.send(500, {"error": "读取失败，请从 Codex 重新打开浏览器。"})
        finally:
            self.server.slots.release()


def serve(args):
    server = ExplorerServer(Repository(args.repo), args.port, args.idle_seconds)
    result = {"url": server.url, "pid": os.getpid(), "repository": server.repo.path,
              "idle_seconds": args.idle_seconds}
    if args.ready_file:
        path = Path(args.ready_file)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result), encoding="utf-8")
        temporary.replace(path)
    else:
        print(json.dumps(result, ensure_ascii=False), flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def start(args):
    repo = Repository(args.repo)
    with tempfile.TemporaryDirectory(prefix="codex-git-explorer-") as temp:
        ready = Path(temp) / "ready.json"
        kwargs = {"start_new_session": True} if os.name != "nt" else {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "serve", "--repo", repo.path,
                                  "--port", str(args.port), "--idle-seconds", str(args.idle_seconds),
                                  "--ready-file", str(ready)], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
        for _ in range(160):
            if ready.exists():
                result = json.loads(ready.read_text(encoding="utf-8"))
                if "error" in result:
                    child.wait(timeout=5)
                    raise GitError(result["error"])
                print(json.dumps(result, ensure_ascii=False), flush=True)
                return
            if child.poll() is not None:
                raise GitError("后台服务启动失败。可使用 serve 命令查看错误。")
            time.sleep(0.05)
        child.terminate()
        child.wait(timeout=5)
        raise GitError("浏览器启动超时。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("start", "serve", "branches", "log", "show"):
        p = sub.add_parser(command)
        p.add_argument("--repo", required=True, help="Repository or worktree path")
        if command in ("start", "serve"):
            p.add_argument("--port", type=int, default=0)
            p.add_argument("--idle-seconds", type=int, default=7200)
        if command == "serve":
            p.add_argument("--ready-file")
        if command == "log":
            p.add_argument("--ref", default="HEAD")
            p.add_argument("--limit", type=int, default=50)
            p.add_argument("--offset", type=int, default=0)
            p.add_argument("--query", default="")
            p.add_argument("--author", default="")
            p.add_argument("--first-parent", action="store_true")
        if command == "show":
            p.add_argument("--sha", required=True)
            p.add_argument("--parent", type=int, default=0)
    args = parser.parse_args()
    try:
        if args.command == "start":
            start(args)
        elif args.command == "serve":
            serve(args)
        else:
            repo = Repository(args.repo)
            if args.command == "branches":
                value = repo.branches()
            elif args.command == "log":
                value = repo.commits(args.ref, args.limit, args.offset, args.query, args.author, args.first_parent)
            else:
                value = repo.commit(args.sha, args.parent)
            print(json.dumps(value, ensure_ascii=False, indent=2))
    except (GitError, OSError) as error:
        if args.command == "serve" and args.ready_file:
            target = Path(args.ready_file)
            temp = target.with_suffix(".tmp")
            temp.write_text(json.dumps({"error": str(error)}), encoding="utf-8")
            temp.replace(target)
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
