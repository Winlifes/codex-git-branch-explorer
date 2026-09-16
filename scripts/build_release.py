#!/usr/bin/env python3
"""Build a deterministic, portable release from the public plugin tree."""
from pathlib import Path
import hashlib
import json
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP_LEVEL = {".gitignore", "README.md", "README.zh-CN.md", "PRIVACY.md", "LICENSE", "CHANGELOG.md"}
DIRECTORIES = {".codex-plugin", "assets", "docs", "scripts", "skills", "tests"}


def build():
    manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text())
    name, version = manifest["name"], manifest["version"]
    if name != "git-branch-explorer" or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Release manifest must use the plugin name and a stable semantic version")
    files = {}
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if relative.parts[0] not in TOP_LEVEL | DIRECTORIES:
            continue
        if any(part in {"__pycache__", ".git", ".DS_Store"} for part in relative.parts):
            continue
        if path.suffix == ".pyc" or path.is_dir():
            continue
        if path.is_symlink():
            raise ValueError("Release cannot contain symlinks: " + str(relative))
        files[relative.as_posix()] = path.read_bytes()
    # Always regenerate launch configuration; never export local installation paths.
    config = {"mcpServers": {"git-branches": {"command": "python3",
              "args": ["${PLUGIN_ROOT}/scripts/mcp_server.py"]}}}
    files[".mcp.json"] = (json.dumps(config, indent=2) + "\n").encode()
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    archive = destination / (name + "-" + version + ".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for relative, data in sorted(files.items()):
            info = zipfile.ZipInfo(name + "/" + relative, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(info, data)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = destination / "SHA256SUMS"
    checksum.write_text(digest + "  " + archive.name + "\n", encoding="utf-8")
    print(json.dumps({"archive": str(archive), "files": len(files),
                      "sha256": digest, "checksums": str(checksum)}, indent=2))


if __name__ == "__main__":
    build()
