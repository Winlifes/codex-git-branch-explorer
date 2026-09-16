"use strict";
// Native-panel controls. Browsing a branch never switches the working tree.
window.GitOperations = (() => {
  if (!nativeHost) return {updateBranchActions() {}, addRevertButton() {}};
  let current = null, repository = "", statusVersion = 0, dialogVersion = 0;
  let busy = false, preview = null, submit = null, returnFocus = null;
  const work = $("work-dialog"), dialog = $("operation-dialog");
  const labels = {switch: "切换", create: "创建", stage: "暂存", unstage: "取消暂存", commit: "提交",
    fetch: "获取", pull: "拉取", push: "推送", merge: "合并", revert: "撤销提交", delete: "删除分支",
    continue: "继续", abort: "中止", discard: "撤回改动"};
  GitI18n.text($("mode-label"), () => GitI18n.t("本地"));

  function displayError(err, target = $("operation-error")) {
    GitI18n.text(target, () => err.message);
    target.hidden = false;
  }
  function resultMessage(text, ok = true) {
    const node = $("operation-result");
    node.replaceChildren(el("span", "", () => text));
    node.dataset.ok = String(ok); node.hidden = false;
    const close = el("button", "text-button", () => GitI18n.t("关闭"));
    close.addEventListener("click", () => { node.hidden = true; });
    node.append(close);
  }
  function updateBranchActions() {
    const b = state.branch;
    $("git-actions").hidden = !state.repository || state.repository.bare;
    for (const option of $("branch-action").options) {
      if (!option.value) continue;
      option.disabled = !b || b.unborn || b.detached ||
        ((option.value === "switch" || option.value === "delete") && (b.remote || b.current));
    }
    $("create-branch").disabled = !state.repository?.head;
    window.GitUI.sync($("branch-action"));
  }
  async function loadStatus() {
    if (!state.repository || state.repository.bare) return;
    const version = ++statusVersion, path = selectedRepository;
    $("refresh-work").disabled = true;
    try {
      const data = await api("status", {}, "work-status");
      if (version !== statusVersion || path !== selectedRepository) return;
      current = data;
      GitI18n.text($("change-count"), () => data.changes.length);
      if (work.open) renderWorkspace();
    } catch (err) {
      if (err.name !== "AbortError") {
        GitI18n.text($("change-count"), () => "?");
        if (work.open) displayError(err, $("work-error"));
      }
    } finally { if (version === statusVersion) $("refresh-work").disabled = false; }
  }
  function closeOperation() {
    if (busy) return;
    dialogVersion++; preview = null; submit = null;
    dialog.close(); returnFocus?.focus();
  }
  function beginDialog(title) {
    if (busy) return false;
    window.GitUI.closeMenus();
    dialogVersion++; preview = null; submit = null;
    returnFocus = document.activeElement;
    GitI18n.text($("operation-title"), () => title);
    $("operation-content").replaceChildren();
    $("operation-error").hidden = true;
    $("confirm-operation").disabled = true;
    $("confirm-operation").classList.remove("danger");
    GitI18n.text($("confirm-operation"), () => GitI18n.t("预览操作"));
    GitI18n.text($("cancel-operation"), () => GitI18n.t("取消"));
    if (!dialog.open) dialog.showModal();
    return true;
  }
  function field(label, control) {
    const wrapper = el("label", "operation-field", () => label);
    wrapper.append(control); $("operation-content").append(wrapper);
    if (control.tagName === "SELECT") window.GitUI.enhance(control);
    return control;
  }
  function input(label, value = "", placeholder = "") {
    const node = el("input"); node.type = "text"; node.value = value;
    GitI18n.attr(node, "placeholder", () => placeholder); node.autocomplete = "off"; node.spellcheck = false;
    return field(label, node);
  }
  function checkbox(label, checked) {
    const node = el("input"); node.type = "checkbox"; node.checked = checked;
    const wrapper = el("label", "operation-checkbox"); wrapper.append(node, el("span", "", () => label));
    $("operation-content").append(wrapper); return node;
  }
  function enableForm(action) {
    submit = action; $("confirm-operation").disabled = false;
  }
  async function prepare(action, args = {}, alreadyOpen = false) {
    if (busy) return;
    if (!alreadyOpen && !beginDialog(() => GitI18n.t(labels[action]))) return;
    const version = ++dialogVersion, path = selectedRepository;
    $("operation-error").hidden = true;
    $("confirm-operation").disabled = true;
    GitI18n.text($("confirm-operation"), () => GitI18n.t("正在检查…"));
    try {
      const data = await nativeHost.operation("git_prepare", {repo: path, action, ...args});
      if (!dialog.open || version !== dialogVersion || path !== selectedRepository) return;
      preview = data;
      GitI18n.text($("operation-title"), () => data.title);
      const target = $("operation-content"); target.replaceChildren();
      const context = el("div", "operation-context");
      context.append(el("strong", "", () => data.repository.name), el("code", "", () => data.repository.path));
      target.append(context);
      for (const text of data.details) target.append(el("p", "operation-description", () => text));
      if (data.files.length) {
        target.append(el("p", "muted", () => GitI18n.t("{count} 个文件", {count: data.files.length})));
        const list = el("div", "operation-files");
        for (const path of data.files) list.append(el("code", "", () => path));
        target.append(list);
      }
      GitI18n.text($("confirm-operation"), () => GitI18n.t("确认") + GitI18n.t(labels[action]));
      $("confirm-operation").classList.toggle("danger", ["delete", "abort", "discard"].includes(action));
      $("confirm-operation").disabled = false;
      submit = execute;
      $("cancel-operation").focus();
    } catch (err) {
      if (version !== dialogVersion) return;
      displayError(err);
      GitI18n.text($("confirm-operation"), () => GitI18n.t("预览操作"));
      $("confirm-operation").disabled = !alreadyOpen;
      if (work.open) loadStatus();
    }
  }
  async function execute() {
    if (!preview || busy) return;
    const chosen = preview;
    busy = true;
    $("operation-error").hidden = true;
    $("confirm-operation").disabled = true;
    GitI18n.text($("confirm-operation"), () => GitI18n.t("正在") + GitI18n.t(labels[chosen.action]) + "…");
    $("cancel-operation").disabled = true; $("close-operation").disabled = true;
    try {
      const result = await nativeHost.operation("git_apply", {repo: chosen.repository.path, token: chosen.token});
      if (result.ok && chosen.action === "commit") $("commit-message").value = "";
      // The next explicit action always gets a fresh preview, even after failure.
      busy = false; closeOperation();
      if (!["stage", "unstage", "discard"].includes(chosen.action)) {
        if (["switch", "create", "commit", "merge", "revert", "continue", "abort"].includes(chosen.action)) state.branch = null;
        await refresh();
      }
      await loadStatus();
      resultMessage(result.message, result.ok);
      if (chosen.action === "discard") {
        const notice = $("work-result"); notice.hidden = false;
        notice.replaceChildren(el("p", "", () => GitI18n.format(result.message) + (result.ok ? GitI18n.t(" 已暂存的内容已保留。") : "")));
        if (result.backup_path) {
          const details = el("details"); details.append(el("summary", "", () => GitI18n.t("查看本次撤回的本地备份")));
          details.append(el("code", "", () => result.backup_path),
            el("p", "muted", () => GitI18n.t("manifest.json 记录原文件名；编号 .data 文件保留撤回前的原始内容。备份不会自动删除。")));
          notice.append(details);
        }
        notice.scrollIntoView({block:"nearest"});
      }
      if (!result.ok && work.open) displayError(GitI18n.error(() => result.message), $("work-error"));
      if (!result.ok && result.status?.conflict_count && !work.open) openWorkspace();
    } catch (err) {
      busy = false; preview = null; submit = null;
      displayError(GitI18n.error(() => err.message + GitI18n.t("\n请刷新确认仓库状态后再操作；不会自动重复执行。")));
      GitI18n.text($("confirm-operation"), () => GitI18n.t("请关闭后刷新"));
      await loadStatus();
    } finally {
      busy = false; $("cancel-operation").disabled = false; $("close-operation").disabled = false;
    }
  }
  async function network(action) {
    if (!beginDialog(() => GitI18n.t("{action}远程分支", {action: GitI18n.t(labels[action])}))) return;
    const version = dialogVersion;
    await loadStatus();
    if (!dialog.open || version !== dialogVersion) return;
    if (!current?.remotes.length) {
      displayError(GitI18n.error(() => GitI18n.t("当前仓库还没有配置远程地址，请先在终端添加远程仓库，再刷新。"))); return;
    }
    const select = el("select");
    for (const r of current.remotes) { const option = el("option", "", () => r.name); option.value = r.name; select.append(option); }
    const suggested = current.upstream?.remote;
    if (current.remotes.some(r => r.name === suggested)) select.value = suggested;
    field(() => GitI18n.t("远程仓库"), select);
    const path = el("p", "operation-description"); $("operation-content").append(path);
    const showAddress = () => {
      const r = current.remotes.find(r => r.name === select.value);
      GitI18n.text(path, () => (action === "push" ? r.push_urls : r.fetch_urls).map(GitI18n.format).join("\n"));
    };
    select.addEventListener("change", showAddress); showAddress();
    let branch, upstream;
    if (action !== "fetch") {
      branch = input(() => action === "push" ? GitI18n.t("远程目标分支") : GitI18n.t("拉取的远程分支"), (current.upstream?.ref || current.repository.current_ref || "").replace(/^refs\/heads\//, ""));
      if (action === "push") upstream = checkbox(() => GitI18n.t("设为当前分支的上游"), !current.upstream);
    }
    enableForm(() => prepare(action, {remote: select.value, ...(branch ? {branch: branch.value.trim()} : {}),
      ...(upstream ? {set_upstream: upstream.checked} : {})}, true));
    window.GitUI.focus(select);
  }
  function createBranch() {
    const source = state.branch?.ref || "HEAD";
    if (!beginDialog(() => GitI18n.t("新建分支"))) return;
    $("operation-content").append(el("p", "operation-description", () => GitI18n.t("从 ") + (state.branch?.name || GitI18n.t("当前提交")) + GitI18n.t(" 创建本地分支。")));
    const name = input(() => GitI18n.t("分支名称"), "", "feature/my-change");
    name.maxLength = 240;
    const checkout = checkbox(() => GitI18n.t("创建后切换到新分支"), true);
    enableForm(() => prepare("create", {ref: source, name: name.value.trim(), checkout: checkout.checked}, true));
    name.focus();
  }
  function addRevertButton(target, commit) {
    if (state.repository?.bare) return;
    const button = el("button", "button revert-button", () => GitI18n.t("撤销此提交…"));
    button.addEventListener("click", () => {
      if (commit.parents.length < 2) { prepare("revert", {sha: commit.sha}); return; }
      if (!beginDialog(() => GitI18n.t("撤销合并提交"))) return;
      $("operation-content").append(el("p", "operation-description", () => GitI18n.t("选择保留的父提交主线。将创建反向提交，撤销相对该主线引入的改动。")));
      const select = el("select");
      commit.parents.forEach((sha, i) => {
        const option = el("option", "", () => GitI18n.t("父提交 ") + (i + 1) + " · " + sha.slice(0, 12));
        option.value = i + 1; select.append(option);
      });
      field(() => GitI18n.t("保留主线"), select);
      enableForm(() => prepare("revert", {sha: commit.sha, mainline: Number(select.value)}, true));
    });
    target.append(button);
  }
  async function openWorkspace() {
    if (!state.repository || busy) return;
    $("work-error").hidden = true;
    $("work-changes").replaceChildren(el("p", "muted", () => GitI18n.t("正在读取工作区…")));
    $("prepare-commit").disabled = true;
    closeBranches();
    if (!work.open) work.showModal();
    await loadStatus();
  }
  function renderWorkspace() {
    const s = current;
    if (!s) return;
    GitI18n.text($("work-branch"), () => s.repository.name + " / " +
      (s.repository.current_ref?.replace(/^refs\/heads\//, "") || GitI18n.t("游离 HEAD")));
    $("work-patch-section").hidden = true;
    controllers.get("working-patch")?.abort();
    const progress = $("work-progress"); progress.replaceChildren(); progress.hidden = !s.operation;
    if (s.operation) {
      const title = () => s.operation === "merge" ? GitI18n.t("合并") : s.operation === "revert" ? GitI18n.t("撤销") : s.operation;
      progress.append(el("strong", "", () => title() + GitI18n.t("尚未完成")), el("p", "", () => s.conflict_count ?
        s.conflict_count + GitI18n.t(" 个冲突文件。请在编辑器中解决后，回到这里暂存并继续。") : GitI18n.t("请检查暂存内容，确认后继续完成操作。")));
      if (["merge", "revert"].includes(s.operation)) {
        const actions = el("div", "git-actions");
        for (const action of ["continue", "abort"]) {
          const button = el("button", "button", () => (action === "continue" ? GitI18n.t("继续") : GitI18n.t("中止")) + title());
          button.disabled = action === "continue" && Boolean(s.conflict_count);
          button.addEventListener("click", () => prepare(action)); actions.append(button);
        }
        progress.append(actions);
      }
    }
    const target = $("work-changes"); target.replaceChildren();
    for (const [key, title, action] of [["unstaged", "更改", "stage"], ["staged", "已暂存", "unstage"]]) {
      const files = s.changes.filter(c => c[key]);
      const group = el("section", "work-group"), heading = el("div", "work-group-heading");
      heading.append(el("h3", "", () => GitI18n.t(title) + " · " + files.length));
      const paths = files.filter(c => c.operable).map(c => c.path);
      const all = el("button", "text-button", () => action === "stage" ? GitI18n.t("全部暂存") : GitI18n.t("全部取消暂存"));
      all.disabled = !paths.length || paths.length > 500;
      all.addEventListener("click", () => prepare(action, {paths}));
      const groupActions = el("div", "work-group-actions");
      if (key === "unstaged") {
        const discard = el("button", "text-button discard-all", () => GitI18n.t("全部撤回"));
        discard.prepend(window.GitUI.icon("undo"));
        GitI18n.attr(discard, "title", () => GitI18n.t("撤回全部未暂存的改动，保留已暂存的内容"));
        discard.disabled = !files.length || Boolean(s.operation) || files.some(f => !f.operable || f.conflict);
        discard.addEventListener("click", () => prepare("discard", {all:true}));
        groupActions.append(discard);
      }
      groupActions.append(all); heading.append(groupActions); group.append(heading);
      if (!files.length) group.append(el("p", "work-empty", () => key === "unstaged" ? GitI18n.t("工作区没有未暂存的更改") : GitI18n.t("还没有暂存的更改")));
      for (const file of files) {
        const row = el("div", "work-file");
        const view = el("button", "work-file-path");
        view.append(el("span", "file-status" + (file.conflict ? " del" : ""), () => file.conflict ? GitI18n.t("冲突") :
          file.untracked ? "U" : file[key === "staged" ? "index_status" : "worktree_status"]), el("code", "", () => file.path));
        view.disabled = !file.operable;
        view.addEventListener("click", () => showWorkingPatch(file.path, key === "staged"));
        const change = el("button", "icon-button");
        change.append(window.GitUI.icon(action === "stage" ? "plus" : "minus"));
        GitI18n.attr(change, "aria-label", () => (action === "stage" ? GitI18n.t("暂存 ") : GitI18n.t("取消暂存 ")) + file.path);
        change.disabled = !file.operable;
        change.addEventListener("click", () => prepare(action, {paths: [file.path]}));
        row.append(view);
        if (key === "unstaged") {
          const discard = el("button", "icon-button discard-file");
          discard.append(window.GitUI.icon("undo"));
          GitI18n.attr(discard, "aria-label", () => GitI18n.t("撤回改动 ") + file.path);
          GitI18n.attr(discard, "title", () => GitI18n.t("撤回此文件未暂存的改动，保留已暂存的内容"));
          discard.disabled = !file.operable || file.conflict || Boolean(s.operation);
          discard.addEventListener("click", () => prepare("discard", {paths:[file.path]}));
          row.append(discard);
        }
        row.append(change); group.append(row);
      }
      target.append(group);
    }
    $("prepare-commit").disabled = Boolean(s.conflict_count) || s.operation === "revert" || !s.staged_count;
    GitI18n.text($("commit-hint"), () => GitI18n.t("将提交 {count} 个已暂存文件", {count: s.staged_count}));
    document.querySelectorAll("[data-network]").forEach(b => { b.disabled = !s.remotes.length || Boolean(s.operation); });
  }
  async function showWorkingPatch(path, staged) {
    GitI18n.text($("work-patch-path"), () => path + (staged ? GitI18n.t(" · 已暂存") : GitI18n.t(" · 工作区")));
    $("work-patch-section").hidden = false;
    GitI18n.text($("work-patch"), () => GitI18n.t("正在读取差异…"));
    try {
      const data = await api("working_patch", {path, staged}, "working-patch");
      const fragment = document.createDocumentFragment();
      if (data.notice) fragment.append(el("span", "diff-line meta", () => data.notice));
      for (const line of data.patch.split("\n")) {
        const cls = line.startsWith("+++") || line.startsWith("---") ? "meta" :
          line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : line.startsWith("@@") ? "hunk" : "";
        fragment.append(el("span", "diff-line " + cls, () => line || " "));
      }
      if (data.truncated) fragment.append(el("span", "diff-line meta", () => GitI18n.t("差异较大，仅展示前 800 KB。")));
      $("work-patch").replaceChildren(fragment);
      $("work-patch-section").scrollIntoView({block: "nearest"});
    } catch (err) { if (err.name !== "AbortError") displayError(err, $("work-error")); }
  }
  document.addEventListener("git-repository-loaded", () => {
    if (repository !== selectedRepository) {
      repository = selectedRepository; current = null;
      $("commit-message").value = ""; $("operation-result").hidden = true;
      $("work-result").hidden = true;
      work.close(); closeOperation();
    }
    updateBranchActions(); loadStatus();
  });
  $("open-workspace").addEventListener("click", openWorkspace);
  $("close-work").addEventListener("click", () => { work.close(); $("open-workspace").focus(); });
  $("refresh-work").addEventListener("click", () => { $("work-error").hidden = true; loadStatus(); });
  $("create-branch").addEventListener("click", createBranch);
  $("branch-action").addEventListener("change", event => {
    const action = event.target.value; event.target.value = "";
    if (action && state.branch) prepare(action, {ref: state.branch.ref});
  });
  document.querySelectorAll("[data-network]").forEach(b => b.addEventListener("click", () => network(b.dataset.network)));
  $("prepare-commit").addEventListener("click", () => prepare("commit", {message: $("commit-message").value}));
  $("close-work-patch").addEventListener("click", () => { controllers.get("working-patch")?.abort(); $("work-patch-section").hidden = true; });
  $("confirm-operation").addEventListener("click", () => { if (!busy && !$("confirm-operation").disabled) submit?.(); });
  $("cancel-operation").addEventListener("click", closeOperation);
  $("close-operation").addEventListener("click", closeOperation);
  dialog.addEventListener("cancel", event => { event.preventDefault(); closeOperation(); });
  dialog.addEventListener("keydown", event => {
    if (event.key === "Enter" && event.target.matches("input[type=text]") && !event.isComposing) {
      event.preventDefault(); if (!$("confirm-operation").disabled) submit?.();
    }
  });
  // Escape in a dialog should not also close the underlying commit details.
  for (const modal of [dialog, work]) modal.addEventListener("keydown", event => {
    if (event.key === "Escape") event.stopPropagation();
  });
  updateBranchActions();
  return {updateBranchActions, addRevertButton};
})();
