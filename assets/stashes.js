"use strict";
// A stash saves the index separately from the working-tree snapshot. Neither
// snapshot may hide paths from the other, even when they share a file name.
const GitStashFiles = {
  groups(worktree, staged, untracked) {
    return [
      {key: "staged", label: "已暂存", snapshot: staged},
      {key: "worktree", label: "工作区", snapshot: worktree},
      {key: "untracked", label: "未进行版本管理的文件", snapshot: untracked},
    ].filter(group => group.snapshot?.files.length).map(({key, label, snapshot}) => ({
      key, label, files: snapshot.files.map(file => ({...file, source: snapshot.sha, label})),
    }));
  },
};
if (typeof module !== "undefined") module.exports = GitStashFiles;
if (typeof window !== "undefined") window.GitStashes = (() => {
  let version = 0, detailVersion = 0, patchVersion = 0, current = null, items = [], repository = "";
  const readonly = !nativeHost;
  async function load() {
    const request = ++version, directory = selectedRepository;
    if (!directory) return;
    if (repository !== directory) { repository = directory; current = null; }
    try {
      const data = await api("stashes", {}, "stashes");
      if (version !== request || directory !== selectedRepository) return;
      items = data.stashes;
      render();
      const selected = items.find(item => item.sha === current?.sha) || items[0];
      if (selected) select(selected);
      else {
        current = null;
        empty($("stash-summary"), () => GitI18n.t("没有储藏记录"), () => GitI18n.t("可以先储藏工作区的修改。"));
        $("stash-files").replaceChildren(); $("stash-diff").replaceChildren(); $("stash-patch-title").hidden = true;
      }
    } catch (err) { if (version === request && err.name !== "AbortError") error(err); }
  }
  function render() {
    const target = $("stash-list"); target.replaceChildren();
    for (const item of items) {
      const row = el("button", "stash-row" + (current?.sha === item.sha ? " selected" : "")); row.dataset.sha = item.sha;
      row.append(el("span", "stash-ref", () => item.ref), el("strong", "", () => item.subject), el("time", "", () => date(item.date, true)));
      row.addEventListener("click", () => select(item)); target.append(row);
    }
    if (!items.length) empty(target, () => GitI18n.t("没有储藏记录"), null, true);
  }
  async function select(item) {
    current = item; render(); const request = ++detailVersion; patchVersion++;
    $("stash-files").replaceChildren(); $("stash-diff").replaceChildren(); $("stash-patch-title").hidden = true;
    const summary = $("stash-summary"); summary.replaceChildren(el("h3", "", () => item.subject));
    summary.append(el("p", "muted", () => item.ref + " · " + date(item.date, true)));
    const actions = el("div", "stash-actions");
    for (const [action, label] of [["stash_apply", "应用储藏"], ["stash_drop", "删除储藏"]]) {
      const button = el("button", "button" + (action === "stash_drop" ? " stash-delete" : ""), () => GitI18n.t(label));
      button.disabled = readonly; button.addEventListener("click", () => GitOperations.prepare(action, {sha: item.sha})); actions.append(button);
    }
    summary.append(actions);
    try {
      const detail = await api("commit", {sha: item.sha}, "stash-detail");
      if (request !== detailVersion || current?.sha !== item.sha) return;
      let staged = null;
      if (detail.parents.length >= 2) {
        staged = await api("commit", {sha: detail.parents[1]}, "stash-index");
        if (request !== detailVersion || current?.sha !== item.sha) return;
      }
      // The third stash parent contains untracked files; list them separately.
      let untracked = null;
      if (detail.parents.length >= 3) {
        untracked = await api("commit", {sha: detail.parents[2]}, "stash-untracked");
        if (request !== detailVersion || current?.sha !== item.sha) return;
      }
      const groups = GitStashFiles.groups(detail, staged, untracked);
      const target = $("stash-files"); target.replaceChildren();
      for (const group of groups) {
        const section = el("section", "stash-file-group");
        section.append(el("h4", "", () => GitI18n.t(group.label)));
        const tree = el("div"); section.append(tree); target.append(section);
        GitFileTree.mount(tree, group.files, {key: selectedRepository + ":stash:" + group.key,
          storage: folderStorage, onOpen: showFile});
      }
      const files = groups.flatMap(group => group.files);
      if (files[0]) showFile(files[0]);
    } catch (err) { if (request === detailVersion && err.name !== "AbortError") error(err); }
  }
  async function showFile(file) {
    const request = ++patchVersion;
    GitI18n.text($("stash-patch-title"), () => GitI18n.t(file.label) + " · " + file.path);
    $("stash-patch-title").hidden = false;
    GitI18n.text($("stash-diff"), () => GitI18n.t("正在读取差异…"));
    try {
      const data = await api("patch", {sha: file.source, path: file.path, parent: 0}, "stash-patch");
      if (request === patchVersion) GitDiffView.render($("stash-diff"), data);
    } catch (err) { if (request === patchVersion && err.name !== "AbortError") error(err); }
  }
  document.addEventListener("git-repository-loaded", () => { if (document.body.dataset.view === "stashes") load(); });
  return {load};
})();
