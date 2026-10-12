"use strict";
// Folder paths describe refs for display only; leaves retain the original Git data.
const GitBranchTree = (() => {
  const folderId = (group, path = "") => JSON.stringify([group, path]);
  const groupOf = branch => branch.tag ? "tags" : branch.remote ? "remote" : "local";
  function ancestors(branch) {
    const group = groupOf(branch), parts = branch.name.split("/");
    return [folderId(group), ...parts.slice(0, -1).map((_, i) => folderId(group, parts.slice(0, i + 1).join("/")))];
  }
  function build(branches, query = "", kind = "all") {
    const roots = new Map(), q = query.trim().toLocaleLowerCase();
    function folder(group, path, name, root = false) {
      return {type: "folder", id: folderId(group, path), group, path, name, root,
        count: 0, current: false, folders: new Map(), leaves: []};
    }
    for (const branch of branches) {
      const group = groupOf(branch);
      if ((kind !== "all" && kind !== group) || !branch.name.toLocaleLowerCase().includes(q)) continue;
      if (!roots.has(group)) roots.set(group, folder(group, "", group, true));
      let parent = roots.get(group);
      parent.count++; parent.current ||= Boolean(branch.current);
      const parts = branch.name.split("/");
      for (let i = 0; i < parts.length - 1; i++) {
        const name = parts[i], path = parts.slice(0, i + 1).join("/");
        if (!parent.folders.has(name)) parent.folders.set(name, folder(group, path, name));
        parent = parent.folders.get(name);
        parent.count++; parent.current ||= Boolean(branch.current);
      }
      parent.leaves.push({type: "branch", id: "ref:" + branch.ref, name: parts[parts.length - 1], branch});
    }
    function finish(node) {
      const folders = [...node.folders.values()].sort((a, b) => a.name.localeCompare(b.name, "en", {numeric: true}));
      // Keep Git's latest-commit order within each folder.
      node.children = [...folders.map(finish), ...node.leaves];
      delete node.folders; delete node.leaves;
      return node;
    }
    return ["local", "remote", "tags"].filter(group => roots.has(group)).map(group => finish(roots.get(group)));
  }
  class Expansion {
    constructor(storage) {
      this.storage = storage; this.repositories = new Map(); this.repo = "";
      this.query = ""; this.search = new Map();
    }
    use(repo, selected) {
      if (repo !== this.repo) { this.repo = repo; this.query = ""; this.search.clear(); }
      if (this.repositories.has(repo)) return;
      let saved;
      try { saved = JSON.parse(this.storage?.getItem("git-explorer-folders:" + repo) || "null"); } catch {}
      const entries = Array.isArray(saved) ? saved.slice(0, 2000).filter(entry => Array.isArray(entry) &&
        typeof entry[0] === "string" && entry[0].length < 8192 && typeof entry[1] === "boolean") : null;
      this.repositories.set(repo, new Map(entries || (selected ? ancestors(selected).map(id => [id, true]) : [])));
    }
    filter(query) {
      if (query !== this.query) { this.query = query; this.search.clear(); }
    }
    expanded(node) {
      return this.query ? this.search.get(node.id) ?? true :
        this.repositories.get(this.repo)?.get(node.id) ?? (node.root && node.group === "local");
    }
    save() {
      try { this.storage?.setItem("git-explorer-folders:" + this.repo, JSON.stringify([...this.repositories.get(this.repo)].slice(-2000))); } catch {}
    }
    set(node, open) {
      (this.query ? this.search : this.repositories.get(this.repo)).set(node.id, open);
      if (!this.query) this.save();
    }
    reveal(branch) {
      const target = this.query ? this.search : this.repositories.get(this.repo);
      for (const id of ancestors(branch)) target.set(id, true);
      if (!this.query) this.save();
    }
  }
  return {build, ancestors, folderId, Expansion};
})();
if (typeof module !== "undefined" && module.exports) module.exports = GitBranchTree;
