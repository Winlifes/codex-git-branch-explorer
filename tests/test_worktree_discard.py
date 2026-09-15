"""Discard behavior and data preservation in isolated, disposable worktrees."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from test_git_operations import OperationTests
from git_operations import status
from git_explorer import GitError, Repository
from worktree_discard import create_backup


class DiscardTests(OperationTests):
    # Reuse the fixture, but do not rerun inherited operation tests in this suite.
    def backup_files(self, result):
        root = Path(result["backup_path"])
        manifest = json.loads((root / "manifest.json").read_text())
        return {item["path"]: (root / item["storage"]).read_bytes()
                if item["kind"] == "file" else item for item in manifest["files"]}

    def test_discard_one_preserves_staging_and_other_work(self):
        self.file("tracked.txt", "staged version\n")
        self.git("add", "tracked.txt")
        index = self.git("ls-files", "--stage")
        self.file("tracked.txt", "unstaged version\n")
        self.file("leave.txt", "leave me\n")
        before = (self.path / ".git/index").read_bytes()
        plan = self.ops.prepare(self.repo, "discard", {"paths": ["tracked.txt"]}, "task-a")
        self.assertEqual(before, (self.path / ".git/index").read_bytes())
        self.assertFalse((self.path / ".git/codex-git-explorer").exists())
        self.assertEqual((self.path / "tracked.txt").read_text(), "unstaged version\n")
        result = self.ops.apply(self.repo, plan["token"], "task-a")
        self.assertTrue(result["ok"], result)
        self.assertEqual((self.path / "tracked.txt").read_text(), "staged version\n")
        self.assertEqual((self.path / "leave.txt").read_text(), "leave me\n")
        self.assertEqual(index, self.git("ls-files", "--stage"))
        self.assertEqual(self.git("rev-parse", "HEAD"), self.initial)
        self.assertEqual(self.backup_files(result), {"tracked.txt": b"unstaged version\n"})

    def test_discard_all_new_deleted_binary_and_literal_names(self):
        self.file(".gitignore", "ignored.txt\n")
        self.file("deleted.txt", "restore me\n")
        self.git("add", "."); self.git("commit", "-m", "Fixture paths")
        head = self.git("rev-parse", "HEAD")
        self.file("staged.txt", "keep staged\n"); self.git("add", "staged.txt")
        index = self.git("ls-files", "--stage")
        (self.path / "deleted.txt").unlink()
        self.file("tracked.txt", "discard this\n")
        self.file("ignored.txt", "ignored data\n")
        names = ["new/你好.txt", "line\nname\t.txt", "-option.txt", ":(glob)*"]
        for name in names: self.file(name, "new file\n")
        (self.path / "binary.bin").write_bytes(b"\0binary\xff")
        result = self.apply("discard", all=True)
        self.assertEqual((self.path / "tracked.txt").read_text(), "base\n")
        self.assertEqual((self.path / "deleted.txt").read_text(), "restore me\n")
        self.assertEqual((self.path / "ignored.txt").read_text(), "ignored data\n")
        self.assertTrue(all(not (self.path / n).exists() for n in names + ["binary.bin"]))
        self.assertEqual(index, self.git("ls-files", "--stage"))
        self.assertEqual(head, self.git("rev-parse", "HEAD"))
        self.assertEqual(status(self.repo)["unstaged_count"], 0)
        backed = self.backup_files(result)
        self.assertEqual(backed["binary.bin"], b"\0binary\xff")
        self.assertEqual(backed["deleted.txt"]["kind"], "missing")
        self.assertNotIn("ignored.txt", backed)
        for name in names: self.assertEqual(backed[name], b"new file\n")

    def test_discard_symlink_never_reads_or_changes_target(self):
        outside = self.root / "outside.txt"; outside.write_text("outside data\n")
        (self.path / "new-link").symlink_to(outside)
        (self.path / "tracked.txt").unlink()
        (self.path / "tracked.txt").symlink_to(outside)
        result = self.apply("discard", all=True)
        self.assertEqual(outside.read_text(), "outside data\n")
        self.assertFalse((self.path / "new-link").is_symlink())
        self.assertFalse((self.path / "tracked.txt").is_symlink())
        self.assertEqual((self.path / "tracked.txt").read_text(), "base\n")
        backup = self.backup_files(result)
        self.assertEqual(backup["tracked.txt"]["kind"], "symlink")
        self.assertEqual(backup["new-link"]["target"], str(outside))

    def test_discard_unborn_and_intent_to_add(self):
        empty = self.root / "empty"; empty.mkdir()
        self.git("init", "-b", "main", path=empty)
        self.path, self.repo = empty, Repository(empty)
        self.file("staged.txt", "keep staged\n"); self.git("add", "staged.txt")
        self.file("staged.txt", "unstaged edit\n")
        self.file("intent.txt", "intent content\n"); self.git("add", "-N", "intent.txt")
        self.file("new.txt", "new\n")
        result = self.apply("discard", all=True)
        self.assertEqual((empty / "staged.txt").read_text(), "keep staged\n")
        self.assertFalse((empty / "intent.txt").exists())
        self.assertFalse((empty / "new.txt").exists())
        self.assertEqual(self.git("ls-files"), "staged.txt")
        self.assertEqual(status(self.repo)["staged_count"], 1)
        self.assertEqual(self.backup_files(result)["intent.txt"], b"intent content\n")

    def test_discard_stale_and_replayed_confirmation(self):
        self.file("new.txt", "first\n")
        plan = self.ops.prepare(self.repo, "discard", {"all": True})
        self.file("late.txt", "arrived after preview\n")
        with self.assertRaisesRegex(GitError, "状态已变化"):
            self.ops.apply(self.repo, plan["token"])
        plan = self.ops.prepare(self.repo, "discard", {"paths": ["new.txt"]})
        first = self.ops.apply(self.repo, plan["token"])
        self.assertTrue(first["ok"], first)
        self.file("new.txt", "created after discard\n")
        self.assertEqual(first, self.ops.apply(self.repo, plan["token"]))
        self.assertEqual((self.path / "new.txt").read_text(), "created after discard\n")
        self.assertTrue((self.path / "late.txt").exists())

    def test_discard_backup_failure_changes_nothing(self):
        self.file("tracked.txt", "keep this\n")
        self.file("new.txt", "keep new\n")
        plan = self.ops.prepare(self.repo, "discard", {"all": True})
        with patch("git_operations.create_backup", side_effect=OSError("disk full")):
            result = self.ops.apply(self.repo, plan["token"])
        self.assertFalse(result["ok"])
        self.assertEqual((self.path / "tracked.txt").read_text(), "keep this\n")
        self.assertEqual((self.path / "new.txt").read_text(), "keep new\n")

    def test_discard_rechecks_changes_after_backing_up(self):
        self.file("tracked.txt", "first\n")
        plan = self.ops.prepare(self.repo, "discard", {"all": True})
        def concurrent_edit(repo, paths):
            saved = create_backup(repo, paths)
            self.file("tracked.txt", "edited while backing up\n")
            return saved
        with patch("git_operations.create_backup", side_effect=concurrent_edit):
            result = self.ops.apply(self.repo, plan["token"])
        self.assertFalse(result["ok"])
        self.assertIn("状态已变化", result["message"])
        self.assertEqual((self.path / "tracked.txt").read_text(), "edited while backing up\n")
        self.assertEqual(self.backup_files(result)["tracked.txt"], b"first\n")

    def test_discard_all_is_not_limited_to_a_single_selection_batch(self):
        for i in range(501): self.file("bulk/" + str(i) + ".txt", "new\n")
        plan = self.ops.prepare(self.repo, "discard", {"all": True})
        self.assertEqual(len(plan["files"]), 501)
        result = self.ops.apply(self.repo, plan["token"])
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(self.backup_files(result)), 501)
        self.assertTrue(status(self.repo)["clean"])

    def test_discard_rejects_nested_repo_submodule_and_symlink_parent(self):
        child = self.path / "nested"; child.mkdir()
        self.git("init", "-b", "main", path=child)
        self.file("tracked.txt", "keep this\n")
        with self.assertRaises(GitError): self.ops.prepare(self.repo, "discard", {"all": True})
        self.assertEqual((self.path / "tracked.txt").read_text(), "keep this\n")
        child.rename(self.root / "child")
        self.git("update-index", "--add", "--cacheinfo", "160000," + self.initial + ",module")
        with self.assertRaisesRegex(GitError, "子模块"):
            self.ops.prepare(self.repo, "discard", {"all": True})
        self.git("rm", "--cached", "module")
        self.file("dir/file.txt", "original\n")
        self.git("add", "dir/file.txt"); self.git("commit", "-m", "Directory fixture")
        (self.path / "dir/file.txt").unlink(); (self.path / "dir").rmdir()
        outside = self.root / "outside"; outside.mkdir(); (outside / "file.txt").write_text("external\n")
        (self.path / "dir").symlink_to(outside)
        with self.assertRaises(GitError):
            self.ops.prepare(self.repo, "discard", {"all": True})
        self.assertEqual((outside / "file.txt").read_text(), "external\n")

    def test_discard_rejects_staged_only_conflicts_and_invalid_paths(self):
        self.file("tracked.txt", "staged\n"); self.git("add", "tracked.txt")
        for params in ({"paths": ["tracked.txt"]}, {"paths": ["../outside"]}, {"all": "yes"},
                       {"all": True, "paths": ["tracked.txt"]}, {"paths": ["x", "x"]}, {"paths": [1]}):
            with self.subTest(params=params), self.assertRaises(GitError):
                self.ops.prepare(self.repo, "discard", params)
        self.git("commit", "-m", "Fixture staging")
        self.conflict()
        with self.assertRaisesRegex(GitError, "完成或中止"):
            self.ops.prepare(self.repo, "discard", {"all": True})


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(DiscardTests(name) for name in DiscardTests.__dict__ if name.startswith("test_"))


if __name__ == "__main__":
    unittest.main()
