"""Resolve only the calling Codex task's local paths; never guess the active project."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3


def absolute_path(value):
    if not isinstance(value, str) or not value or "\0" in value or len(value) > 8192:
        return None
    path = Path(value).expanduser()
    return str(path) if path.is_absolute() else None


class ProjectContext:
    def __init__(self, codex_home=None):
        self.home = Path(codex_home or os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve()

    def paths(self, metadata):
        """None means no task metadata; [] means a task was supplied but could not be resolved."""
        return self.inspect(metadata)["paths"]

    def inspect(self, metadata):
        """Only persisted message flags are evidence; a missing task is not proof of no message."""
        result = {"paths": None, "message_status": "unknown"}
        if not isinstance(metadata, dict):
            return result
        supplied = [metadata[key] for key in ("threadId", "thread_id") if key in metadata]
        if not supplied:
            return result
        result["paths"] = []
        if any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", value)
               for value in supplied) or len(set(supplied)) != 1:
            return result
        thread_id = supplied[0]
        record = self._task_record(thread_id)
        cwd = record.get("cwd") if record else None
        if record and record.get("has_user_event") in (0, 1):
            result["message_status"] = "sent" if record["has_user_event"] else "not_sent"
        if cwd and Path(cwd).is_dir():
            result["paths"] = [cwd]
            return result
        # A saved task may predate a project move. Its explicit project assignment
        # is still valid even when the old checkout path no longer exists.
        result["paths"] = self._desktop_paths(thread_id) or ([cwd] if cwd else [])
        return result

    def _task_record(self, thread_id):
        # Read cwd and the user-event flag only: no conversation bodies, writes, or migrations.
        # A task's worktree cwd takes precedence over its saved project's main checkout.
        try:
            databases = [path for path in self.home.glob("state_*.sqlite")
                         if re.fullmatch(r"state_[0-9]+\.sqlite", path.name)]
            databases.sort(key=lambda path: int(path.stem.split("_")[1]), reverse=True)
        except OSError:
            return None
        for database in databases:
            try:
                connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0.2)
                try:
                    connection.execute("PRAGMA query_only = ON")
                    columns = {row[1] for row in connection.execute("PRAGMA table_info(threads)")}
                    flag = "has_user_event" if "has_user_event" in columns else "NULL"
                    row = connection.execute("SELECT cwd, " + flag + " FROM threads WHERE id = ? LIMIT 1", (thread_id,)).fetchone()
                    if row:
                        return {"cwd": absolute_path(row[0]), "has_user_event": row[1]}
                finally:
                    connection.close()
            except (sqlite3.Error, OSError):
                continue
        return None

    def _desktop_paths(self, thread_id):
        # Newly created desktop tasks can have a project assignment before their
        # first turn is persisted to SQLite. Use that exact assignment only.
        try:
            with (self.home / ".codex-global-state.json").open("rb") as stream:
                raw = stream.read(32 * 1024 * 1024 + 1)
            if len(raw) > 32 * 1024 * 1024:
                return []
            state = json.loads(raw)
        except (OSError, ValueError):
            return []
        if not isinstance(state, dict):
            return []

        def mapping(key):
            value = state.get(key)
            return value if isinstance(value, dict) else {}

        for key in ("thread-projectless-output-directories", "thread-workspace-root-hints"):
            path = absolute_path(mapping(key).get(thread_id))
            if path:
                return [path]
        assignment = mapping("thread-project-assignments").get(thread_id)
        if not isinstance(assignment, dict) or assignment.get("projectKind") != "local":
            return []
        project_id = assignment.get("projectId")
        if not isinstance(project_id, str):
            return []
        project = mapping("local-projects").get(project_id)
        if not isinstance(project, dict) or not isinstance(project.get("rootPaths"), list):
            return []
        roots = project["rootPaths"]
        if len(roots) > 32:
            return []
        return list(dict.fromkeys(path for value in roots if (path := absolute_path(value))))
