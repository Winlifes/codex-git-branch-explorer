"""Bounded, local commit drafts from the index or selected worktree scope."""
from __future__ import annotations

import difflib
import json
import os
from pathlib import Path
import re
import stat

from git_explorer import decode
from i18n import ui, translate

MAX_CONTENT = 48_000
MAX_DETAILS = 20


def display(value, limit=180):
    value = json.dumps(value, ensure_ascii=False)[1:-1] if any(ord(c) < 32 for c in value) else value
    return value if len(value) <= limit else value[:limit - 1] + "…"


def entries(raw):
    result = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        info, name = record.split(b"\t", 1)
        parts = info.decode("ascii").split()
        # ls-tree: mode type oid; ls-files --stage: mode oid stage.
        result[decode(name)] = (parts[0], parts[2] if parts[1] in {"blob", "commit", "tree"} else parts[1])
    return result


def worktree(path):
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None, b"", False
    if stat.S_ISLNK(mode):
        return "120000", os.fsencode(os.readlink(path)), False
    if stat.S_ISDIR(mode):
        return "160000", b"", False
    if not stat.S_ISREG(mode):
        return "special", b"", True
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as source:
        data = source.read(MAX_CONTENT + 1)
    return "100755" if mode & 0o111 else "100644", data[:MAX_CONTENT], len(data) > MAX_CONTENT


def symbols(lines, path):
    result = []
    for line in lines:
        # Only names and headings become draft text, never arbitrary code lines
        # or values. Repository text is data, including anything resembling instructions.
        patterns = [r"\b(?:class|interface|enum|struct|record|def|function|fn|type)\s+([\w$]+)",
                    r"^\s*(?:export\s+)?(?:const|let|var)\s+([\w$]+)\s*=.*=>",
                    r"\b(?:public|private|protected|internal)\s+.*?([\w$]+)\s*\("]
        if Path(path).suffix.lower() in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}:
            patterns += [r"(?:^|[{,])\s*[\"']([\w.$:/-]+)[\"']\s*:", r"^\s*([\w.-]+)\s*[:=]"]
        if Path(path).suffix.lower() in {".md", ".mdx", ".rst"}:
            patterns += [r"^\s*#{1,6}\s+(.{1,64})"]
        for pattern in patterns:
            for match in re.finditer(pattern, line):
                name = display(match[1], 64)
                if name not in result:
                    result.append(name)
                if len(result) >= 4:
                    break
        if len(result) >= 4:
            break
    return result[:4]


def generate(repo, files, head, staged=False, locale="zh-CN", merging=False):
    paths = [item["path"] for item in files if item["operable"]]
    literals = [":(top,literal)" + path for path in paths]
    before = entries(repo.git("ls-tree", "-r", "-z", "HEAD", "--", *literals)) if head and paths else {}
    after = entries(repo.git("ls-files", "--stage", "-z", "--", *literals)) if staged and paths else {}
    rows, partial = [], len(files) > MAX_DETAILS
    for index, item in enumerate(files):
        path = item["path"]
        old = before.get(path)
        new = after.get(path) if staged else None
        detailed = index < MAX_DETAILS and item["operable"]
        old_data, new_data, old_limited, new_limited = b"", b"", False, False
        if staged:
            if old == new and item["operable"]:
                continue
            mode = new[0] if new else None
        else:
            if detailed:
                mode, new_data, new_limited = worktree(Path(repo.path) / path)
            else:
                try:
                    file_mode = (Path(repo.path) / path).lstat().st_mode
                    mode = "120000" if stat.S_ISLNK(file_mode) else "160000" if stat.S_ISDIR(file_mode) else "100644"
                except FileNotFoundError:
                    mode = None
            if not old and mode is None:
                continue
        if detailed:
            if old and old[0] not in {"160000", "040000"}:
                old_data, old_limited = repo.git("cat-file", "blob", old[1], cap=MAX_CONTENT, truncate=True)
            if staged and new and new[0] not in {"160000", "040000"}:
                new_data, new_limited = repo.git("cat-file", "blob", new[1], cap=MAX_CONTENT, truncate=True)
            if not staged and old and old[0] == mode and old_data == new_data and not (old_limited or new_limited):
                continue
        kind = "add" if not old and mode else "delete" if old and mode is None else "modify"
        limited = old_limited or new_limited or not detailed
        binary = b"\0" in old_data or b"\0" in new_data
        references, added, removed = [], 0, 0
        if detailed and not binary and mode != "160000" and (not old or old[0] != "160000"):
            old_lines, new_lines = decode(old_data).splitlines(), decode(new_data).splitlines()
            changed = []
            for tag, a, b, c, d in difflib.SequenceMatcher(None, old_lines, new_lines).get_opcodes():
                if tag != "equal":
                    removed += b - a
                    added += d - c
                    changed.extend(old_lines[a:b]); changed.extend(new_lines[c:d])
            references = symbols(changed, path)
        partial = partial or limited
        rows.append({"path": path, "kind": kind, "added": added, "removed": removed,
                     "binary": binary, "submodule": mode == "160000" or bool(old and old[0] == "160000"),
                     "symbols": references, "limited": limited})
    labels = {"add": translate(ui("新增"), locale), "modify": translate(ui("更新"), locale),
              "delete": translate(ui("删除"), locale)}
    if len(rows) == 1:
        title = labels[rows[0]["kind"]] + " " + display(Path(rows[0]["path"]).name, 64)
    elif rows:
        title = translate(ui("更新 {count} 个文件", count=len(rows)), locale)
    else:
        title = translate(ui("合并更改"), locale) if merging else ""
    body = []
    for row in rows[:MAX_DETAILS]:
        description = labels[row["kind"]] + " " + display(row["path"])
        if row["binary"]:
            description += " (" + translate(ui("二进制文件"), locale) + ")"
        elif row["submodule"]:
            description += " (" + translate(ui("子模块引用"), locale) + ")"
        elif not row["limited"]:
            description += f" (+{row['added']}/-{row['removed']})"
        if row["symbols"]:
            description += "; " + translate(ui("涉及：{names}", names=", ".join(row["symbols"])), locale)
        body.append("- " + description)
    if len(rows) > MAX_DETAILS:
        body.append("- " + translate(ui("另有 {count} 个文件，请查看提交预览。", count=len(rows) - MAX_DETAILS), locale))
    return {"message": title + ("\n\n" + "\n".join(body) if body else ""),
            "files": [row["path"] for row in rows], "partial": partial}
