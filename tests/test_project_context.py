"""Regression tests for a shared MCP process opened from different Codex tasks."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from mcp_server import Server
from git_explorer import GitError
from project_context import ProjectContext


class ProjectContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "codex-data"
        self.home.mkdir()
        self.repo_a = self.root / "项目 A"
        self.repo_b = self.root / "项目 B"
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                        GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.test",
                        GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.test")
        for repo, branch in ((self.repo_a, "project-a"), (self.repo_b, "project-b")):
            repo.mkdir()
            self.git(repo, "init", "-b", branch)
            (repo / "hello.txt").write_text(branch)
            self.git(repo, "add", ".")
            self.git(repo, "commit", "-m", branch + " first commit")
        self.server = Server(cwd="/", codex_home=self.home)

    def git(self, repo, *args):
        return subprocess.check_output(["git", "-C", str(repo), "-c", "commit.gpgsign=false",
            "-c", "core.hooksPath=" + str(self.root / "no-hooks"), *args], env=self.env, stderr=subprocess.PIPE)

    def task(self, identifier, cwd, has_user_event=1):
        with sqlite3.connect(self.home / "state_5.sqlite") as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS threads (id TEXT PRIMARY KEY, cwd TEXT, has_user_event INTEGER)")
            connection.execute("INSERT OR REPLACE INTO threads VALUES (?, ?, ?)", (identifier, str(cwd), has_user_event))

    def desktop(self, assignments):
        state = {"thread-project-assignments": assignments,
                 "local-projects": {"a": {"rootPaths": [str(self.repo_a)]},
                                    "b": {"rootPaths": [str(self.repo_b)]}},
                 "selected-project": "b"}
        (self.home / ".codex-global-state.json").write_text(json.dumps(state))
        return state

    def call(self, identifier, name="git_panel", **arguments):
        result = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": arguments,
                       "_meta": {"thread_id": identifier, "threadId": identifier}}})["result"]
        self.assertFalse(result.get("isError"), result)
        return result["_meta"]["gitExplorer"]

    def test_slash_process_cwd_uses_calling_task_and_finds_repo_from_subdirectory(self):
        subdir = self.repo_a / "src"
        subdir.mkdir()
        self.task("task-a", subdir)
        before = (self.home / "state_5.sqlite").read_bytes()
        result = self.call("task-a")
        self.assertEqual(result["repository"]["path"], str(self.repo_a))
        history = self.call("task-a", "git_query", action="commits")
        self.assertEqual(history["commits"][0]["subject"], "project-a first commit")
        self.assertEqual((self.home / "state_5.sqlite").read_bytes(), before)

    def test_interleaved_tasks_never_share_a_selected_repository(self):
        self.task("task-a", self.repo_a)
        self.task("task-b", self.repo_b)
        for identifier, repo in [("task-a", self.repo_a), ("task-b", self.repo_b), ("task-a", self.repo_a)]:
            self.assertEqual(self.call(identifier)["repository"]["path"], str(repo))

    def test_new_desktop_task_before_first_turn_uses_its_project_assignment(self):
        self.desktop({"fresh-task": {"projectKind": "local", "projectId": "a"}})
        self.assertFalse((self.home / "state_5.sqlite").exists())
        self.assertEqual(self.call("fresh-task")["repository"]["path"], str(self.repo_a))
        self.assertFalse((self.home / "state_5.sqlite").exists())

    def test_task_worktree_wins_over_saved_project_main_checkout(self):
        worktree = self.root / "worktree"
        self.git(self.repo_a, "worktree", "add", "-b", "worktree-branch", str(worktree))
        self.task("task-a", worktree)
        self.desktop({"task-a": {"projectKind": "local", "projectId": "a"}})
        result = self.call("task-a")
        self.assertEqual(result["repository"]["path"], str(worktree))
        self.assertEqual(result["repository"]["current_ref"], "refs/heads/worktree-branch")

    def test_non_git_task_does_not_fall_back_to_another_project_or_process_cwd(self):
        self.task("non-git-task", self.root)
        self.server = Server(cwd=self.repo_b, codex_home=self.home)
        self.desktop({"non-git-task": {"projectKind": "local", "projectId": "a"}})
        result = self.call("non-git-task")
        self.assertTrue(result["needs_repository"])
        self.assertEqual(result["suggested_path"], str(self.root))
        self.assertIn("不是 Git 仓库", result["reason"])
        self.assertEqual(result["context"]["message_status"], "sent")
        self.assertEqual(result["context"]["repository_status"], "not_found")
        self.assertEqual(result["context"]["paths"], [str(self.root)])

    def test_old_task_after_project_move_uses_its_updated_project_assignment(self):
        self.task("old-task", self.root / "removed-old-checkout")
        self.desktop({"old-task": {"projectKind": "local", "projectId": "a"}})
        self.assertEqual(self.call("old-task")["repository"]["path"], str(self.repo_a))

    def test_missing_context_returns_empty_picker_and_refresh_can_recover(self):
        self.desktop({"other-task": {"projectKind": "local", "projectId": "b"}})
        result = self.call("new-task")
        self.assertTrue(result["needs_repository"])
        self.assertEqual(result["suggested_path"], "")
        self.assertEqual(result["context"]["message_status"], "unknown")
        self.assertEqual(result["context"]["repository_status"], "pending")
        self.task("new-task", self.repo_a)
        result = self.call("new-task", "git_query", action="branches")
        self.assertEqual(result["repository"]["path"], str(self.repo_a))

    def test_multiple_project_roots_require_selection_and_manual_choice_wins(self):
        state = self.desktop({"task-a": {"projectKind": "local", "projectId": "a"}})
        state["local-projects"]["a"]["rootPaths"].append(str(self.repo_b))
        (self.home / ".codex-global-state.json").write_text(json.dumps(state))
        result = self.call("task-a")
        self.assertTrue(result["needs_repository"])
        self.assertEqual({repo["path"] for repo in result["repositories"]}, {str(self.repo_a), str(self.repo_b)})
        result = self.call("task-a", "git_query", action="branches", repo=str(self.repo_b))
        self.assertEqual(result["repository"]["path"], str(self.repo_b))

    def test_invalid_or_conflicting_metadata_and_unreadable_state_never_guess(self):
        context = ProjectContext(self.home)
        for meta in ({"threadId": []}, {"threadId": "../escape"}, {"threadId": "a", "thread_id": "b"}):
            self.assertEqual(context.paths(meta), [])
        (self.home / "state_5.sqlite").write_bytes(b"not a database")
        (self.home / ".codex-global-state.json").write_text("{")
        self.assertEqual(context.paths({"threadId": "task-a"}), [])
        self.assertEqual(context.inspect({"threadId": "task-a"})["message_status"], "unknown")
        self.assertIsNone(context.paths({}))

    def test_persisted_no_message_flag_and_refresh_after_first_message(self):
        self.task("draft", self.root, has_user_event=0)
        result = self.call("draft")
        self.assertEqual(result["context"]["message_status"], "not_sent")
        self.assertEqual(result["context"]["repository_status"], "not_found")
        self.task("draft", self.root, has_user_event=1)
        result = self.call("draft", "git_query", action="branches")
        self.assertEqual(result["context"]["message_status"], "sent")
        self.assertEqual(result["context"]["repository_status"], "not_found")
        self.git(self.root, "init", "-b", "main")
        result = self.call("draft", "git_query", action="branches")
        self.assertEqual(result["repository"]["path"], str(self.root))

    def test_ephemeral_task_never_claims_no_messages_or_no_repository(self):
        self.task("other-task", self.repo_a)
        self.desktop({"other-task": {"projectKind": "local", "projectId": "a"}})
        result = self.call("ephemeral-host-task")
        self.assertEqual(result["context"]["message_status"], "unknown")
        self.assertEqual(result["context"]["repository_status"], "pending")
        self.assertEqual(result["context"]["paths"], [])
        self.assertNotIn("不是 Git 仓库", result["reason"])

    def test_git_and_directory_errors_are_not_reported_as_missing_repository(self):
        self.task("task-a", self.repo_a)
        with patch("mcp_server.Repository", side_effect=GitError("找不到 Git。", "git_unavailable")):
            result = self.call("task-a")
        self.assertEqual(result["context"]["repository_status"], "unavailable")
        self.assertEqual(result["context"]["error"], "找不到 Git。")
        self.task("missing-directory", self.root / "does-not-exist")
        result = self.call("missing-directory")
        self.assertEqual(result["context"]["message_status"], "sent")
        self.assertEqual(result["context"]["repository_status"], "unavailable")
        self.assertIn("不存在", result["context"]["error"])

    def test_older_schema_without_message_flag_remains_usable(self):
        with sqlite3.connect(self.home / "state_5.sqlite") as connection:
            connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, cwd TEXT)")
            connection.execute("INSERT INTO threads VALUES (?, ?)", ("older-task", str(self.root)))
        result = self.call("older-task")
        self.assertEqual(result["context"]["message_status"], "unknown")
        self.assertEqual(result["context"]["repository_status"], "not_found")


if __name__ == "__main__":
    unittest.main()
