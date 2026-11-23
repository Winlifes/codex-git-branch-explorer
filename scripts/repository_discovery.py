"""Find Git repositories inside the calling task's workspace."""
from collections import deque
import os
from pathlib import Path
import stat
import time

from git_explorer import GitError, Repository

MAX_DEPTH = 2
MAX_ENTRIES = 2048
MAX_REPOSITORIES = 64
DISCOVERY_SECONDS = 10


def discover(paths, *, scan_workspace):
    """Resolve direct paths first. Search beneath known non-Git workspace roots."""
    deadline = time.monotonic() + DISCOVERY_SECONDS
    repositories = {}
    failure = None
    folders = deque()
    home = Path.home().resolve() if scan_workspace else None
    for path in paths:
        if time.monotonic() >= deadline:
            return repositories, failure, True
        try:
            repo = Repository(path, deadline=deadline)
            repositories[repo.path] = repo
        except GitError as error:
            if error.kind == "not_repository":
                if scan_workspace:
                    directory = Path(path).resolve()
                    if directory != directory.parent and directory != home:
                        folders.append((directory, 0))
                continue
            failure = failure or error
            if error.kind in {"git_unavailable", "query_timeout"}:
                return repositories, failure, error.kind == "query_timeout"
        except OSError as error:
            failure = failure or error

    entries = 0
    visited = set()
    incomplete = False
    while folders:
        directory, depth = folders.popleft()
        if directory in visited:
            continue
        visited.add(directory)
        try:
            with os.scandir(directory) as children:
                for child in children:
                    entries += 1
                    if entries > MAX_ENTRIES or time.monotonic() >= deadline:
                        return repositories, failure, True
                    if child.name.startswith(".") or child.name in {"node_modules", "__pycache__"}:
                        continue
                    if not child.is_dir(follow_symlinks=False):
                        continue
                    # Older Pythons can report Windows directory junctions as directories.
                    if os.name == "nt" and child.stat(follow_symlinks=False).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                        continue
                    path = directory / child.name
                    if (path / ".git").exists() or ((path / "HEAD").is_file() and (path / "objects").is_dir()):
                        if len(repositories) >= MAX_REPOSITORIES and str(path) not in repositories:
                            return repositories, failure, True
                        try:
                            repo = Repository(path, deadline=deadline)
                        except GitError as error:
                            if error.kind == "query_timeout":
                                return repositories, failure or error, True
                            if error.kind != "not_repository":
                                failure = failure or error
                                incomplete = True
                        else:
                            # A candidate must be the worktree/bare root, not an
                            # enclosing repo or a directory outside the workspace.
                            if Path(repo.path) == path:
                                repositories[repo.path] = repo
                    elif depth + 1 < MAX_DEPTH:
                        folders.append((path, depth + 1))
        except OSError as error:
            failure = failure or error
            incomplete = True
    return repositories, failure, incomplete
