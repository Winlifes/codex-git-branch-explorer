"use strict";
// Log range is independent of the branch selected for browsing/operations.
const GitHistoryScope = (() => {
  function defaults(branches) {
    const current = branches.find(branch => branch.current);
    const wanted = new Set([current?.ref, current?.upstream,
      "refs/heads/master", "refs/remotes/origin/master", "refs/heads/main", "refs/remotes/origin/main"]);
    const selected = branches.filter(branch => branch.sha && wanted.has(branch.ref)).map(branch => branch.ref);
    return selected.length ? selected : branches.filter(branch => branch.sha).slice(0, 1).map(branch => branch.ref);
  }
  class Selection {
    constructor(storage) { this.storage = storage; this.repo = ""; this.mode = "all"; this.refs = []; this.available = new Set(); }
    use(repo, branches, tags = []) {
      this.available = new Set([...branches, ...tags].filter(branch => branch.sha).map(branch => branch.ref));
      if (repo !== this.repo) {
        this.repo = repo; this.mode = "all"; this.refs = [];
        try {
          const saved = JSON.parse(this.storage?.getItem("git-history-scope:" + repo) || "null");
          if (saved && ["all", "selected"].includes(saved.mode) && Array.isArray(saved.refs) && saved.refs.length <= 4096) {
            this.mode = saved.mode; this.refs = saved.refs.filter(ref => this.available.has(ref));
          }
        } catch {}
      }
      this.refs = this.refs.filter(ref => this.available.has(ref));
      if (!this.refs.length) this.refs = defaults(branches);
      return this;
    }
    configure(mode, refs = this.refs) {
      if (!["all", "selected"].includes(mode)) return false;
      const selected = [...new Set(refs)].filter(ref => this.available.has(ref));
      if (mode === "selected" && !selected.length) return false;
      this.mode = mode; this.refs = selected;
      try { this.storage?.setItem("git-history-scope:" + this.repo, JSON.stringify({mode, refs: selected})); } catch {}
      return true;
    }
    query(snapshot = null) {
      if (Array.isArray(snapshot)) return {snapshot: [...snapshot]};
      return this.mode === "all" ? {all_branches: true} : {refs: [...this.refs]};
    }
  }
  function references(branches, tags, sha) {
    return [...branches, ...tags].filter(branch => branch.sha === sha).sort((a, b) =>
      Number(Boolean(b.current)) - Number(Boolean(a.current)) || Number(Boolean(a.tag)) - Number(Boolean(b.tag)) ||
      Number(!/^(origin\/)?(master|main)$/.test(a.name)) - Number(!/^(origin\/)?(master|main)$/.test(b.name)) ||
      a.name.localeCompare(b.name));
  }
  return {Selection, defaults, references};
})();
if (typeof module !== "undefined") module.exports = GitHistoryScope;
