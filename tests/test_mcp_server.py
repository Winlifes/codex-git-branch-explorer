"""Exercise the packaged MCP transport and read real Git data through it."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from mcp_server import Server, ROOT, URI, MIME


class McpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls.temp.name).resolve() / "仓库 with spaces"
        cls.repo.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="Test",
                   GIT_AUTHOR_EMAIL="test@example.test", GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.test")
        def git(*args):
            return subprocess.check_output(["git", "-C", str(cls.repo), "-c", "commit.gpgsign=false",
                "-c", "core.hooksPath=" + str(Path(cls.temp.name) / "no-hooks"), *args], env=env, stderr=subprocess.PIPE)
        git("init", "-b", "main")
        (cls.repo / "你好.txt").write_text("hello\n")
        git("add", "."); git("commit", "-m", "First <script> is data")
        cls.sha = git("rev-parse", "HEAD").decode().strip()
        git("branch", "feature/中文")
        cls.server = Server(cls.repo)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def rpc(self, method, **params):
        response = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        self.assertNotIn("error", response)
        return response["result"]

    def test_native_entrypoint_and_icon_are_discoverable(self):
        init = self.rpc("initialize", protocolVersion="2025-11-25")
        self.assertTrue(all(i["src"].startswith("data:image/svg+xml;base64,") for i in init["serverInfo"]["icons"]))
        tools = self.rpc("tools/list")["tools"]
        self.assertEqual(tools[0]["title"], "Git 分支")
        self.assertEqual(tools[0]["_meta"]["openai/ui"]["entrypoints"], [{"type": "thread"}])
        self.assertEqual(tools[0]["_meta"]["ui"]["resourceUri"], URI)
        self.assertEqual(tools[1]["_meta"]["ui"]["visibility"], ["app"])
        write = next(t for t in tools if t["name"] == "git_apply")
        self.assertFalse(write["annotations"]["readOnlyHint"])
        self.assertTrue(write["annotations"]["destructiveHint"])
        self.assertTrue(write["annotations"]["openWorldHint"])
        self.assertEqual(write["_meta"]["ui"]["visibility"], ["app"])

    def test_self_contained_resource(self):
        resource = self.rpc("resources/read", uri=URI)["contents"][0]
        self.assertEqual(resource["mimeType"], MIME)
        self.assertNotIn('src="./app.js"', resource["text"])
        self.assertNotIn('href="./style.css"', resource["text"])
        self.assertIn('ui/initialize', resource["text"])
        self.assertIn('data-host-theme', resource["text"])

    def test_initial_result_then_history_and_diff(self):
        first = self.rpc("tools/call", name="git_panel", arguments={})["_meta"]["gitExplorer"]
        self.assertEqual(first["repository"]["path"], str(self.repo))
        self.assertEqual(len(first["branches"]), 2)
        def query(**args):
            result = self.rpc("tools/call", name="git_query", arguments=args)
            self.assertFalse(result.get("isError"), result)
            return result["_meta"]["gitExplorer"]
        history = query(action="commits", ref="refs/heads/feature/中文")
        self.assertEqual(history["commits"][0]["sha"], self.sha)
        detail = query(action="commit", sha=self.sha)
        patch = query(action="patch", sha=self.sha, path=detail["files"][0]["path"])
        self.assertIn("+hello", patch["patch"])

    def test_non_repo_has_actionable_picker(self):
        result = Server(self.temp.name).call("git_panel", {})["_meta"]["gitExplorer"]
        self.assertTrue(result["needs_repository"])

    def test_invalid_requests_do_not_run_git_commands(self):
        for arguments in ({"action": "checkout"}, {"action": "commits", "first_parent": "false"},
                          {"action": "branches", "repo": 4}, {"action": "branches", "command": "rm"},
                          {"action": "patch", "sha": self.sha, "path": "../secret"}):
            self.assertTrue(self.rpc("tools/call", name="git_query", arguments=arguments)["isError"])

    def test_stdio_lifecycle_and_parse_error_recovery(self):
        requests = ["not json", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}),
                    json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                    json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "git_panel", "arguments": {}}})]
        process = subprocess.run([sys.executable, str(ROOT / "scripts/mcp_server.py")], cwd=self.repo,
                                 input="\n".join(requests) + "\n", text=True, capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        responses = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual(len(responses), 3)
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertEqual(responses[1]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(responses[2]["result"]["_meta"]["gitExplorer"]["repository"]["path"], str(self.repo))


if __name__ == "__main__":
    unittest.main()
