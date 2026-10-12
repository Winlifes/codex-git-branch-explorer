"""Real disposable Git projects, with a fake GitHub API and local push target."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from git_explorer import GitError
from git_operations import run as real_run
from github_setup import GithubClient, GithubSetup, MAX_FILE, project_path
from mcp_server import Server


class FakeGithub:
    executable = "/test path/gh"

    def __init__(self):
        self.login, self.identifier = "TestOwner", 123
        self.created, self.exists = [], False
        self.failure = None

    def account(self):
        return {"login": self.login, "id": self.identifier, "name": "Test Owner"}

    def request(self, endpoint, payload=None, missing_ok=False):
        if payload is None:
            return {} if self.exists else None
        self.created.append(payload)
        if self.failure:
            raise self.failure
        self.exists = True
        return {"full_name": self.login + "/" + payload["name"], "private": payload["private"],
                "html_url": "https://github.com/" + self.login + "/" + payload["name"]}


class GithubSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "项目 with spaces"; self.project.mkdir()
        (self.project / "hello.txt").write_text("hello\n")
        self.remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "--quiet", str(self.remote)], check=True)
        self.client = FakeGithub(); self.setup = GithubSetup(self.client)
        self.commands, self.push_failure = [], False
        self.author = "Test User"
        self.hooks = str(self.root / "no-hooks")
        self.addCleanup(patch.stopall)
        patch("github_setup.run", side_effect=self.git_run).start()

    def git_run(self, repo, *args, **kwargs):
        self.commands.append(args)
        options = ["-c", "user.name=" + self.author, "-c", "user.email=test@example.test",
                   "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + self.hooks]
        if "push" in args:
            if self.push_failure:
                raise GitError("Test push failed")
            options += ["-c", "url." + str(self.remote) + ".insteadOf=https://github.com/TestOwner/test-project.git"]
        return real_run(repo, *options, *args, **kwargs)

    def parameters(self, **values):
        return {"name": "test-project", "description": "Example", "visibility": "private", "branch": "main",
                "template": "common", "upload": True, "message": "Initial commit", "account": self.client.login,
                "account_confirmed": True, **values}

    def prepare(self, **values):
        return self.setup.prepare(str(self.project), self.parameters(**values), "task-a")

    def apply(self, preview, owner="task-a"):
        job = self.setup.apply(str(self.project), preview["token"], owner)
        deadline = time.monotonic() + 10
        while job["state"] == "running" and time.monotonic() < deadline:
            time.sleep(0.01)
            job = self.setup.progress(str(self.project), job["job"], owner)
        self.assertNotEqual(job["state"], "running", job)
        return job

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.project), *args], stderr=subprocess.PIPE).decode().strip()

    def test_inspect_uses_confirmed_account_and_detects_unity(self):
        (self.project / "Assets").mkdir(); (self.project / "ProjectSettings").mkdir()
        data = self.setup.inspect(str(self.project))
        self.assertTrue(data["ready"])
        self.assertEqual(data["account"]["login"], "TestOwner")
        self.assertEqual(data["suggested_template"], "unity")
        self.assertFalse((self.project / ".git").exists())

    def test_preview_is_read_only_and_preserves_existing_ignores(self):
        (self.project / ".gitignore").write_text("private-cache/\n")
        (self.project / "private-cache").mkdir(); (self.project / "private-cache/item").write_text("ignored")
        (self.project / ".env").write_text("secret=test-not-a-real-token")
        preview = self.prepare()
        self.assertEqual(preview["files"], [".gitignore", "hello.txt"])
        self.assertFalse(self.client.created)
        self.assertFalse((self.project / ".git").exists())
        self.assertEqual((self.project / ".gitignore").read_text(), "private-cache/\n")

    def test_ignored_gitignore_is_rejected_before_local_mutation(self):
        (self.project / ".gitignore").write_text(".gitignore\n")
        with self.assertRaises(GitError):
            self.prepare()
        self.assertFalse((self.project / ".git").exists())
        self.assertFalse(self.client.created)

    def test_existing_empty_gitignore_is_included_in_first_commit(self):
        (self.project / ".gitignore").write_bytes(b"")
        preview = self.prepare(template="existing")
        self.assertEqual(preview["files"], [".gitignore", "hello.txt"])
        result = self.apply(preview)
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.git("show", "HEAD:.gitignore"), "")

    def test_initial_upload_creates_exact_files_remote_and_upstream(self):
        (self.project / ".gitignore").write_text("cache/\n")
        (self.project / ".env").write_text("secret")
        (self.project / "file [odd] 名字.txt").write_text("literal path")
        result = self.apply(self.prepare())
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["remote_state"], "created")
        self.assertEqual(self.client.created[0]["private"], True)
        self.assertEqual(self.git("-c", "core.quotePath=false", "ls-files").splitlines(), [".gitignore", "file [odd] 名字.txt", "hello.txt"])
        self.assertEqual(self.git("remote", "get-url", "origin"), "https://github.com/TestOwner/test-project.git")
        self.assertEqual(self.git("config", "branch.main.remote"), "origin")
        self.assertEqual(self.git("config", "branch.main.merge"), "refs/heads/main")
        helpers = self.git("config", "--local", "--get-all", "credential.https://github.com.helper")
        self.assertIn("auth git-credential", helpers)
        self.assertIn("/test path/gh", helpers)
        self.assertTrue((self.project / ".gitignore").read_text().startswith("cache/\n"))
        pushed = subprocess.check_output(["git", "--git-dir=" + str(self.remote), "rev-parse", "refs/heads/main"]).decode().strip()
        self.assertEqual(pushed, self.git("rev-parse", "HEAD"))
        self.assertNotIn("owner", result)

    def test_empty_repository_does_not_stage_commit_or_upload_files(self):
        result = self.apply(self.prepare(upload=False, template="existing"))
        self.assertTrue(result["ok"], result)
        self.assertTrue((self.project / ".git").is_dir())
        self.assertEqual(self.git("ls-files"), "")
        self.assertFalse(any("push" in command or "commit" in command or "add" == command[0] for command in self.commands))
        self.assertFalse((self.project / ".gitignore").exists())
        self.assertEqual(self.git("symbolic-ref", "HEAD"), "refs/heads/main")
        self.assertIn("auth git-credential", self.git("config", "--local", "--get-all", "credential.https://github.com.helper"))

    def test_public_visibility_is_explicit_in_preview_and_request(self):
        preview = self.prepare(visibility="public", upload=False)
        self.assertIn("公开，任何人均可查看上传内容", "\n".join(preview["details"]))
        result = self.apply(preview)
        self.assertTrue(result["ok"], result)
        self.assertFalse(self.client.created[0]["private"])

    def test_account_confirmation_is_required(self):
        for values in ({"account_confirmed": False}, {"account": "AnotherAccount"}):
            with self.subTest(values=values), self.assertRaises(GitError):
                self.prepare(**values)
        self.assertFalse(self.client.created)

    def test_changed_account_invalidates_preview_before_local_mutation(self):
        preview = self.prepare(); self.client.login = "OtherOwner"; self.client.identifier = 456
        result = self.apply(preview)
        self.assertFalse(result["ok"])
        self.assertIn("账号已变化", result["message"])
        self.assertFalse((self.project / ".git").exists())
        self.assertFalse(self.client.created)

    def test_changed_files_and_ignores_invalidate_preview(self):
        for name in ("hello.txt", ".gitignore"):
            with self.subTest(name=name):
                preview = self.prepare()
                (self.project / name).write_text("changed")
                result = self.apply(preview)
                self.assertFalse(result["ok"])
                self.assertFalse((self.project / ".git").exists())
        self.assertFalse(self.client.created)

    def test_changed_git_identity_invalidates_preview(self):
        preview = self.prepare(); self.author = "Someone Else"
        result = self.apply(preview)
        self.assertFalse(result["ok"])
        self.assertIn("提交身份已变化", result["message"])

    def test_git_url_rewrite_is_rejected_before_initialization(self):
        def rewrite(repo, *args, **kwargs):
            return self.git_run(repo, "-c", "url.ssh://git@github.com/.insteadOf=https://github.com/", *args, **kwargs)
        with patch("github_setup.run", side_effect=rewrite), self.assertRaises(GitError) as error:
            self.prepare()
        self.assertIn("URL 重写", str(error.exception))
        self.assertFalse((self.project / ".git").exists())
        self.assertFalse(self.client.created)

    def test_author_timestamp_can_change_while_reviewing_preview(self):
        counter = [100]
        def changing_timestamp(repo, *args, **kwargs):
            if args == ("var", "GIT_AUTHOR_IDENT"):
                counter[0] += 100
                return f"Test User <test@example.test> {counter[0]} +0000\n".encode()
            return self.git_run(repo, *args, **kwargs)
        with patch("github_setup.run", side_effect=changing_timestamp):
            result = self.apply(self.prepare())
        self.assertTrue(result["ok"], result)

    def test_token_is_bound_to_task_path_expiration_and_single_use(self):
        preview = self.prepare(upload=False)
        with self.assertRaises(GitError):
            self.setup.apply(str(self.project), preview["token"], "task-b")
        with self.assertRaises(GitError):
            self.setup.apply(str(self.root), preview["token"], "task-a")
        self.setup.plans[preview["token"]]["expires"] = 0
        with self.assertRaises(GitError):
            self.setup.apply(str(self.project), preview["token"], "task-a")
        preview = self.prepare(upload=False)
        result = self.apply(preview)
        with self.assertRaises(GitError):
            self.setup.apply(str(self.project), preview["token"], "task-a")
        with self.assertRaises(GitError):
            self.setup.progress(str(self.project), result["job"], "task-b")

    def test_existing_name_is_not_overwritten_or_connected(self):
        self.client.exists = True
        with self.assertRaises(GitError):
            self.prepare()
        self.assertFalse((self.project / ".git").exists())

    def test_name_race_is_detected_before_initialization(self):
        preview = self.prepare(); self.client.exists = True
        result = self.apply(preview)
        self.assertFalse(result["ok"])
        self.assertFalse((self.project / ".git").exists())
        self.assertFalse(self.client.created)

    def test_existing_git_directory_and_repository_parent_are_rejected(self):
        subprocess.run(["git", "init", "--quiet", str(self.project)], check=True)
        child = self.project / "child"; child.mkdir()
        for path in (self.project, child):
            with self.subTest(path=path), self.assertRaises(GitError):
                project_path(str(path))

    def test_invalid_options_are_rejected_without_writes(self):
        for options in ({"name": "../escape"}, {"name": "-option"}, {"name": "thing.git"}, {"visibility": "internal"},
                        {"template": "unknown"}, {"branch": "-bad"}, {"branch": "bad branch"}, {"message": ""}):
            with self.subTest(options=options), self.assertRaises(GitError):
                self.prepare(**options)
        self.assertFalse(self.client.created)
        self.assertFalse((self.project / ".git").exists())

    def test_credentials_links_and_nested_repos_never_enter_initial_commit(self):
        (self.project / ".env").write_text("secret")
        (self.project / "private.pem").write_text("secret")
        (self.project / "link.txt").symlink_to(self.root / "outside.txt")
        nested = self.project / "nested"; nested.mkdir()
        subprocess.run(["git", "init", "--quiet", str(nested)], check=True)
        (nested / "private.txt").write_text("private")
        preview = self.prepare(template="existing")
        self.assertEqual(preview["files"], ["hello.txt"])
        self.assertEqual({file["path"] for file in preview["excluded"]}, {".env", "private.pem", "link.txt", "nested"})
        result = self.apply(preview)
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.git("ls-files"), "hello.txt")

    def test_github_size_limit_blocks_before_init_or_remote_creation(self):
        with (self.project / "huge.bin").open("wb") as output:
            output.truncate(MAX_FILE)
        with self.assertRaises(GitError) as error:
            self.prepare()
        self.assertIn("100 MiB", str(error.exception))
        self.assertFalse((self.project / ".git").exists())

    def test_failed_hook_preserves_local_state_without_creating_remote(self):
        hooks = self.root / "hooks"; hooks.mkdir(); self.hooks = str(hooks)
        hook = hooks / "pre-commit"; hook.write_text("#!/bin/sh\nexit 1\n"); hook.chmod(0o755)
        result = self.apply(self.prepare())
        self.assertFalse(result["ok"])
        self.assertTrue(result["local_initialized"])
        self.assertEqual(result["remote_state"], "not_created")
        self.assertFalse(self.client.created)
        self.assertEqual(self.git("ls-files").splitlines(), [".gitignore", "hello.txt"])

    def test_post_timeout_is_not_retried_and_reports_unknown_remote(self):
        self.client.failure = GitError("Test API timeout")
        preview = self.prepare(); result = self.apply(preview)
        self.assertFalse(result["ok"])
        self.assertEqual(result["remote_state"], "unknown")
        self.assertEqual(len(self.client.created), 1)
        self.assertEqual(self.git("log", "-1", "--format=%s"), "Initial commit")

    def test_push_failure_keeps_remote_and_commit_for_recovery(self):
        self.push_failure = True
        result = self.apply(self.prepare())
        self.assertFalse(result["ok"])
        self.assertEqual(result["remote_state"], "created")
        self.assertEqual(result["url"], "https://github.com/TestOwner/test-project")
        self.assertEqual(len(self.client.created), 1)
        self.assertEqual(self.git("remote", "get-url", "origin"), result["url"] + ".git")

    def test_mcp_bootstrap_handles_non_repository_and_rejects_unconfirmed_calls(self):
        server = Server(self.project); server.github = self.setup
        metadata = {"threadId": "task-a"}
        data = server.call("github_project", {"project": str(self.project), "action": "inspect"}, metadata)["_meta"]["gitExplorer"]
        self.assertTrue(data["ready"])
        with self.assertRaises(GitError):
            server.call("github_prepare", {"project": str(self.project), **self.parameters(account_confirmed=False)}, metadata)
        with self.assertRaises(GitError):
            server.call("github_apply", {"project": str(self.project), "token": "fake-token"}, metadata)


class GithubTransportTests(unittest.TestCase):
    def test_missing_gh_returns_actionable_auth_state(self):
        with tempfile.TemporaryDirectory() as directory, patch("github_setup.find_gh", return_value=None):
            data = GithubSetup().inspect(directory)
        self.assertFalse(data["ready"])
        self.assertEqual(data["auth_state"], "gh_missing")

    def client(self, directory, output, error="", exit_code=0):
        path = Path(directory) / "fake gh"
        path.write_text("#!" + sys.executable + "\nimport sys\n" +
                        "sys.stdout.write(" + repr(output) + ")\n" +
                        "sys.stderr.write(" + repr(error) + ")\nsys.exit(" + str(exit_code) + ")\n")
        path.chmod(0o755)
        return GithubClient(str(path))

    def test_http_header_parsing_and_only_safe_account_fields_are_returned(self):
        output = "HTTP/2.0 200 OK\r\nContent-Type: application/json\r\n\r\n" + json.dumps({"login": "TestOwner", "id": 1, "name": "Tester", "email": "private@example.test"})
        with tempfile.TemporaryDirectory() as directory:
            account = self.client(directory, output).account()
        self.assertEqual(set(account), {"login", "id", "name"})

    def test_only_a_real_404_counts_as_available(self):
        with tempfile.TemporaryDirectory() as directory:
            client = self.client(directory, 'HTTP/2.0 404 Not Found\n\n{"message":"Not Found"}', exit_code=1)
            self.assertIsNone(client.request("repos/TestOwner/name", missing_ok=True))
            client = self.client(directory, 'HTTP/2.0 403 Forbidden\n\n{"message":"Forbidden"}', exit_code=1)
            with self.assertRaises(GitError):
                client.request("repos/TestOwner/name", missing_ok=True)

    def test_auth_errors_and_diagnostics_do_not_expose_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            client = self.client(directory, "", "To get started, run gh auth login", 1)
            with self.assertRaises(GitError) as error:
                client.account()
            self.assertEqual(error.exception.kind, "gh_auth")
            client = self.client(directory, "HTTP/2.0 403 Forbidden\n\n{}", "failure ghp_TestNotARealToken https://user:password@example.test", 1)
            with self.assertRaises(GitError) as error:
                client.account()
            self.assertNotIn("TestNotARealToken", str(error.exception))
            self.assertNotIn("password", str(error.exception))


if __name__ == "__main__":
    unittest.main()
