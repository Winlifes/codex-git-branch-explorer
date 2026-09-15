"""Exercise mutations only in disposable repositories and local bare remotes."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from git_explorer import Repository, GitError
from git_operations import Operations, status, working_patch
from mcp_server import Server


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="git-operations-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "仓库 with spaces"
        self.path.mkdir()
        self.global_config = self.root / "test.gitconfig"
        self.global_config.write_text('[user]\n name = Panel Test\n email = panel@example.test\n[commit]\n gpgsign = false\n[core]\n hooksPath = ' + str(self.root / "no-hooks") + '\n')
        # Isolate Git's real configuration without changing the user's environment.
        original_popen = subprocess.Popen
        def isolated_popen(*a, **kw):
            kw["env"] = {**kw.get("env", os.environ), "GIT_CONFIG_GLOBAL": str(self.global_config), "GIT_CONFIG_NOSYSTEM": "1"}
            return original_popen(*a, **kw)
        self.patcher = patch("git_operations.subprocess.Popen", side_effect=isolated_popen)
        self.patcher.start(); self.addCleanup(self.patcher.stop)
        self.git("init", "-b", "main")
        self.file("tracked.txt", "base\n")
        self.git("add", "."); self.git("commit", "-m", "Initial")
        self.initial = self.git("rev-parse", "HEAD")
        self.repo = Repository(self.path)
        self.ops = Operations()

    def git(self, *args, path=None):
        return subprocess.check_output(["git", "-C", str(path or self.path), *args], stderr=subprocess.PIPE).decode().strip()

    def file(self, name, text):
        path = self.path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def apply(self, action, **params):
        preview = self.ops.prepare(self.repo, action, params, "task-a")
        result = self.ops.apply(self.repo, preview["token"], "task-a")
        self.assertTrue(result["ok"], result)
        return result

    def test_preview_and_status_do_not_change_index_worktree_or_refs(self):
        self.file("tracked.txt", "pending\n")
        index = (self.path / ".git/index").read_bytes()
        refs = self.git("show-ref")
        self.ops.prepare(self.repo, "stage", {"paths": ["tracked.txt"]})
        self.assertEqual(index, (self.path / ".git/index").read_bytes())
        self.assertEqual(refs, self.git("show-ref"))
        self.assertEqual((self.path / "tracked.txt").read_text(), "pending\n")
        self.assertEqual(status(self.repo)["fingerprint"], status(self.repo)["fingerprint"])

    def test_literal_paths_stage_unstage_preserves_files(self):
        paths = ["line\nname\t.txt", "-option.txt", ":(glob)*"]
        for name in paths:
            self.file(name, "literal\n")
        self.apply("stage", paths=paths)
        self.assertEqual(status(self.repo)["staged_count"], 3)
        self.apply("unstage", paths=paths)
        self.assertEqual(status(self.repo)["staged_count"], 0)
        self.assertTrue(all((self.path / p).read_text() == "literal\n" for p in paths))

    def test_commit_only_staged_content_uses_user_config_and_no_duplicate(self):
        self.file("tracked.txt", "staged content\n")
        self.apply("stage", paths=["tracked.txt"])
        self.file("tracked.txt", "unstaged content\n")
        plan = self.ops.prepare(self.repo, "commit", {"message": "Panel commit\n\nDetails"}, "task-a")
        self.assertTrue(self.ops.apply(self.repo, plan["token"], "task-a")["ok"])
        head = self.git("rev-parse", "HEAD")
        self.assertEqual(self.git("show", "HEAD:tracked.txt"), "staged content")
        self.assertEqual((self.path / "tracked.txt").read_text(), "unstaged content\n")
        self.assertEqual(self.git("show", "-s", "--format=%an <%ae>"), "Panel Test <panel@example.test>")
        self.assertTrue(self.ops.apply(self.repo, plan["token"], "task-a")["ok"])
        self.assertEqual(head, self.git("rev-parse", "HEAD"))

    def test_unborn_unstage_then_root_commit(self):
        empty = self.root / "empty"; empty.mkdir()
        self.git("init", "-b", "main", path=empty)
        self.path, self.repo = empty, Repository(empty)
        self.file("new.txt", "new\n")
        self.apply("stage", paths=["new.txt"])
        self.file("new.txt", "newer\n")
        self.apply("unstage", paths=["new.txt"])
        self.assertEqual((empty / "new.txt").read_text(), "newer\n")
        self.apply("stage", paths=["new.txt"])
        self.apply("commit", message="Root from panel")
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "1")

    def test_stale_preview_same_status_code_and_cross_task_are_rejected(self):
        self.file("tracked.txt", "first\n")
        plan = self.ops.prepare(self.repo, "stage", {"paths": ["tracked.txt"]}, "task-a")
        with self.assertRaises(GitError): self.ops.apply(self.repo, plan["token"], "task-b")
        self.file("tracked.txt", "second\n")
        with self.assertRaisesRegex(GitError, "状态已变化"):
            self.ops.apply(self.repo, plan["token"], "task-a")
        self.assertEqual(status(self.repo)["staged_count"], 0)

    def test_expired_and_wrong_repo_tokens_are_rejected(self):
        plan = self.ops.prepare(self.repo, "create", {"name": "new", "checkout": False})
        other = self.root / "other"; other.mkdir()
        self.git("init", "-b", "main", path=other)
        with self.assertRaises(GitError): self.ops.apply(Repository(other), plan["token"])
        self.ops.plans[plan["token"]]["created"] -= 301
        with self.assertRaises(GitError): self.ops.apply(self.repo, plan["token"])
        self.assertEqual(self.git("branch", "--list", "new"), "")

    def test_create_switch_and_safe_delete(self):
        self.apply("create", ref="HEAD", name="feature/中文", checkout=True)
        self.assertEqual(self.repo.info()["current_ref"], "refs/heads/feature/中文")
        self.apply("switch", ref="refs/heads/main")
        self.apply("delete", ref="refs/heads/feature/中文")
        self.assertEqual(self.git("branch", "--list", "feature/中文"), "")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.initial)

    def test_unmerged_current_and_checked_out_branch_not_deleted(self):
        self.git("switch", "-c", "feature")
        self.file("feature.txt", "keep\n"); self.git("add", "."); self.git("commit", "-m", "Unmerged")
        self.git("switch", "main")
        with self.assertRaisesRegex(GitError, "尚未合并"):
            self.ops.prepare(self.repo, "delete", {"ref": "refs/heads/feature"})
        with self.assertRaisesRegex(GitError, "当前分支"):
            self.ops.prepare(self.repo, "delete", {"ref": "refs/heads/main"})
        self.git("branch", "linked")
        self.git("worktree", "add", str(self.root / "linked"), "linked")
        plan = self.ops.prepare(self.repo, "delete", {"ref": "refs/heads/linked"})
        result = self.ops.apply(self.repo, plan["token"])
        self.assertFalse(result["ok"])
        self.assertTrue(self.git("branch", "--list", "linked"))

    def test_dirty_worktree_blocks_switch_merge_pull_revert(self):
        self.git("branch", "feature")
        self.file("untracked.txt", "keep\n")
        for action, params in [("switch", {"ref": "refs/heads/feature"}), ("merge", {"ref": "refs/heads/feature"}),
                               ("pull", {"remote": "origin", "branch": "main"}), ("revert", {"sha": self.initial})]:
            with self.subTest(action=action), self.assertRaisesRegex(GitError, "未提交"):
                self.ops.prepare(self.repo, action, params)
        self.assertEqual((self.path / "untracked.txt").read_text(), "keep\n")

    def conflict(self):
        self.git("switch", "-c", "feature")
        self.file("tracked.txt", "feature\n"); self.git("add", "."); self.git("commit", "-m", "Feature")
        self.git("switch", "main")
        self.file("tracked.txt", "main\n"); self.git("add", "."); self.git("commit", "-m", "Main")
        before = self.git("rev-parse", "HEAD")
        plan = self.ops.prepare(self.repo, "merge", {"ref": "refs/heads/feature"})
        result = self.ops.apply(self.repo, plan["token"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"]["conflict_count"], 1)
        self.assertEqual(result["status"]["operation"], "merge")
        return before

    def test_merge_conflict_stage_and_continue(self):
        self.conflict()
        with self.assertRaisesRegex(GitError, "冲突"):
            self.ops.prepare(self.repo, "continue", {})
        self.file("tracked.txt", "resolved\n")
        self.apply("stage", paths=["tracked.txt"])
        self.apply("continue")
        self.assertIsNone(status(self.repo)["operation"])
        self.assertEqual(len(self.git("show", "-s", "--format=%P").split()), 2)
        self.assertEqual(self.git("show", "HEAD:tracked.txt"), "resolved")

    def test_merge_conflict_abort_restores_start(self):
        before = self.conflict()
        self.apply("abort")
        self.assertEqual(before, self.git("rev-parse", "HEAD"))
        self.assertEqual((self.path / "tracked.txt").read_text(), "main\n")
        self.assertTrue(status(self.repo)["clean"])

    def test_revert_preserves_history(self):
        self.file("tracked.txt", "change\n"); self.git("add", "."); self.git("commit", "-m", "Change")
        sha = self.git("rev-parse", "HEAD")
        self.apply("revert", sha=sha)
        self.assertEqual(self.git("rev-parse", "HEAD^"), sha)
        self.assertEqual((self.path / "tracked.txt").read_text(), "base\n")
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "3")

    def test_revert_conflict_can_be_resolved_and_continued(self):
        self.file("tracked.txt", "first change\n"); self.git("add", "."); self.git("commit", "-m", "First change")
        sha = self.git("rev-parse", "HEAD")
        self.file("tracked.txt", "second change\n"); self.git("add", "."); self.git("commit", "-m", "Second change")
        before = self.git("rev-parse", "HEAD")
        plan = self.ops.prepare(self.repo, "revert", {"sha": sha})
        result = self.ops.apply(self.repo, plan["token"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"]["operation"], "revert")
        self.assertEqual(result["status"]["conflict_count"], 1)
        self.file("tracked.txt", "resolved reverse\n")
        self.apply("stage", paths=["tracked.txt"])
        self.apply("continue")
        self.assertEqual(self.git("rev-parse", "HEAD^"), before)
        self.assertIsNone(status(self.repo)["operation"])

    def test_submodule_head_changes_invalidate_stage_preview(self):
        child = self.root / "child"; child.mkdir()
        self.git("init", "-b", "main", path=child)
        (child / "child.txt").write_text("one\n")
        self.git("add", ".", path=child); self.git("commit", "-m", "Child", path=child)
        self.git("-c", "protocol.file.allow=always", "submodule", "add", str(child), "module")
        self.git("commit", "-m", "Add module")
        module = self.path / "module"
        for text in ("two\n", "three\n"):
            (module / "child.txt").write_text(text)
            self.git("add", ".", path=module); self.git("commit", "-m", text.strip(), path=module)
            if text == "two\n":
                plan = self.ops.prepare(self.repo, "stage", {"paths": ["module"]})
        with self.assertRaisesRegex(GitError, "状态已变化"):
            self.ops.apply(self.repo, plan["token"])
        self.assertEqual(status(self.repo)["staged_count"], 0)

    def test_revert_merge_requires_explicit_mainline(self):
        self.git("switch", "-c", "feature")
        self.file("feature.txt", "feature\n"); self.git("add", "."); self.git("commit", "-m", "Feature")
        self.git("switch", "main"); self.git("merge", "--no-ff", "feature", "-m", "Merge")
        sha = self.git("rev-parse", "HEAD")
        with self.assertRaisesRegex(GitError, "主线"):
            self.ops.prepare(self.repo, "revert", {"sha": sha})
        self.apply("revert", sha=sha, mainline=1)
        self.assertFalse((self.path / "feature.txt").exists())
        self.assertEqual(self.git("rev-parse", "HEAD^"), sha)

    def remote(self):
        bare = self.root / "remote.git"
        self.git("init", "--bare", "-b", "main", str(bare))
        self.git("remote", "add", "origin", str(bare))
        self.apply("push", remote="origin", branch="main", set_upstream=True)
        clone = self.root / "peer"
        self.git("clone", str(bare), str(clone))
        (clone / "peer.txt").write_text("from remote\n")
        self.git("add", ".", path=clone); self.git("commit", "-m", "Peer", path=clone)
        self.git("push", path=clone)
        return bare, clone

    def test_push_fetch_and_fast_forward_pull(self):
        bare, peer = self.remote()
        self.assertEqual(status(self.repo)["upstream"], {"remote": "origin", "ref": "refs/heads/main"})
        self.apply("fetch", remote="origin")
        self.assertFalse((self.path / "peer.txt").exists())
        self.assertEqual(self.git("rev-parse", "HEAD"), self.initial)
        self.apply("pull", remote="origin", branch="main")
        self.assertEqual((self.path / "peer.txt").read_text(), "from remote\n")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.git("rev-parse", "HEAD", path=peer))

    def test_non_fast_forward_push_and_diverged_pull_leave_history(self):
        bare, peer = self.remote()
        self.file("local.txt", "local\n"); self.git("add", "."); self.git("commit", "-m", "Local")
        local, remote = self.git("rev-parse", "HEAD"), self.git("rev-parse", "HEAD", path=peer)
        for action in ("push", "pull"):
            plan = self.ops.prepare(self.repo, action, {"remote": "origin", "branch": "main"})
            self.assertFalse(self.ops.apply(self.repo, plan["token"])["ok"])
            self.assertEqual(self.git("rev-parse", "HEAD"), local)
            self.assertEqual(self.git("rev-parse", "refs/heads/main", path=bare), remote)
        self.assertIsNone(status(self.repo)["operation"])

    def test_precommit_hook_is_respected_without_losing_staging(self):
        hooks = self.root / "hooks"; hooks.mkdir()
        script = hooks / "pre-commit"; script.write_text("#!/bin/sh\necho 'hook rejected' >&2\nexit 1\n"); script.chmod(0o755)
        self.git("config", "core.hooksPath", str(hooks))
        self.file("tracked.txt", "pending\n"); self.apply("stage", paths=["tracked.txt"])
        plan = self.ops.prepare(self.repo, "commit", {"message": "Should fail"})
        result = self.ops.apply(self.repo, plan["token"])
        self.assertFalse(result["ok"]); self.assertIn("hook rejected", result["message"])
        self.assertEqual(self.git("rev-parse", "HEAD"), self.initial)
        self.assertEqual(status(self.repo)["staged_count"], 1)

    def test_working_diffs_and_symlinks_do_not_read_link_target(self):
        self.file("tracked.txt", "working\n")
        self.assertIn("+working", working_patch(self.repo, "tracked.txt")["patch"])
        self.apply("stage", paths=["tracked.txt"])
        self.assertIn("+working", working_patch(self.repo, "tracked.txt", True)["patch"])
        secret = self.root / "external.txt"; secret.write_text("NEVER_READ_THIS_CONTENT")
        (self.path / "link").symlink_to(secret)
        self.assertNotIn("NEVER_READ_THIS_CONTENT", working_patch(self.repo, "link")["patch"])

    def test_untrusted_arguments_and_forged_tokens_are_rejected(self):
        for action, params in [("create", {"name": "--force"}), ("create", {"name": "../bad"}),
                               ("delete", {"ref": "refs/remotes/origin/main"}),
                               ("stage", {"paths": ["../outside"]}), ("fetch", {"remote": str(self.root)}),
                               ("push", {"remote": "origin", "branch": "main", "force": True})]:
            with self.subTest(action=action, params=params), self.assertRaises(GitError):
                self.ops.prepare(self.repo, action, params)
        with self.assertRaises(GitError): self.ops.apply(self.repo, "forged-token")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.initial)

    def test_mcp_requires_explicit_repository_and_separate_confirmed_write(self):
        server = Server(self.path)
        with self.assertRaises(GitError): server.call("git_apply", {"token": "fake"})
        before = self.git("show-ref")
        args = {"repo": str(self.path), "action": "create", "name": "from-mcp", "checkout": False}
        plan = server.call("git_prepare", args, {"threadId": "one"})["_meta"]["gitExplorer"]
        self.assertEqual(before, self.git("show-ref"))
        result = server.call("git_apply", {"repo": str(self.path), "token": plan["token"]}, {"threadId": "one"})
        self.assertTrue(result["_meta"]["gitExplorer"]["ok"])
        self.assertEqual(self.git("rev-parse", "refs/heads/from-mcp"), self.initial)


if __name__ == "__main__":
    unittest.main()
