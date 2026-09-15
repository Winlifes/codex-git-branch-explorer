#!/usr/bin/env python3
"""Install this package into the current user's personal Codex marketplace."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

NAME = "git-branch-explorer"
SOURCE = Path(__file__).resolve().parents[1]


def configure_mcp(destination, codex_home=None):
    """Legacy Codex plugin manifests do not expand PLUGIN_ROOT in stdio args."""
    destination = Path(destination).resolve()
    path = destination / ".mcp.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    server = data["mcpServers"]["git-branches"]
    server["args"] = [str(destination / "scripts/mcp_server.py")]
    # Codex filters inherited MCP environment variables. Pass its metadata root
    # explicitly so the server can resolve the caller's task, including custom homes.
    server.setdefault("env", {})["CODEX_HOME"] = str(Path(codex_home or os.environ.get("CODEX_HOME")
                                                           or Path.home() / ".codex").expanduser().resolve())
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def register(source, user_root):
    """Register a new plugin; preserve existing catalog entries and source files."""
    user_root = Path(user_root).resolve()
    source = Path(source).resolve()
    manifest = json.loads((source / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    if manifest.get("name") != NAME:
        raise ValueError("此安装器仅适用于 git-branch-explorer。")
    catalog = user_root / ".agents/plugins/marketplace.json"
    destination = user_root / "plugins" / NAME
    if catalog.exists():
        data = json.loads(catalog.read_text(encoding="utf-8"))
    else:
        data = {"name": "personal", "interface": {"displayName": "Personal"}, "plugins": []}
    if not isinstance(data, dict) or not re.fullmatch(r"[A-Za-z0-9_-]+", str(data.get("name", ""))):
        raise ValueError("现有个人 marketplace 名称不合法，请先修复。")
    if not isinstance(data.get("plugins"), list) or any(not isinstance(p, dict) for p in data["plugins"]):
        raise ValueError("现有 marketplace 的 plugins 字段不是有效列表。")
    existing = [p for p in data["plugins"] if p.get("name") == NAME]
    expected_source = {"source": "local", "path": "./plugins/" + NAME}
    if len(existing) > 1 or (existing and existing[0].get("source") != expected_source):
        raise ValueError("已存在同名插件，且来源不同；安装已停止。")
    if existing and existing[0].get("policy", {}).get("installation") == "NOT_AVAILABLE":
        raise ValueError("此 marketplace 中该插件被标记为不可安装。")
    if destination.exists() and destination.resolve() != source:
        raise ValueError("插件目录已存在，未覆盖。更新现有插件请使用 Codex 的 plugin-creator 更新流程。")
    if destination.is_symlink():
        raise ValueError("插件目标目录是符号链接，安装已停止。")
    if destination.resolve() != source:
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Stage first so a failed copy never leaves a half-installed plugin.
        with tempfile.TemporaryDirectory(prefix=".git-explorer-install-", dir=destination.parent) as stage:
            staged = Path(stage) / NAME
            shutil.copytree(source, staged, ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".git", ".DS_Store", "dist", ".venv", ".env", ".env.*"))
            staged.rename(destination)
    codex_home = (os.environ.get("CODEX_HOME") or user_root / ".codex") if user_root == Path.home().resolve() else user_root / ".codex"
    configure_mcp(destination, codex_home)
    if not existing:
        data["plugins"].append({"name": NAME, "source": expected_source,
                                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                                "category": "Productivity"})
        catalog.parent.mkdir(parents=True, exist_ok=True)
        # Keep a recovery copy when extending an existing personal catalog.
        if catalog.exists():
            backup = catalog.with_name("marketplace.before-git-branch-explorer.json")
            if not backup.exists():
                shutil.copy2(catalog, backup)
        handle, temporary = tempfile.mkstemp(prefix=".git-explorer-", suffix=".json", dir=catalog.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as output:
                json.dump(data, output, ensure_ascii=False, indent=2)
                output.write("\n")
            os.replace(temporary, catalog)
        finally:
            if Path(temporary).exists():
                Path(temporary).unlink()
    return {"plugin": NAME, "marketplace": data["name"], "catalog": str(catalog), "source": str(destination)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register-only", action="store_true", help="Register the local package without running codex plugin add")
    args = parser.parse_args()
    try:
        result = register(SOURCE, Path.home())
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        command = shutil.which("codex")
        if not command and sys.platform == "darwin":
            for name in ("Codex.app", "ChatGPT.app"):
                candidate = Path("/Applications") / name / "Contents/Resources/codex"
                if candidate.is_file():
                    command = str(candidate)
                    break
        selector = NAME + "@" + result["marketplace"]
        if args.register_only or not command:
            print("已注册到个人插件市场。安装命令：codex plugin add " + selector)
        else:
            subprocess.run([command, "plugin", "add", selector], check=True)
            print("安装完成。现有任务和新任务均可在右侧面板的新标签页列表点击「Git 分支」。若入口未出现，请等运行中的任务结束后退出并重新打开 Codex，再回到原任务。")
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print("安装失败：" + str(error), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
