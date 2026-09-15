"""Integration tests against real, disposable Git repositories."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch as mock_patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from git_explorer import ExplorerServer, GitError, Repository


class GitExplorerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="git-explorer-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "repo with spaces"
        self.path.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_AUTHOR_NAME="Test Author", GIT_AUTHOR_EMAIL="test@example.test",
                        GIT_COMMITTER_NAME="Test Author", GIT_COMMITTER_EMAIL="test@example.test")
        self.git("init", "-b", "main")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", str(self.root / "no-hooks"))
        self.file("hello.txt", "hello\n")
        self.initial = self.commit("Initial commit")
        self.git("branch", "feature/搜索")
        self.file("hello.txt", "hello\nmain change\n")
        self.main = self.commit("Main change", "literal [query].\nSecond paragraph\n<script>alert(1)</script>")
        self.git("checkout", "feature/搜索")
        self.file("空 格\t文件\n.txt", "first\n")
        self.feature = self.commit("Feature search")
        self.git("checkout", "main")
        self.git("update-ref", "refs/remotes/origin/main", self.initial)
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.git("config", "remote.origin.url", str(self.root / "nonexistent"))
        self.git("config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
        self.git("config", "branch.main.remote", "origin")
        self.git("config", "branch.main.merge", "refs/heads/main")
        self.repo = Repository(self.path)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.path), *args], env=self.env, stderr=subprocess.PIPE).decode().strip()

    def file(self, path, text):
        p = self.path / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def commit(self, subject, body=None):
        self.git("add", "--all")
        args = ["commit", "-m", subject]
        if body:
            args.extend(["-m", body])
        self.git(*args)
        return self.git("rev-parse", "HEAD")

    def test_branches_current_remote_and_alias(self):
        data = self.repo.branches()
        self.assertEqual(data["repository"]["current_ref"], "refs/heads/main")
        branches = {b["ref"]: b for b in data["branches"]}
        self.assertEqual(set(branches), {"refs/heads/main", "refs/heads/feature/搜索", "refs/remotes/origin/main"})
        self.assertTrue(branches["refs/heads/main"]["current"])
        self.assertTrue(branches["refs/remotes/origin/main"]["remote"])
        self.assertIn("ahead 1", branches["refs/heads/main"]["tracking"])

    def test_branch_histories_and_stable_pagination(self):
        page = self.repo.commits("refs/heads/main", limit=1)
        self.assertEqual([c["sha"] for c in page["commits"]], [self.main])
        self.assertEqual(page["commits"][0]["stats"],
                         {"additions": 1, "deletions": 0, "files_changed": 1, "binary_files": 0})
        self.assertTrue(page["has_more"])
        self.file("new.txt", "new")
        self.commit("New tip")
        next_page = self.repo.commits(page["snapshot"], limit=1, offset=page["next_offset"])
        self.assertEqual([c["sha"] for c in next_page["commits"]], [self.initial])
        self.assertEqual(next_page["commits"][0]["stats"]["additions"], 1)
        self.assertFalse(next_page["has_more"])
        feature = self.repo.commits("refs/heads/feature/搜索")
        self.assertEqual([c["sha"] for c in feature["commits"]], [self.feature, self.initial])
        self.assertEqual([c["stats"]["additions"] for c in feature["commits"]], [1, 1])

    def test_literal_search_author_and_multiline_message(self):
        data = self.repo.commits("refs/heads/main", query="[query].", author="test@example.test")
        self.assertEqual(len(data["commits"]), 1)
        self.assertIn("Second paragraph", data["commits"][0]["message"])
        self.assertIn("<script>", data["commits"][0]["message"])
        self.assertEqual(data["commits"][0]["stats"]["additions"], 1)
        self.assertEqual(self.repo.commits("refs/heads/main", query=".*")["commits"], [])
        self.assertEqual(self.repo.commits("refs/heads/main", author="Nobody")["commits"], [])

    def test_root_commit_and_patch(self):
        data = self.repo.commit(self.initial)
        self.assertEqual(data["parents"], [])
        self.assertEqual(data["files"], [{"status": "A", "path": "hello.txt"}])
        patch = self.repo.patch(self.initial, "hello.txt")
        self.assertIn("+hello", patch["patch"])

    def test_file_names_are_nul_delimited_and_literal(self):
        data = self.repo.commit(self.feature)
        self.assertEqual(data["files"][0]["path"], "空 格\t文件\n.txt")
        self.assertIn("+first", self.repo.patch(self.feature, "空 格\t文件\n.txt")["patch"])
        self.file("[special]*.txt", "special\n")
        self.file("other.txt", "other\n")
        sha = self.commit("literal paths")
        self.assertNotIn("other.txt", self.repo.patch(sha, "[special]*.txt")["patch"])

    def test_merge_parents_and_first_parent_history(self):
        self.file("main-only.txt", "main only\nsecond line\n")
        self.commit("Main-only addition")
        self.git("merge", "--no-ff", "feature/搜索", "-m", "Merge feature")
        sha = self.git("rev-parse", "HEAD")
        data = self.repo.commit(sha)
        self.assertEqual(len(data["parents"]), 2)
        self.assertEqual(data["files"][0]["path"], "空 格\t文件\n.txt")
        second = self.repo.commit(sha, 1)
        self.assertEqual(second["files"][0]["path"], "hello.txt")
        first_parent = self.repo.commits("HEAD", first_parent=True)
        self.assertEqual(first_parent["commits"][0]["stats"],
                         {"additions": 1, "deletions": 0, "files_changed": 1, "binary_files": 0})
        self.assertNotIn(self.feature, [c["sha"] for c in first_parent["commits"]])
        self.assertIn(self.feature, [c["sha"] for c in self.repo.commits("HEAD")["commits"]])

    def test_line_counts_mixed_changes_binary_and_unusual_names(self):
        self.file("hello.txt", "replacement one\nreplacement two\nreplacement three\n")
        self.file("\nleading newline\tname.txt", "first\nsecond\n")
        (self.path / "binary.dat").write_bytes(b"\x00\xffdata")
        sha = self.commit("Mixed line changes")
        row = self.repo.commits(sha, limit=1)["commits"][0]
        self.assertEqual(row["stats"],
                         {"additions": 5, "deletions": 2, "files_changed": 3, "binary_files": 1})
        (self.path / "hello.txt").unlink()
        deleted = self.commit("Delete text file")
        row = self.repo.commits(deleted, limit=1)["commits"][0]
        self.assertEqual(row["stats"],
                         {"additions": 0, "deletions": 3, "files_changed": 1, "binary_files": 0})

    def test_empty_commit_has_zero_line_counts(self):
        self.git("commit", "--allow-empty", "-m", "Empty commit")
        row = self.repo.commits(limit=1)["commits"][0]
        self.assertEqual(row["stats"],
                         {"additions": 0, "deletions": 0, "files_changed": 0, "binary_files": 0})

    def test_unavailable_line_counts_preserve_history_and_can_retry(self):
        with mock_patch.object(self.repo, "commit_stats", side_effect=GitError("Git 查询超时")):
            data = self.repo.commits("refs/heads/main", limit=1)
        self.assertEqual([c["sha"] for c in data["commits"]], [self.main])
        self.assertTrue(data["has_more"])
        self.assertIsNone(data["commits"][0]["stats"])
        self.assertIn("超时", data["commits"][0]["stats_error"])
        self.assertEqual(self.repo.commits("refs/heads/main", limit=1)["commits"][0]["stats"]["additions"], 1)

    def test_empty_detached_worktree_and_bare(self):
        empty = self.root / "empty"
        subprocess.check_output(["git", "init", "-b", "main", str(empty)], stderr=subprocess.PIPE)
        repo = Repository(empty)
        self.assertTrue(repo.branches()["branches"][0]["unborn"])
        self.assertEqual(repo.commits()["commits"], [])
        self.git("checkout", "--detach", self.initial)
        self.assertTrue(self.repo.info()["detached"])
        worktree = self.root / "linked worktree"
        self.git("worktree", "add", str(worktree), "feature/搜索")
        self.assertEqual(Repository(worktree).info()["current_ref"], "refs/heads/feature/搜索")
        bare = self.root / "bare.git"
        self.git("clone", "--bare", str(self.path), str(bare))
        self.assertTrue(Repository(bare).info()["bare"])

    def test_invalid_refs_and_parameters(self):
        for ref in ["--all", "HEAD~1", "refs/heads/main..feature/搜索", "main;touch /tmp/no", "refs/heads/missing"]:
            with self.subTest(ref=ref), self.assertRaises(GitError):
                self.repo.commits(ref)
        for kwargs in [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"query": "bad\0query"}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(GitError):
                self.repo.commits(**kwargs)
        with self.assertRaises(GitError):
            self.repo.patch(self.main, "../../etc/passwd")

    def test_binary_large_patch_and_no_external_diff(self):
        (self.path / "binary.dat").write_bytes(b"\x00\xffdata")
        self.file("large.txt", "x" * 1_000_000)
        sha = self.commit("Large and binary")
        self.assertIn("Binary files", self.repo.patch(sha, "binary.dat")["patch"])
        self.assertTrue(self.repo.patch(sha, "large.txt")["truncated"])
        sentinel = self.root / "external-command-was-run"
        self.git("config", "diff.external", "touch " + str(sentinel))
        self.repo.patch(self.main, "hello.txt")
        self.repo.commits(limit=1)
        self.assertFalse(sentinel.exists())

    def test_read_operations_preserve_repo_and_dirty_worktree(self):
        self.file("dirty.txt", "leave me")
        before = self.git("status", "--porcelain=v1")
        head = self.git("rev-parse", "HEAD")
        refs = self.git("show-ref")
        index = (self.path / ".git/index").read_bytes()
        self.repo.branches()
        self.repo.commits("refs/heads/feature/搜索")
        self.repo.commit(self.main)
        self.repo.patch(self.main, "hello.txt")
        self.assertEqual(before, self.git("status", "--porcelain=v1"))
        self.assertEqual(head, self.git("rev-parse", "HEAD"))
        self.assertEqual(refs, self.git("show-ref"))
        self.assertEqual(index, (self.path / ".git/index").read_bytes())

    def test_http_routes_session_origin_and_traversal(self):
        server = ExplorerServer(self.repo)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        response = urllib.request.urlopen(server.url + "api/branches")
        self.assertEqual(json.load(response)["repository"]["path"], self.repo.path)
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(urllib.request.urlopen(server.url).status, 200)
        for url, headers, status in [
            (server.origin + "/api/branches", {}, 404),
            (server.url + "../../etc/passwd", {}, 404),
            (server.url + "api/branches", {"Origin": "https://evil.example"}, 403),
            (server.url + "api/branches", {"Host": "evil.example"}, 403),
            (server.url + "api/commits?limit=-2", {}, 400)]:
            with self.subTest(url=url), self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(urllib.request.Request(url, headers=headers))
            self.assertEqual(caught.exception.code, status)

    def test_background_launcher_and_stop(self):
        script = Path(__file__).resolve().parents[1] / "scripts/git_explorer.py"
        raw = subprocess.check_output([sys.executable, str(script), "start", "--repo", str(self.path),
                                       "--idle-seconds", "10"], timeout=15)
        result = json.loads(raw)
        url = result["url"]
        try:
            self.assertEqual(json.load(urllib.request.urlopen(url + "api/branches"))["repository"]["path"], self.repo.path)
        finally:
            request = urllib.request.Request(url + "api/stop", method="POST", data=b"")
            self.assertTrue(json.load(urllib.request.urlopen(request))["stopped"])
        for _ in range(30):
            try:
                urllib.request.urlopen(url, timeout=.2)
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                break
            time.sleep(.1)
        else:
            self.fail("Service did not stop after the stop request")


if __name__ == "__main__":
    unittest.main()
