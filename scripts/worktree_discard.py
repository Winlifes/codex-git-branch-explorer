"""Validate and back up exact worktree paths before discarding local changes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
import time

from git_explorer import GitError, decode


def worktree_path(repo, name):
    parts = Path(name).parts
    if (not name or "\0" in name or Path(name).is_absolute() or name.endswith("/")
            or any(p in {"", ".", ".."} or p.lower() == ".git" for p in parts)):
        raise GitError("此路径无法安全撤回，请单独检查：" + name)
    current = Path(repo.path)
    for part in parts[:-1]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            break
        if not stat.S_ISDIR(mode):
            raise GitError("路径包含符号链接或目录类型变化，请单独处理：" + name)
    full = Path(repo.path) / name
    try:
        mode = full.lstat().st_mode
    except FileNotFoundError:
        return full, None
    if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
        raise GitError("子模块、嵌套仓库或特殊文件需要单独打开处理：" + name)
    return full, mode


def prepare_discard(repo, changes, params):
    all_files = params.get("all", False)
    if type(all_files) is not bool or (all_files and "paths" in params):
        raise GitError("请选择撤回单个文件或全部工作区改动。")
    available = {c["path"]: c for c in changes if c["unstaged"]}
    paths = list(available) if all_files else params.get("paths")
    if (not isinstance(paths, list) or not paths or (not all_files and len(paths) > 500)
            or any(not isinstance(p, str) for p in paths) or len(set(paths)) != len(paths)):
        raise GitError("没有可撤回的工作区改动，请刷新后选择文件。")
    if any(p not in available or not available[p]["operable"] or available[p]["conflict"] for p in paths):
        raise GitError("文件状态已变化、存在冲突或文件名无法处理，请刷新工作区。")
    # Read index modes to reject gitlinks even if their worktree directory is gone.
    indexed = {}
    for row in repo.git("ls-files", "--stage", "-z").split(b"\0"):
        if row:
            header, name = row.split(b"\t", 1)
            indexed[name] = header.split()[0]
    intents = []
    for path in paths:
        if indexed.get(path.encode("utf-8")) == b"160000":
            raise GitError("子模块需要单独打开处理：" + path)
        # Intent-to-add is an index placeholder, not a staged file version.
        if available[path]["index_status"] == " " and available[path]["worktree_status"] == "A":
            intents.append(path)
        worktree_path(repo, path)
    untracked = [p for p in paths if p.encode("utf-8") not in indexed or p in intents]
    untracked_set = set(untracked)
    return {"paths": paths, "tracked": [p for p in paths if p not in untracked_set],
            "untracked": untracked, "intents": intents,
            "signatures": {p: file_signature(repo, p) for p in untracked}}


def file_signature(repo, name):
    full, mode = worktree_path(repo, name)
    if mode is None:
        return None
    s = full.lstat()
    return [s.st_mode, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def create_backup(repo, paths):
    raw = Path(decode(repo.git("rev-parse", "--git-path", ".")).strip())
    git_dir = (raw if raw.is_absolute() else Path(repo.path) / raw).resolve()
    base = git_dir
    for name in ("codex-git-explorer", "discard-backups"):
        base /= name
        base.mkdir(mode=0o700, exist_ok=True)
        if base.is_symlink() or not base.is_dir():
            raise GitError("本地备份目录不可用，已取消撤回。")
    backup = Path(tempfile.mkdtemp(prefix=time.strftime("%Y%m%d-%H%M%S-"), dir=base))
    records = []
    try:
        for i, name in enumerate(paths):
            full, mode = worktree_path(repo, name)
            item = {"path": name, "kind": "missing"}
            if mode is not None and stat.S_ISLNK(mode):
                item.update(kind="symlink", target=os.readlink(full))
            elif mode is not None:
                storage = str(i) + ".data"
                fd = os.open(full, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                with os.fdopen(fd, "rb") as source, (backup / storage).open("xb") as dest:
                    if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                        raise GitError("文件类型已变化，请刷新工作区。")
                    while True:
                        block = source.read(1024 * 1024)
                        if not block:
                            break
                        dest.write(block)
                    dest.flush(); os.fsync(dest.fileno())
                item.update(kind="file", storage=storage, mode=stat.S_IMODE(mode) & 0o777)
            records.append(item)
        manifest = {"version": 1, "repository": repo.path, "created_at": time.time(), "files": records}
        with (backup / "manifest.json").open("x", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
            f.flush(); os.fsync(f.fileno())
    except (OSError, GitError) as err:
        raise GitError("本地备份未完成，未执行撤回。\n" + str(err)) from err
    return str(backup)


def remove_untracked(repo, paths, signatures):
    # Only unlink the exact previewed files/links. Never recurse or run git clean.
    for name in paths:
        if file_signature(repo, name) != signatures[name]:
            raise GitError("新文件在执行期间发生变化，已停止撤回。请刷新检查；已完成的部分可从本地备份恢复。")
        full, mode = worktree_path(repo, name)
        if mode is not None:
            full.unlink()
