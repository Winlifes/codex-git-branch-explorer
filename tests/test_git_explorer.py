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
from urllib.parse import urlencode

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

    def test_multi_branch_log_shows_current_local_and_newer_remote_tips(self):
        remote = self.git("commit-tree", self.git("rev-parse", "main^{tree}"), "-p", self.main, "-m", "Remote-only tip")
        self.git("update-ref", "refs/remotes/origin/main", remote)
        self.git("checkout", "feature/搜索")
        self.file("dirty.txt", "keep local content\n")
        before = self.git("status", "--porcelain=v1"), self.git("show-ref"), (self.path / ".git/index").read_bytes()
        data = self.repo.commits(refs=["refs/heads/feature/搜索", "refs/heads/main", "refs/remotes/origin/main"])
        shas = [item["sha"] for item in data["commits"]]
        self.assertEqual(set(shas), {remote, self.main, self.feature, self.initial})
        self.assertEqual(len(shas), len(set(shas)))
        self.assertEqual(set(data["snapshot"]), {remote, self.main, self.feature})
        self.assertEqual(data["commits"][shas.index(remote)]["parents"], [self.main])
        self.assertLess(shas.index(remote), shas.index(self.main))
        self.assertEqual(self.git("symbolic-ref", "HEAD"), "refs/heads/feature/搜索")
        self.assertEqual(before, (self.git("status", "--porcelain=v1"), self.git("show-ref"), (self.path / ".git/index").read_bytes()))

    def test_all_branches_include_unmerged_and_disconnected_remote_history(self):
        other = self.git("commit-tree", self.git("rev-parse", "main^{tree}"), "-m", "Independent remote root")
        self.git("update-ref", "refs/remotes/other/topic", other)
        data = self.repo.commits(all_branches=True)
        self.assertEqual({c["sha"] for c in data["commits"]}, {self.main, self.feature, self.initial, other})
        selected = self.repo.commits(refs=["refs/heads/main"])
        self.assertEqual([c["sha"] for c in selected["commits"]], [self.main, self.initial])
        self.assertNotIn(other, [c["sha"] for c in selected["commits"]])

    def test_multi_branch_pagination_stays_frozen_after_refs_move_and_are_deleted(self):
        original = self.repo.commits(all_branches=True)
        first = self.repo.commits(all_branches=True, limit=1)
        self.file("new.txt", "new local tip\n")
        new = self.commit("New tip after first page")
        self.git("branch", "-D", "feature/搜索")
        self.git("update-ref", "refs/remotes/origin/main", new)
        remaining = self.repo.commits(snapshot=first["snapshot"], offset=first["next_offset"])
        self.assertEqual(first["commits"] + remaining["commits"], original["commits"])
        self.assertEqual(first["snapshot"], remaining["snapshot"])
        self.assertNotIn(new, [c["sha"] for c in remaining["commits"]])
        self.assertIn(new, [c["sha"] for c in self.repo.commits(all_branches=True)["commits"]])

    def test_multi_branch_merges_keep_real_parents_and_deduplicate_shared_commits(self):
        self.git("merge", "--no-ff", "feature/搜索", "-m", "Merge feature")
        merged = self.git("rev-parse", "HEAD")
        data = self.repo.commits(refs=["refs/heads/main", "refs/heads/feature/搜索", "refs/heads/main"])
        shas = [c["sha"] for c in data["commits"]]
        self.assertEqual(len(shas), 4)
        self.assertEqual(data["commits"][0]["parents"], [self.main, self.feature])
        self.assertEqual(shas[0], merged)
        for commit in data["commits"]:
            for parent in commit["parents"]:
                if parent in shas:
                    self.assertLess(shas.index(commit["sha"]), shas.index(parent))
        first_parent = self.repo.commits(refs=["refs/heads/main", "refs/heads/feature/搜索"], first_parent=True)
        self.assertIn(self.feature, [c["sha"] for c in first_parent["commits"]])
        search = self.repo.commits(all_branches=True, query="[query].", author="test@example.test")
        self.assertEqual([c["sha"] for c in search["commits"]], [self.main])

    def test_all_branches_include_detached_head_and_handle_empty_repository(self):
        detached = self.git("commit-tree", self.git("rev-parse", "main^{tree}"), "-p", self.initial, "-m", "Detached commit")
        self.git("checkout", "--detach", detached)
        self.assertIn(detached, [c["sha"] for c in self.repo.commits(all_branches=True)["commits"]])
        self.assertEqual(self.repo.commits(refs=[detached])["commits"][0]["sha"], detached)
        empty = self.root / "empty"
        subprocess.check_output(["git", "init", "-b", "main", str(empty)], env=self.env, stderr=subprocess.PIPE)
        empty_log = Repository(empty).commits(all_branches=True)
        self.assertIsNone(empty_log["log_context"]["repository"]["head"])
        self.assertEqual({key:value for key,value in empty_log.items() if key != "log_context"},
                         {"commits": [], "has_more": False, "next_offset": 0, "snapshot": []})

    def test_new_log_query_returns_updated_head_branches_and_tags_with_its_roots(self):
        self.git("tag", "moving", self.main)
        previous = self.repo.branches()
        self.file("new.txt", "external change\n")
        advanced = self.commit("New commit while panel is open")
        self.git("update-ref", "refs/remotes/origin/main", advanced)
        self.git("tag", "-f", "moving", advanced)
        data = self.repo.commits(all_branches=True)
        context = data["log_context"]
        self.assertEqual(previous["repository"]["head"], self.main)
        self.assertEqual(context["repository"]["head"], advanced)
        refs = {item["ref"]:item["sha"] for item in context["branches"] + context["tags"]}
        for ref in ("refs/heads/main", "refs/remotes/origin/main", "refs/tags/moving"):
            self.assertEqual(refs[ref], advanced)
        self.assertEqual(set(data["snapshot"]), {item["sha"] for item in context["branches"]})
        self.assertIn(advanced, [item["sha"] for item in data["commits"]])

    def test_log_pages_preserve_first_context_after_head_refs_and_tags_change(self):
        self.git("tag", "moving", self.main)
        first = self.repo.commits(all_branches=True, limit=1)
        context = json.loads(json.dumps(first["log_context"]))
        self.file("after.txt", "after first page\n")
        advanced = self.commit("After first page")
        self.git("branch", "-D", "feature/搜索")
        self.git("tag", "-f", "moving", advanced)
        rest = self.repo.commits(snapshot=first["snapshot"], offset=first["next_offset"])
        self.assertNotIn("log_context", rest)
        self.assertEqual(first["log_context"], context)
        self.assertNotIn(advanced, [item["sha"] for item in rest["commits"]])
        self.assertEqual(self.repo.commits(all_branches=True)["log_context"]["repository"]["head"], advanced)

    def test_log_head_matches_root_when_current_branch_advances_during_catalog_read(self):
        read_info = self.repo.info
        advanced = []
        def read_then_commit():
            info = read_info()
            self.file("during-read.txt", "commit while reading references\n")
            advanced.append(self.commit("Advance during catalog read"))
            return info
        with mock_patch.object(self.repo, "info", side_effect=read_then_commit):
            data = self.repo.commits(all_branches=True)
        self.assertEqual(data["log_context"]["repository"]["head"], advanced[0])
        current = next(item for item in data["log_context"]["branches"] if item["current"])
        self.assertEqual(current["sha"], advanced[0])
        self.assertIn(advanced[0], data["snapshot"])

    def test_multi_branch_range_rejects_invalid_refs_and_snapshot_injection(self):
        cases = [dict(refs=[]), dict(refs="refs/heads/main"), dict(refs=[3]), dict(refs=["--all"]),
                 dict(refs=["HEAD~1"]), dict(refs=["refs/heads/missing"]), dict(refs=["HEAD"] * 4097),
                 dict(refs=["HEAD"], all_branches=True), dict(all_branches="true"),
                 dict(snapshot="HEAD"), dict(snapshot=["--all"]), dict(snapshot=[self.initial + "~1"]),
                 dict(snapshot=[self.initial] * 4097), dict(snapshot=[False])]
        for case in cases:
            with self.subTest(case=repr(case)[:100]), self.assertRaises(GitError):
                self.repo.commits(**case)

    def test_multi_branch_date_order_surfaces_other_recent_tips_before_long_old_history(self):
        original_env = self.env.copy()
        tree = self.git("rev-parse", "main^{tree}")
        parent = self.initial
        try:
            for day in range(1, 9):
                self.env["GIT_AUTHOR_DATE"] = self.env["GIT_COMMITTER_DATE"] = f"2026-01-{day:02d}T12:00:00Z"
                parent = self.git("commit-tree", tree, "-p", parent, "-m", f"Long history {day}")
            self.env["GIT_AUTHOR_DATE"] = self.env["GIT_COMMITTER_DATE"] = "2026-01-10T12:00:00Z"
            feature = self.git("commit-tree", tree, "-p", parent, "-m", "Feature latest")
            self.env["GIT_AUTHOR_DATE"] = self.env["GIT_COMMITTER_DATE"] = "2026-01-09T12:00:00Z"
            master = self.git("commit-tree", tree, "-p", self.initial, "-m", "Master latest")
        finally:
            self.env = original_env
        self.git("update-ref", "refs/heads/long-feature", feature)
        self.git("update-ref", "refs/heads/master", master)
        page = self.repo.commits(refs=["refs/heads/long-feature", "refs/heads/master"], limit=2)
        self.assertEqual([c["sha"] for c in page["commits"]], [feature, master])
        self.assertTrue(page["has_more"])

    def test_multi_branch_http_and_cli_transport(self):
        server = ExplorerServer(self.repo)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        query = urlencode({"refs": json.dumps(["refs/heads/main", "refs/heads/feature/搜索"]), "limit": "1"})
        first = json.load(urllib.request.urlopen(server.url + "api/commits?" + query))
        query = urlencode({"snapshot": json.dumps(first["snapshot"]), "offset": first["next_offset"]})
        rest = json.load(urllib.request.urlopen(server.url + "api/commits?" + query))
        self.assertEqual({c["sha"] for c in first["commits"] + rest["commits"]}, {self.main, self.feature, self.initial})
        script = Path(__file__).resolve().parents[1] / "scripts/git_explorer.py"
        result = json.loads(subprocess.check_output([sys.executable, str(script), "log", "--repo", str(self.path), "--all-branches"]))
        self.assertEqual({c["sha"] for c in result["commits"]}, {self.main, self.feature, self.initial})
        self.assertEqual(urllib.request.urlopen(server.url + "history-scope.js").status, 200)

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

    def test_tags_are_separate_refs_and_annotated_tags_resolve_to_commit_history(self):
        self.git("tag", "v1.0")
        self.git("tag", "-a", "release/v1.0", "-m", "Release")
        data = self.repo.branches()
        tags = {item["ref"]: item for item in data["tags"]}
        self.assertEqual(tags["refs/tags/v1.0"]["sha"], self.main)
        self.assertEqual(tags["refs/tags/release/v1.0"]["sha"], self.main)
        self.assertEqual(self.repo.commits("refs/tags/release/v1.0")["commits"][0]["sha"], self.main)
        self.assertFalse(any(item.get("tag") for item in data["branches"]))

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
