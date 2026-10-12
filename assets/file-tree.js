"use strict";
const GitFileTree = (() => {
  function build(files) {
    const root = {children: new Map(), files: [], path: ""};
    for (const file of files) {
      const parts = file.path.split("/"); let parent = root;
      for (let index = 0; index < parts.length - 1; index++) {
        const name = parts[index], fullPath = parts.slice(0, index + 1).join("/");
        if (!parent.children.has(name)) parent.children.set(name, {name, path: fullPath, children: new Map(), files: []});
        parent = parent.children.get(name);
      }
      parent.files.push(file);
    }
    function finish(parent) {
      const folders = [...parent.children.values()].sort((a, b) => a.name.localeCompare(b.name, undefined, {numeric: true}));
      return [
        ...folders.map(folder => { const children = finish(folder); return {type: "folder", name: folder.name, path: folder.path, children,
          files: children.flatMap(child => child.type === "folder" ? child.files : [child.file])}; }),
        ...parent.files.slice().sort((a, b) => a.path.localeCompare(b.path, undefined, {numeric: true})).map(file =>
          ({type: "file", name: file.path.split("/").at(-1), path: file.path, file})),
      ];
    }
    return finish(root);
  }
  function selection(files, selected) {
    const available = files.filter(file => file.operable !== false && !file.conflict);
    const count = available.filter(file => selected.has(file.path)).length;
    return {checked: available.length > 0 && count === available.length, indeterminate: count > 0 && count < available.length,
      disabled: !available.length, paths: available.map(file => file.path)};
  }
  function mount(target, files, {selected, onToggle, onOpen, actions, active = "", key = "files", storage} = {}) {
    const tree = build(files), closed = new Set();
    try { JSON.parse(storage?.getItem(`git-file-tree:${key}`) || "[]").forEach(value => closed.add(value)); } catch {}
    const remember = () => { try { storage?.setItem(`git-file-tree:${key}`, JSON.stringify([...closed])); } catch {} };
    function render() {
      const focusedPath = target.contains(document.activeElement) ? document.activeElement.closest("[data-path]")?.dataset.path : null;
      target.replaceChildren();
      function append(nodes, container, depth = 0) {
        for (const node of nodes) {
          const folder = node.type === "folder", wrapper = document.createElement("div");
          wrapper.className = folder ? "file-folder" : "file-entry";
          const row = document.createElement("div"); row.className = "file-tree-row";
          row.classList.toggle("selectable", Boolean(selected && onToggle));
          row.style.setProperty("--file-depth", depth); row.dataset.path = node.path;
          if (active === node.path) row.classList.add("active");
          const open = folder && !closed.has(node.path);
          const disclosure = document.createElement("button");
          disclosure.type = "button"; disclosure.className = "file-disclosure";
          if (folder) {
            disclosure.append(GitUI.icon("chevron")); disclosure.classList.toggle("expanded", open);
            disclosure.setAttribute("aria-expanded", String(open));
            GitI18n.attr(disclosure, "aria-label", () => GitI18n.t("展开或收起 ") + node.path);
            disclosure.addEventListener("click", () => { open ? closed.add(node.path) : closed.delete(node.path); remember(); render(); });
          } else { disclosure.disabled = true; disclosure.setAttribute("aria-hidden", "true"); disclosure.tabIndex = -1; }
          row.append(disclosure);
          if (selected && onToggle) {
            const checkbox = document.createElement("input"); checkbox.type = "checkbox";
            const status = selection(folder ? node.files : [node.file], selected);
            Object.assign(checkbox, {checked: status.checked, indeterminate: status.indeterminate, disabled: status.disabled});
            GitI18n.attr(checkbox, "aria-label", () => GitI18n.t("选择 ") + node.path);
            checkbox.addEventListener("change", () => { onToggle(status.paths, checkbox.checked); render(); }); row.append(checkbox);
          }
          const name = document.createElement("button"); name.type = "button"; name.className = "file-tree-name";
          name.append(GitUI.icon(folder ? "folder" : "file"));
          const label = document.createElement("span"); label.textContent = node.name; name.append(label); name.title = node.path;
          if (folder) {
            const count = document.createElement("span"); count.className = "file-tree-count";
            GitI18n.text(count, () => GitI18n.t("{count} 个文件", {count: node.files.length})); name.append(count);
            name.setAttribute("aria-expanded", String(open));
            name.addEventListener("click", () => disclosure.click());
          } else {
            name.disabled = node.file.operable === false;
            const code = node.file.status || (node.file.conflict ? "!" : node.file.untracked ? "?" : node.file.worktree_status?.trim() || node.file.index_status);
            row.dataset.status = code;
            const badge = document.createElement("span"); badge.className = "file-status";
            badge.textContent = code; row.append(badge);
            name.addEventListener("click", () => {
              active = node.path;
              for (const item of target.querySelectorAll(".file-tree-row")) item.classList.toggle("active", item.dataset.path === active);
              onOpen?.(node.file);
            });
          }
          row.append(name); if (!folder && actions) row.append(actions(node.file));
          wrapper.append(row); container.append(wrapper);
          if (folder && open) { const children = document.createElement("div"); wrapper.append(children); append(node.children, children, depth + 1); }
        }
      }
      append(tree, target);
      if (focusedPath) [...target.querySelectorAll("[data-path]")].find(row => row.dataset.path === focusedPath)?.querySelector("input,button:not(:disabled)")?.focus({preventScroll: true});
    }
    render();
    return {refresh: render};
  }
  return {build, selection, mount};
})();
if (typeof module !== "undefined") module.exports = GitFileTree;
