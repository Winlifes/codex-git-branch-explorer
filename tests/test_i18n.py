"""UI copy remains localizable without changing Git content or operation plans."""
import ast
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from i18n import ui, message_paths, message_spec, translate, error_message
from git_explorer import GitError
from git_operations import safe_output


class LocalizationTests(unittest.TestCase):
    def test_repository_strings_are_never_translation_keys(self):
        data = {"title": ui("切换到 ") + "刷新", "files": ["取消"], "subject": "关闭", "author": "分支"}
        messages = message_paths(data)
        self.assertEqual([m["path"] for m in messages], [["title"]])
        self.assertEqual(translate(data["title"], "en-US"), "Switch to 刷新")
        self.assertEqual(json.loads(json.dumps(data))["subject"], "关闭")
        self.assertEqual(message_spec(data["title"])["values"]["parts"][1], "刷新")

    def test_errors_preserve_messages_and_sanitize_diagnostic_values(self):
        message = ui("本地备份未完成，未执行撤回。\n") + "https://secret:token@example.test/repo?key=private"
        safe = safe_output(error_message(GitError(message)))
        text = translate(safe, "en-US")
        self.assertTrue(text.startswith("Local backup did not complete."))
        self.assertNotIn("secret", text)
        self.assertNotIn("private", json.dumps(message_spec(safe)))

    def test_catalog_covers_code_and_template_copy(self):
        catalog = json.loads((ROOT / "assets/locales/en.json").read_text())
        keys = set()
        for name in ("git_explorer", "git_operations", "worktree_discard", "mcp_server"):
            for node in ast.walk(ast.parse((ROOT / f"scripts/{name}.py").read_text())):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ui":
                    if isinstance(node.args[0], ast.Constant):
                        keys.add(node.args[0].value)
        for name in ("app", "operations", "controls", "mcp-bridge"):
            source = (ROOT / f"assets/{name}.js").read_text()
            keys.update(json.loads(m) for m in re.findall(r'GitI18n\.t\(("(?:[^"\\]|\\.)*")', source))
        class Template(HTMLParser):
            def handle_data(self, data):
                if re.search(r"[\u4e00-\u9fff]", data):
                    keys.add(data.strip())
            def handle_starttag(self, tag, attributes):
                for name, value in attributes:
                    if name in {"title", "aria-label", "placeholder"} and value and re.search(r"[\u4e00-\u9fff]", value):
                        keys.add(value)
        Template().feed((ROOT / "assets/index.html").read_text())
        self.assertFalse(keys - catalog.keys(), sorted(keys - catalog.keys()))
        self.assertTrue(all(value and not re.search(r"[\u4e00-\u9fff]", value) for value in catalog.values()))
