"use strict";
window.GitStashes = (() => {
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
        $("stash-files").replaceChildren(); $("stash-diff").replaceChildren();
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
    $("stash-files").replaceChildren(); $("stash-diff").replaceChildren();
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
      // The third stash parent contains untracked files; list them separately.
      let untracked = null;
      if (detail.parents.length >= 3) {
        untracked = await api("commit", {sha: detail.parents[2]}, "stash-untracked");
        if (request !== detailVersion || current?.sha !== item.sha) return;
      }
      const files = [...detail.files.map(file => ({...file, source: item.sha})),
        ...(untracked?.files || []).filter(file => !detail.files.some(known => known.path === file.path)).map(file => ({...file, source: untracked.sha}))];
      GitFileTree.mount($("stash-files"), files, {key: selectedRepository + ":stash", storage: folderStorage, onOpen: showFile});
      if (files[0]) showFile(files[0]);
    } catch (err) { if (request === detailVersion && err.name !== "AbortError") error(err); }
  }
  async function showFile(file) {
    const request = ++patchVersion;
    try {
      const data = await api("patch", {sha: file.source, path: file.path, parent: 0}, "stash-patch");
      if (request === patchVersion) GitDiffView.render($("stash-diff"), data);
    } catch (err) { if (request === patchVersion && err.name !== "AbortError") error(err); }
  }
  document.addEventListener("git-repository-loaded", () => { if (document.body.dataset.view === "stashes") load(); });
  return {load};
})();
