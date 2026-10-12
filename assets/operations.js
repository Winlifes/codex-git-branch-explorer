"use strict";
// Native-panel controls. Browsing a branch never switches the working tree.
window.GitOperations = (() => {
  const readOnly = !nativeHost;
  const selected = new Set(), collapsed = new Set();
  let selectionInitialized = false, activeWorkPath = "", workPatchData = null, workPatchVersion = 0;
  let diffMode = "unified";
  try { diffMode = localStorage.getItem("git-diff-mode") || "unified"; } catch {}
  let current = null, repository = "", statusVersion = 0, dialogVersion = 0;
  let busy = false, preview = null, submit = null, returnFocus = null;
  const work = $("work-dialog"), dialog = $("operation-dialog");
  const labels = {switch: "切换", create: "创建", stage: "暂存", unstage: "取消暂存", commit: "提交", commit_selected: "提交",
    fetch: "获取", pull: "拉取", push: "推送", merge: "合并", revert: "撤销提交", delete: "删除分支",
    continue: "继续", abort: "中止", discard: "撤回改动"};
  Object.assign(labels, {stash: "储藏", stash_apply: "应用储藏", stash_drop: "删除储藏"});
  GitI18n.text($("mode-label"), () => GitI18n.t(readOnly ? "只读" : "本地"));

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
    $("open-workspace").disabled = !state.repository || state.repository.bare;
    $("stashes-tab").disabled = !state.repository || state.repository.bare;
    $("git-actions").hidden = readOnly || !state.repository || state.repository.bare;
    for (const option of $("branch-action").options) {
      if (!option.value) continue;
      option.disabled = !b || b.tag || b.unborn || b.detached ||
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
      $("create-stash").disabled = readOnly || !data.changes.length || Boolean(data.operation) || Boolean(data.conflict_count) || !data.repository.head;
      document.querySelectorAll("[data-network]").forEach(button => { button.disabled = readOnly || !data.remotes.length || Boolean(data.operation); });
      document.dispatchEvent(new CustomEvent("git-workspace-status", {detail: data}));
      GitI18n.text($("change-count"), () => data.changes.length);
      if (!work.hidden) {
        renderWorkspace();
        const active = data.changes.find(file => file.path === activeWorkPath);
        if (active) showWorkingPatch(active.path, !active.unstaged && active.staged);
      }
    } catch (err) {
      if (err.name !== "AbortError") {
        GitI18n.text($("change-count"), () => "?");
        if (!work.hidden) displayError(err, $("work-error"));
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
  function commitEditor(action, args, draft = null, confirmed = false) {
    const editor = el("textarea", "commit-message-editor");
    editor.id = "preview-commit-message"; editor.rows = 7; editor.maxLength = 10000;
    editor.value = args.message || "";
    GitI18n.attr(editor, "aria-label", () => GitI18n.t("提交说明"));
    GitI18n.attr(editor, "placeholder", () => GitI18n.t("描述这次更改…"));
    field(() => GitI18n.t("提交说明"), editor);
    if (draft) $("operation-content").append(el("p", "operation-description muted", () => GitI18n.t(draft.partial ?
      "草稿基于本地改动生成，部分文件仅提取概要。请核对并修改说明。" : "草稿基于本地改动生成，可在此修改。")));
    const update = () => {
      if (busy) return;
      dialogVersion++; preview = null;
      $("commit-message").value = editor.value;
      $("confirm-operation").disabled = !editor.value.trim() || editor.value.length > 10000;
      GitI18n.text($("confirm-operation"), () => GitI18n.t("预览提交"));
      submit = () => prepare(action, {...args, message: editor.value}, true, draft);
    };
    editor.addEventListener("input", update);
    if (!confirmed) update();
    return editor;
  }
  async function prepareCommit(action) {
    if (busy || readOnly) return;
    const args = {message: $("commit-message").value, ...(action === "commit_selected" ? {paths: [...selected]} : {})};
    if (args.message.trim()) { prepare(action, args); return; }
    if (!beginDialog(() => GitI18n.t("生成提交说明"))) return;
    const version = dialogVersion, path = selectedRepository;
    const target = $("operation-content");
    target.append(el("p", "operation-description", () => GitI18n.t("正在根据提交内容生成说明…")));
    try {
      const data = await nativeHost.operation("git_query", {repo: path, action: "commit_message",
        ...(action === "commit_selected" ? {paths: args.paths} : {staged: true})});
      if (!dialog.open || version !== dialogVersion || path !== selectedRepository) return;
      target.replaceChildren();
      GitI18n.text($("operation-title"), () => GitI18n.t("编辑提交说明"));
      target.append(el("p", "operation-description", () => GitI18n.t(action === "commit_selected" ?
        "说明针对勾选文件的全部当前改动。" : "说明针对已暂存的改动。")));
      args.message = data.message;
      const editor = commitEditor(action, args, data);
      $("commit-message").value = editor.value;
      target.append(el("p", "muted", () => GitI18n.t("{count} 个文件", {count: data.files.length})));
      const list = el("div", "operation-files");
      for (const file of data.files) list.append(el("code", "", () => file));
      target.append(list); editor.focus();
    } catch (err) {
      if (!dialog.open || version !== dialogVersion || path !== selectedRepository) return;
      target.replaceChildren();
      GitI18n.text($("operation-title"), () => GitI18n.t("编辑提交说明"));
      target.append(el("p", "operation-description", () => GitI18n.t("未能生成草稿，可手动填写说明后预览提交。")));
      const editor = commitEditor(action, args);
      displayError(err); editor.focus();
    }
  }
  async function prepare(action, args = {}, alreadyOpen = false, draft = null) {
    if (busy || readOnly) return;
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
      const committing = ["commit", "commit_selected"].includes(action);
      // Commit plans keep their second detail for older panels. The current
      // panel shows that exact message once, in an editable field instead.
      for (const [index, text] of data.details.entries()) {
        if (!committing || index !== 1) target.append(el("p", "operation-description", () => text));
      }
      if (committing) commitEditor(action, args, draft, true);
      if (data.files.length) {
        target.append(el("p", "muted", () => GitI18n.t("{count} 个文件", {count: data.files.length})));
        const list = el("div", "operation-files");
        for (const path of data.files) list.append(el("code", "", () => path));
        target.append(list);
      }
      GitI18n.text($("confirm-operation"), () => GitI18n.t("确认") + GitI18n.t(labels[action]));
      $("confirm-operation").classList.toggle("danger", ["delete", "abort", "discard", "stash_drop"].includes(action));
      $("confirm-operation").disabled = false;
      submit = execute;
      $("cancel-operation").focus();
    } catch (err) {
      if (version !== dialogVersion) return;
      displayError(err);
      GitI18n.text($("confirm-operation"), () => GitI18n.t("预览操作"));
      $("confirm-operation").disabled = !alreadyOpen;
      if (!work.hidden) loadStatus();
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
    const editor = $("preview-commit-message");
    if (editor) editor.disabled = true;
    try {
      const result = await nativeHost.operation("git_apply", {repo: chosen.repository.path, token: chosen.token});
      if (result.ok && ["commit", "commit_selected"].includes(chosen.action)) $("commit-message").value = "";
      // The next explicit action always gets a fresh preview, even after failure.
      busy = false; closeOperation();
      if (!["stage", "unstage", "discard"].includes(chosen.action)) {
        if (["switch", "create", "commit", "commit_selected", "merge", "revert", "continue", "abort"].includes(chosen.action)) state.branch = null;
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
      if (!result.ok && !work.hidden) displayError(GitI18n.error(() => result.message), $("work-error"));
      if (!result.ok && result.status?.conflict_count && work.hidden) openWorkspace();
    } catch (err) {
      busy = false; preview = null; submit = null;
      displayError(GitI18n.error(() => err.message + GitI18n.t("\n请刷新确认仓库状态后再操作；不会自动重复执行。")));
      GitI18n.text($("confirm-operation"), () => GitI18n.t("请关闭后刷新"));
      await loadStatus();
    } finally {
      busy = false; $("cancel-operation").disabled = false; $("close-operation").disabled = false;
      if (editor) editor.disabled = false;
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
  function createStash() {
    if (readOnly || !beginDialog(() => GitI18n.t("储藏修改"))) return;
    const message = input(() => GitI18n.t("储藏说明"), "", GitI18n.t("描述尚未完成的工作…"));
    message.maxLength = 10000;
    const include = checkbox(() => GitI18n.t("包含未跟踪文件"), true);
    enableForm(() => prepare("stash", {message: message.value, include_untracked: include.checked}, true));
    message.focus();
  }
  function addRevertButton(target, commit) {
    if (readOnly || state.repository?.bare) return;
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
    window.GitWorkbench?.view("workspace");
    work.hidden = false;
    await loadStatus();
  }
  function renderWorkspace() {
    const s = current;
    if (!s) return;
    GitI18n.text($("work-branch"), () => s.repository.name + " / " +
      (s.repository.current_ref?.replace(/^refs\/heads\//, "") || GitI18n.t("游离 HEAD")));
    const available = new Set(s.changes.map(file => file.path));
    for (const path of selected) if (!available.has(path)) selected.delete(path);
    if (!selectionInitialized) {
      for (const file of s.changes) if (file.staged && file.operable && !file.conflict) selected.add(file.path);
      selectionInitialized = true;
    }
    if (activeWorkPath && !available.has(activeWorkPath)) {
      activeWorkPath = ""; workPatchData = null; workPatchVersion++;
      $("work-patch-section").hidden = true;
      $("work-diff-empty").hidden = false;
    }
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
    for (const [key, title] of [["tracked", "更改"], ["untracked", "未进行版本管理的文件"]]) {
      const files = s.changes.filter(file => key === "untracked" ? file.untracked : !file.untracked);
      if (!files.length && key === "untracked") continue;
      const group = el("section", "work-group"), heading = el("div", "work-group-heading file-tree-row selectable");
      const expand = el("button", "file-disclosure" + (collapsed.has(key) ? "" : " expanded"));
      expand.append(GitUI.icon("chevron")); expand.setAttribute("aria-expanded", String(!collapsed.has(key)));
      GitI18n.attr(expand, "aria-label", () => GitI18n.t("展开或收起 ") + GitI18n.t(title));
      expand.addEventListener("click", () => { collapsed.has(key) ? collapsed.delete(key) : collapsed.add(key); renderWorkspace(); });
      const all = el("input"); all.type = "checkbox"; all.dataset.group = key;
      const check = GitFileTree.selection(files, selected);
      Object.assign(all, {checked: check.checked, indeterminate: check.indeterminate, disabled: check.disabled});
      GitI18n.attr(all, "aria-label", () => GitI18n.t("选择 ") + GitI18n.t(title));
      all.addEventListener("change", () => { for (const path of check.paths) all.checked ? selected.add(path) : selected.delete(path); renderWorkspace(); });
      heading.append(expand, all, el("h3", "", () => GitI18n.t(title)),
        el("span", "file-tree-count", () => GitI18n.t("{count} 个文件", {count: files.length})));
      group.append(heading);
      if (!files.length) group.append(el("p", "work-empty", () => GitI18n.t("工作区没有未暂存的更改")));
      if (!collapsed.has(key)) {
        const tree = el("div", "work-file-tree"); group.append(tree);
        GitFileTree.mount(tree, files, {selected, key: repository + ":" + key, storage: folderStorage,
          active: activeWorkPath,
          onToggle(paths, checked) { for (const path of paths) checked ? selected.add(path) : selected.delete(path); updateSelection(); },
          onOpen: file => showWorkingPatch(file.path, !file.unstaged && file.staged),
          actions(file) {
            const actions = el("span", "work-file-actions");
            if (file.staged) {
              const badge = el("span", "staged-mark"); badge.append(GitUI.icon("check"));
              GitI18n.attr(badge, "title", () => GitI18n.t("已暂存")); actions.append(badge);
            }
            for (const action of ["discard", "stage", "unstage"]) {
              if (action === "unstage" ? !file.staged : !file.unstaged) continue;
              const button = el("button", "icon-button" + (action === "discard" ? " discard-file" : ""));
              button.append(GitUI.icon(action === "discard" ? "undo" : action === "stage" ? "plus" : "minus"));
              GitI18n.attr(button, "aria-label", () => GitI18n.t(labels[action]) + " " + file.path);
              GitI18n.attr(button, "title", () => GitI18n.t(labels[action]));
              button.disabled = readOnly || !file.operable || (action === "discard" && (file.conflict || Boolean(s.operation)));
              button.addEventListener("click", () => prepare(action, {paths: [file.path]})); actions.append(button);
            }
            return actions;
          }});
      }
      target.append(group);
    }
    updateSelection();
    $("prepare-staged").disabled = readOnly || Boolean(s.conflict_count) || s.operation === "revert" || !s.staged_count;
    document.querySelectorAll("[data-network]").forEach(button => { button.disabled = readOnly || !s.remotes.length || Boolean(s.operation); });
  }
  function updateSelection() {
    if (!current) return;
    const paths = [...selected];
    $("prepare-commit").disabled = readOnly || !paths.length || paths.length > 500 || Boolean(current.conflict_count) || Boolean(current.operation);
    $("stage-selected").disabled = readOnly || !current.changes.some(file => selected.has(file.path) && file.unstaged && file.operable);
    $("unstage-selected").disabled = readOnly || !current.changes.some(file => selected.has(file.path) && file.staged && file.operable);
    $("discard-selected").disabled = readOnly || Boolean(current.operation) || !current.changes.some(file => selected.has(file.path) && file.unstaged && file.operable && !file.conflict);
    GitI18n.text($("commit-hint"), () => readOnly ? GitI18n.t("浏览器模式只读；请在 Codex Git 面板中提交。") :
      !paths.length ? GitI18n.t("请先勾选要提交的文件（共 {total} 个）。", {total: current.changes.length}) :
      GitI18n.t("已选择 {selected} / {total} 个文件", {selected: paths.length, total: current.changes.length}));
    for (const checkbox of $("work-changes").querySelectorAll("input[data-group]")) {
      const files = current.changes.filter(file => checkbox.dataset.group === "untracked" ? file.untracked : !file.untracked);
      const check = GitFileTree.selection(files, selected);
      checkbox.checked = check.checked; checkbox.indeterminate = check.indeterminate;
    }
    GitI18n.text($("status-selection"), () => paths.length ? GitI18n.t("已选择 {count} 个文件", {count: paths.length}) : "");
  }
  async function showWorkingPatch(path, staged) {
    activeWorkPath = path;
    const version = ++workPatchVersion;
    GitI18n.text($("work-patch-path"), () => path + (staged ? GitI18n.t(" · 已暂存") : GitI18n.t(" · 工作区")));
    $("work-patch-section").hidden = false; $("work-diff-empty").hidden = true;
    GitI18n.text($("work-patch"), () => GitI18n.t("正在读取差异…"));
    try {
      const data = await api("working_patch", {path, staged}, "working-patch");
      if (version !== workPatchVersion) return;
      workPatchData = data; renderWorkingDiff();
    } catch (err) { if (err.name !== "AbortError" && version === workPatchVersion) displayError(err, $("work-error")); }
  }
  function renderWorkingDiff() {
    const split = diffMode === "split";
    document.querySelectorAll("[data-diff-mode]").forEach(button => {
      const active = button.dataset.diffMode === diffMode;
      button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active));
    });
    document.querySelector(".diff-side-labels").hidden = !split;
    if (workPatchData) GitDiffView.render($("work-patch"), workPatchData, split);
  }
  document.querySelectorAll("[data-diff-mode]").forEach(button => button.addEventListener("click", () => {
    diffMode = button.dataset.diffMode;
    try { localStorage.setItem("git-diff-mode", diffMode); } catch {}
    renderWorkingDiff();
  }));
  renderWorkingDiff();
  document.addEventListener("git-repository-loaded", () => {
    if (repository !== selectedRepository) {
      repository = selectedRepository; current = null;
      $("commit-message").value = ""; $("operation-result").hidden = true;
      $("work-result").hidden = true;
      selected.clear(); selectionInitialized = false; activeWorkPath = ""; workPatchData = null; workPatchVersion++;
      window.GitWorkbench?.view("history"); work.hidden = true; closeOperation();
    }
    updateBranchActions(); loadStatus();
  });
  $("open-workspace").addEventListener("click", openWorkspace);
  $("close-work").addEventListener("click", () => { window.GitWorkbench?.view("history"); work.hidden = true; $("open-workspace").focus(); });
  $("refresh-work").addEventListener("click", () => { $("work-error").hidden = true; loadStatus(); });
  $("create-branch").addEventListener("click", createBranch);
  $("create-stash").addEventListener("click", createStash);
  $("branch-action").addEventListener("change", event => {
    const action = event.target.value; event.target.value = "";
    if (action && state.branch) prepare(action, {ref: state.branch.ref});
  });
  document.querySelectorAll("[data-network]").forEach(b => b.addEventListener("click", () => network(b.dataset.network)));
  $("prepare-commit").addEventListener("click", () => prepareCommit("commit_selected"));
  $("prepare-staged").addEventListener("click", () => prepareCommit("commit"));
  $("discard-selected").addEventListener("click", () => prepare("discard", {paths: current.changes.filter(file => selected.has(file.path) && file.unstaged && file.operable && !file.conflict).map(file => file.path)}));
  for (const [id, action, key] of [["stage-selected", "stage", "unstaged"], ["unstage-selected", "unstage", "staged"]]) {
    $(id).addEventListener("click", () => prepare(action, {paths: current.changes.filter(file => selected.has(file.path) && file[key] && file.operable).map(file => file.path)}));
  }
  $("close-work-patch").addEventListener("click", () => { controllers.get("working-patch")?.abort(); workPatchVersion++; workPatchData = null; activeWorkPath = ""; $("work-patch-section").hidden = true; $("work-diff-empty").hidden = false; });
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
  return {updateBranchActions, addRevertButton, openWorkspace, loadStatus, prepare};
})();
