import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from install import NAME, SOURCE, register


class InstallTests(unittest.TestCase):
    def test_register_new_plugin_into_isolated_personal_root(self):
        with tempfile.TemporaryDirectory() as temp:
            result = register(SOURCE, temp)
            destination = Path(result["source"])
            self.assertTrue((destination / "scripts/git_explorer.py").is_file())
            mcp = json.loads((destination / ".mcp.json").read_text())
            self.assertEqual(mcp["mcpServers"]["git-branches"]["args"], [str(destination / "scripts/mcp_server.py")])
            self.assertEqual(mcp["mcpServers"]["git-branches"]["env"]["CODEX_HOME"], str(Path(temp).resolve() / ".codex"))
            data = json.loads(Path(result["catalog"]).read_text())
            self.assertEqual(data["name"], "personal")
            self.assertEqual(data["plugins"][0]["source"]["path"], "./plugins/" + NAME)
            self.assertEqual(data["plugins"][0]["policy"]["installation"], "AVAILABLE")

    def test_preserve_existing_catalog_and_refuse_source_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            catalog = root / ".agents/plugins/marketplace.json"
            catalog.parent.mkdir(parents=True)
            other = {"name": "another", "source": {"source": "local", "path": "./plugins/another"}}
            catalog.write_text(json.dumps({"name": "my-personal", "interface": {"displayName": "My plugins"}, "plugins": [other]}))
            result = register(SOURCE, root)
            data = json.loads(catalog.read_text())
            self.assertEqual(result["marketplace"], "my-personal")
            self.assertEqual(data["plugins"][0], other)
            self.assertEqual(data["interface"]["displayName"], "My plugins")
            before = catalog.read_bytes()
            with self.assertRaises(ValueError):
                register(SOURCE, root)
            self.assertEqual(catalog.read_bytes(), before)
            # Re-running from the installed source is idempotent.
            register(Path(result["source"]), root)
            self.assertEqual(catalog.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
