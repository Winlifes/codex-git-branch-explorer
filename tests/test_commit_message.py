"""Draft generation must match commit scope without changing a real project."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from git_explorer import Repository, GitError
from git_operations import Operations
from mcp_server import Server


class CommitMessageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="commit-draft-test-")
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name).resolve()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Draft Test")
        self.git("config", "user.email", "draft@example.test")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", str(self.path / "no-hooks"))
        self.file("main.py", "def original():\n    return 1\n")
        self.file("delete.txt", "remove me\n")
        self.git("add", "."); self.git("commit", "-m", "Initial")
        self.repo = Repository(self.path)
        self.ops = Operations()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.path), *args], stderr=subprocess.PIPE).decode().strip()

    def file(self, name, content):
        path = self.path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def test_selected_draft_summarizes_content_and_leaves_index_refs_and_files_untouched(self):
        self.file("main.py", "def replacement():\n    return 2\n")
        self.file("unselected.py", "def unrelated(): pass\n")
        self.file("new.py", "def added_method():\n    return 3\n")
        (self.path / "delete.txt").unlink()
        index = (self.path / ".git/index").read_bytes()
        head = self.git("rev-parse", "HEAD")
        data = self.ops.commit_message(self.repo, ["main.py", "new.py", "delete.txt"])
        self.assertIn("replacement", data["message"])
        self.assertIn("added_method", data["message"])
        self.assertIn("新增 new.py", data["message"])
        self.assertIn("删除 delete.txt", data["message"])
        self.assertIn("+2/-2", data["message"])
        self.assertNotIn("unselected", data["message"])
        self.assertEqual((self.path / ".git/index").read_bytes(), index)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual((self.path / "new.py").read_text(), "def added_method():\n    return 3\n")
        self.assertEqual(self.ops.plans, {})

    def test_staged_draft_uses_index_content_and_selected_draft_uses_current_file(self):
        self.file("main.py", "def staged_function():\n    return 2\n")
        self.git("add", "main.py")
        self.file("main.py", "def working_function():\n    return 3\n")
        self.file("new.py", "def not_staged(): pass\n")
        staged = self.ops.commit_message(self.repo, staged=True)
        selected = self.ops.commit_message(self.repo, ["main.py"])
        self.assertIn("staged_function", staged["message"])
        self.assertNotIn("working_function", staged["message"])
        self.assertNotIn("not_staged", staged["message"])
        self.assertIn("working_function", selected["message"])
        self.assertNotIn("staged_function", selected["message"])
        self.assertEqual(staged["files"], ["main.py"])

    def test_unborn_repository_supports_selected_and_staged_drafts(self):
        empty = self.path / "empty"
        empty.mkdir()
        subprocess.check_call(["git", "-C", str(empty), "init", "-b", "main"], stdout=subprocess.DEVNULL)
        (empty / "first.py").write_text("def first(): pass\n")
        repo = Repository(empty)
        self.assertIn("新增 first.py", self.ops.commit_message(repo, ["first.py"])["message"])
        subprocess.check_call(["git", "-C", str(empty), "add", "."])
        self.assertIn("新增 first.py", self.ops.commit_message(repo, staged=True)["message"])

    def test_literal_paths_and_control_characters_are_preserved_as_data(self):
        paths = [":(glob)*.py", "line\nname.py", "-option.py", "中文.py"]
        for name in paths:
            self.file(name, "def literal(): pass\n")
        data = self.ops.commit_message(self.repo, paths)
        self.assertEqual(data["files"], paths)
        self.assertIn("line\\nname.py", data["message"])
        self.assertIn(":(glob)*.py", data["message"])

    def test_edited_message_is_the_message_saved_in_the_confirmed_commit(self):
        self.file("main.py", "def changed(): return 2\n")
        self.ops.commit_message(self.repo, ["main.py"])
        edited = "用户编辑的说明\n\nPreserve this body."
        preview = self.ops.prepare(self.repo, "commit_selected", {"paths": ["main.py"], "message": edited}, "task")
        result = self.ops.apply(self.repo, preview["token"], "task")
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.git("log", "-1", "--format=%B"), edited)

    def test_empty_invalid_and_mixed_scopes_are_rejected(self):
        for paths in ([], ["missing.py"], ["../outside"], ["main.py", "main.py"], [1]):
            with self.subTest(paths=paths), self.assertRaises(GitError):
                self.ops.commit_message(self.repo, paths)
        with self.assertRaises(GitError):
            self.ops.commit_message(self.repo, ["main.py"], staged=True)
        with self.assertRaises(GitError):
            self.ops.commit_message(self.repo, staged=True)

    def test_reverted_worktree_has_no_selected_commit_content(self):
        original = (self.path / "main.py").read_text()
        self.file("main.py", "staged change\n"); self.git("add", "main.py")
        self.file("main.py", original)
        with self.assertRaises(GitError):
            self.ops.commit_message(self.repo, ["main.py"])
        self.assertIn("main.py", self.ops.commit_message(self.repo, staged=True)["message"])

    def test_recreated_index_deletion_is_an_update_in_selected_commit(self):
        self.git("rm", "delete.txt")
        self.file("delete.txt", "replacement content\n")
        data = self.ops.commit_message(self.repo, ["delete.txt"])
        self.assertIn("更新 delete.txt", data["message"])
        self.assertNotIn("新增 delete.txt", data["message"])

    def test_binary_and_large_files_produce_bounded_honest_drafts(self):
        (self.path / "image.bin").write_bytes(b"\0binary\xff")
        self.file("large.py", "def large(): pass\n" + "x\n" * 50_000)
        data = self.ops.commit_message(self.repo, ["image.bin", "large.py"])
        self.assertIn("二进制文件", data["message"])
        self.assertTrue(data["partial"])
        self.assertLess(len(data["message"]), 10000)

    @unittest.skipUnless(hasattr(os, "symlink"), "Symlinks unavailable")
    def test_symlinks_do_not_read_target_content(self):
        target = self.path / "outside.txt"
        target.write_text("def secret_outside(): pass\n")
        (self.path / "link.py").symlink_to(target)
        data = self.ops.commit_message(self.repo, ["link.py"])
        self.assertNotIn("secret_outside", data["message"])

    def test_config_key_names_are_included_but_values_and_instructions_are_not(self):
        self.file("settings.json", '{"enablePreview": true, "token": "never-include-this-value"}\n')
        data = self.ops.commit_message(self.repo, ["settings.json"])
        self.assertIn("enablePreview", data["message"])
        self.assertNotIn("never-include-this-value", data["message"])

    def test_mcp_read_only_query_uses_the_requested_language_and_rejects_extra_options(self):
        self.file("main.py", "def changed(): pass\n")
        server = Server(self.path)
        result = server.call("git_query", {"repo": str(self.path), "action": "commit_message", "paths": ["main.py"]}, {"openai/locale": "en-US"})
        self.assertTrue(result["_meta"]["gitExplorer"]["message"].startswith("Update main.py"))
        with self.assertRaises(GitError):
            server.call("git_query", {"repo": str(self.path), "action": "commit_message", "paths": ["main.py"], "sha": "HEAD"})
        with self.assertRaises(GitError):
            server.call("git_query", {"repo": str(self.path), "action": "commit_message", "paths": [1]})

    def test_state_change_during_generation_is_rejected(self):
        self.file("main.py", "def changed(): pass\n")
        def moved(*args, **kwargs):
            self.file("main.py", "changed again\n")
            return {"message": "stale", "files": ["main.py"], "partial": False}
        with patch("git_operations.generate_commit_message", side_effect=moved), self.assertRaises(GitError):
            self.ops.commit_message(self.repo, ["main.py"])
