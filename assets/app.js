"use strict";
const $ = (id) => document.getElementById(id);
const state = {branches: [], repository: null, branch: null, kind: "all",
  commits: [], offset: 0, snapshot: null, hasMore: false, detail: null,
  historyVersion: 0, detailVersion: 0, patchVersion: 0, branchesVersion: 0,
  filters: {query: "", author: "", first_parent: false}};
const controllers = new Map();
const nativeHost = window.GitHost;
let selectedRepository = "";
try { $("theme").value = localStorage.getItem("git-explorer-theme") || "auto"; } catch {}
function setTheme() {
  const theme = $("theme").value;
  const automatic = nativeHost?.context.theme || (matchMedia("(prefers-color-scheme:dark)").matches ? "dark" : "light");
  document.documentElement.dataset.theme = theme === "auto" ? automatic : theme;
  document.documentElement.toggleAttribute("data-host-theme", Boolean(nativeHost && theme === "auto"));
  const variables = nativeHost?.context.styles?.variables || {};
  for (const [key, value] of Object.entries(variables)) {
    if (/^--[a-z0-9-]+$/.test(key) && typeof value === "string") document.documentElement.style.setProperty(key, value);
  }
  try { localStorage.setItem("git-explorer-theme", theme); } catch {}
  window.GitUI.sync($("theme"));
}
document.addEventListener("git-host-context", setTheme);
$("theme").addEventListener("change", setTheme);
matchMedia("(prefers-color-scheme:dark)").addEventListener("change", setTheme);
setTheme();
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) GitI18n.text(node, () => text);
  return node;
}
function empty(target, title, subtitle, compact = false) {
  const node = el("div", "empty" + (compact ? " compact" : ""));
  node.append(el("strong", "", () => title));
  if (subtitle) node.append(el("span", "", () => subtitle));
  target.replaceChildren(node);
}
function date(value, full = false) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return new Intl.DateTimeFormat(GitI18n.locale, full ?
    {year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23"} :
    {month: "2-digit", day: "2-digit"}).format(d);
}
function exactDate(value) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value || "";
  return new Intl.DateTimeFormat(GitI18n.locale, {year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23", timeZoneName: "short"}).format(d);
}
function error(err) {
  if (err.name === "AbortError") return;
  GitI18n.text($("error"), () => err.message);
  $("error").hidden = false;
}
function clearError() { $("error").hidden = true; }
async function api(route, params = {}, channel = route, method = "GET") {
  controllers.get(channel)?.abort();
  const controller = new AbortController();
  controllers.set(channel, controller);
  try {
    if (nativeHost) {
      const args = {...params};
      if (selectedRepository) args.repo = selectedRepository;
      return await nativeHost.query(route, args, controller.signal);
    }
    const response = await fetch("./api/" + route + "?" + new URLSearchParams(params),
      {signal: controller.signal, cache: "no-store", method});
    const body = await response.json();
    GitI18n.hydrate(body, body._gitMessages);
    if (!response.ok) throw GitI18n.error(() => body.error || GitI18n.t("查询失败。"));
    return body;
  } catch (err) {
    if (err instanceof TypeError) throw GitI18n.error(() => GitI18n.t("本地浏览会话已断开，请在 Codex 中重新打开 Git 分支浏览器。"));
    throw err;
  } finally {
    if (controllers.get(channel) === controller) controllers.delete(channel);
  }
}
function closeBranches() {
  document.body.classList.remove("branches-open");
  $("scrim").hidden = true;
  $("toggle-branches").setAttribute("aria-expanded", "false");
  // Off-canvas controls must not remain keyboard-focusable.
  $("sidebar").inert = matchMedia("(max-width:760px)").matches;
}
function renderBranches() {
  const target = $("branches");
  target.replaceChildren();
  const q = $("branch-search").value.trim().toLocaleLowerCase();
  const branches = state.branches.filter(b => b.name.toLocaleLowerCase().includes(q) &&
    (state.kind === "all" || (state.kind === "remote") === b.remote));
  for (const [remote, title] of [[false, "本地分支"], [true, "远程分支"]]) {
    const group = branches.filter(b => b.remote === remote);
    if (!group.length) continue;
    target.append(el("div", "branch-group", () => GitI18n.t(title) + " · " + group.length));
    for (const b of group) {
      const selected = state.branch?.ref === b.ref;
      const button = el("button", "branch" + (selected ? " selected" : ""));
      button.setAttribute("aria-current", selected ? "true" : "false");
      GitI18n.attr(button, "title", () => (b.detached ? GitI18n.t("游离 HEAD") : b.name) + (b.subject ? "\n" + GitI18n.format(b.subject) : ""));
      const top = el("span", "branch-top");
      const branchIcon = el("span", "branch-icon");
      branchIcon.append(window.GitUI.icon(b.detached ? "detached" : "branch"));
      top.append(branchIcon, el("span", "branch-name", () => b.detached ? GitI18n.t("游离 HEAD") : b.name));
      if (b.current) top.append(el("span", "badge current", () => GitI18n.t("当前")));
      button.append(top);
      const tracking = () => b.tracking.replace("[ahead ", GitI18n.t("领先 ")).replace(", behind ", GitI18n.t(" · 落后 ")).replace("[behind ", GitI18n.t("落后 ")).replace("[gone]", GitI18n.t("上游已删除")).replace("]", "");
      button.append(el("span", "branch-meta", () => [date(b.date), b.sha?.slice(0, 7), tracking()].filter(Boolean).join(" · ") || GitI18n.t("尚无提交")));
      button.addEventListener("click", () => selectBranch(b));
      target.append(button);
    }
  }
  if (!branches.length) empty(target, () => GitI18n.t("没有匹配的分支"), () => GitI18n.t("试试其他名称或分支类型"), true);
}
async function refresh(initialData = null) {
  const version = ++state.branchesVersion;
  $("refresh").disabled = true;
  clearError();
  try {
    const data = initialData || await api("branches");
    if (version !== state.branchesVersion) return;
    if (data.needs_repository) {
      showRepositoryPicker(data);
      return;
    }
    state.repository = data.repository;
    selectedRepository = data.repository.path;
    $("repo-input").value = selectedRepository;
    $("repo-picker").hidden = true;
    document.querySelector(".workspace").hidden = false;
    state.branches = data.branches;
    const repo = data.repository;
    if (repo.detached) state.branches.unshift({ref: repo.head, sha: repo.head, name: "HEAD",
      remote: false, current: true, detached: true, tracking: "", date: "", subject: ""});
    GitI18n.text($("repo-name"), () => repo.name);
    GitI18n.text(document.querySelector("title"), () => repo.name + GitI18n.t(" · Git 分支"));
    GitI18n.text($("repo-path"), () => repo.path);
    GitI18n.attr($("repo-path"), "title", () => repo.path);
    GitI18n.text($("branch-count"), () => data.branches.filter(b => !b.detached).length);
    const notes = [];
    if (repo.shallow) notes.push("这是浅克隆：仅展示本地已下载的历史。");
    if (repo.bare) notes.push("当前打开的是裸仓库。");
    GitI18n.text($("notice"), () => notes.map(key => GitI18n.t(key)).join(" "));
    $("notice").hidden = !notes.length;
    const selected = state.branches.find(b => b.ref === state.branch?.ref) ||
      state.branches.find(b => b.current) || state.branches[0];
    renderBranches();
    if (selected) selectBranch(selected);
    else {
      closeDetail();
      state.branch = null;
      state.historyVersion++;
      controllers.get("commits")?.abort();
      $("load-more").hidden = true;
      GitI18n.text($("branch-title"), () => GitI18n.t("尚无分支"));
      GitI18n.text($("history-status"), () => GitI18n.t("0 条提交"));
      empty($("commits"), () => GitI18n.t("仓库还没有提交"), () => GitI18n.t("创建首个提交后点击刷新。"));
    }
    document.dispatchEvent(new CustomEvent("git-repository-loaded"));
  } catch (err) { error(err); }
  finally { if (version === state.branchesVersion) $("refresh").disabled = false; }
}
function selectBranch(branch) {
  state.branch = branch;
  closeBranches();
  closeDetail();
  renderBranches();
  GitI18n.text($("branch-title"), () => branch.detached ? GitI18n.t("游离 HEAD") : branch.name);
  GitI18n.text($("branch-description"), () => branch.detached ? GitI18n.t("当前 HEAD 未指向分支") :
    (branch.remote ? GitI18n.t("远程跟踪分支") : GitI18n.t("本地分支")) +
    (branch.upstream ? GitI18n.t(" · 上游 ") + branch.upstream.replace("refs/remotes/", "").replace("refs/heads/", "") : "") +
    (branch.current ? GitI18n.t(" · 当前工作区") : ""));
  loadHistory();
  window.GitOperations?.updateBranchActions();
}
async function loadHistory(more = false) {
  if (!state.branch) return;
  const version = ++state.historyVersion;
  clearError();
  if (!more) {
    state.offset = 0; state.commits = []; state.snapshot = null; state.hasMore = false;
    $("load-more").hidden = true;
    closeDetail();
    empty($("commits"), () => GitI18n.t("正在读取提交…"));
  }
  const branch = state.branch;
  if (branch.unborn) {
    controllers.get("commits")?.abort();
    GitI18n.text($("history-status"), () => GitI18n.t("0 条提交"));
    empty($("commits"), () => GitI18n.t("这个分支还没有提交"), () => GitI18n.t("创建首个提交后点击刷新。"));
    return;
  }
  $("load-more").disabled = true;
  GitI18n.text($("history-status"), () => GitI18n.t("正在读取…"));
  try {
    const data = await api("commits", {ref: state.snapshot || branch.ref, offset: state.offset,
      limit: 50, ...state.filters});
    if (version !== state.historyVersion) return;
    state.snapshot = data.snapshot;
    state.offset = data.next_offset;
    state.hasMore = data.has_more;
    state.commits.push(...data.commits);
    renderCommits();
    $("load-more").hidden = !state.hasMore;
    GitI18n.text($("history-status"), () => GitI18n.t("已显示 ") + state.commits.length + GitI18n.t(" 条") +
      (state.hasMore ? GitI18n.t(" · 可继续加载") : GitI18n.t(" · 已到末尾")));
  } catch (err) {
    if (version === state.historyVersion && err.name !== "AbortError") {
      error(err);
      GitI18n.text($("history-status"), () => GitI18n.t("读取失败"));
      if (!more) empty($("commits"), () => GitI18n.t("暂时无法读取提交"), () => GitI18n.t("点击刷新重试。"));
    }
  } finally {
    if (version === state.historyVersion) $("load-more").disabled = false;
  }
}
function renderCommits() {
  const target = $("commits");
  target.replaceChildren();
  if (!state.commits.length) {
    empty(target, () => GitI18n.t("没有找到提交"), () => GitI18n.t("调整提交信息或作者筛选后再试。"));
    return;
  }
  for (const c of state.commits) {
    const button = el("button", "commit" + (c.parents.length > 1 ? " merge" : "") +
      (state.detail?.sha === c.sha ? " selected" : ""));
    button.dataset.sha = c.sha;
    const timestamp = c.committed_date || c.date;
    const statsLabel = () => c.stats ? GitI18n.t("新增 {added} 行，删除 {deleted} 行", {added: c.stats.additions, deleted: c.stats.deletions}) +
      (c.stats.binary_files ? GitI18n.t("，另有 ") + c.stats.binary_files + GitI18n.t(" 个二进制文件") : "") : GitI18n.t("行数统计暂不可用");
    GitI18n.attr(button, "aria-label", () => c.subject + GitI18n.t("，") + c.author + GitI18n.t("，") + c.sha.slice(0, 7) +
      GitI18n.t("，提交于 ") + exactDate(timestamp) + GitI18n.t("，") + statsLabel());
    button.append(el("span", "commit-title", () => c.subject || GitI18n.t("（无提交标题）")));
    const meta = el("span", "commit-meta");
    meta.append(el("span", "avatar", () => Array.from(c.author)[0]?.toUpperCase() || "?"),
      el("span", "", () => c.author), el("code", "", () => c.sha.slice(0, 7)));
    if (c.parents.length > 1) meta.append(el("span", "badge", () => GitI18n.t("合并")));
    const trailing = el("span", "commit-trailing");
    const stats = el("span", "commit-stats");
    GitI18n.attr(stats, "title", () => statsLabel() + (c.stats ? GitI18n.t("；") + (c.parents.length ? GitI18n.t("相对第一父提交") : GitI18n.t("根提交，相对空目录")) +
      (c.stats.binary_files ? GitI18n.t("；二进制文件不计入行数") : "") : c.stats_error ? GitI18n.t("：") + GitI18n.format(c.stats_error) : ""));
    if (c.stats) {
      stats.append(el("span", "additions", () => "+" + c.stats.additions.toLocaleString(GitI18n.locale)),
        el("span", "deletions", () => "−" + c.stats.deletions.toLocaleString(GitI18n.locale)));
      if (c.stats.binary_files) stats.append(el("span", "binary-count", () => GitI18n.t("二进制 × ") + c.stats.binary_files));
    } else GitI18n.text(stats, () => GitI18n.t("统计暂不可用"));
    const when = el("time", "when", () => date(timestamp, true));
    when.dateTime = timestamp;
    GitI18n.attr(when, "title", () => GitI18n.t("提交时间（本地时区）：") + exactDate(timestamp));
    trailing.append(stats, when);
    meta.append(trailing); button.append(meta);
    button.addEventListener("click", () => selectCommit(c.sha));
    target.append(button);
  }
}
function closeDetail() {
  state.detailVersion++; state.patchVersion++;
  controllers.get("commit")?.abort(); controllers.get("patch")?.abort();
  state.detail = null;
  $("detail").hidden = true;
  document.body.classList.remove("has-detail");
  for (const row of $("commits").children) row.classList.remove("selected");
}
async function selectCommit(sha, parent = 0) {
  const version = ++state.detailVersion;
  state.patchVersion++;
  controllers.get("patch")?.abort();
  clearError();
  $("detail").hidden = false;
  document.body.classList.add("has-detail");
  $("file-section").hidden = true;
  $("patch-section").hidden = true;
  empty($("commit-detail"), () => GitI18n.t("正在读取提交详情…"));
  for (const row of $("commits").children) row.classList.toggle("selected", row.dataset.sha === sha);
  try {
    const c = await api("commit", {sha, parent});
    if (version !== state.detailVersion) return;
    state.detail = c;
    renderDetail(c);
    if (c.files.length) selectFile(c.files[0].path);
  } catch (err) {
    if (version === state.detailVersion && err.name !== "AbortError") {
      error(err);
      empty($("commit-detail"), () => GitI18n.t("无法读取提交"), () => GitI18n.t("请返回列表，刷新后重试。"));
    }
  }
}
function renderDetail(c) {
  const target = $("commit-detail");
  target.replaceChildren(el("h2", "detail-title", () => c.subject || GitI18n.t("（无提交标题）")));
  const shaRow = el("div", "sha-row");
  shaRow.append(el("code", "", () => c.sha));
  const copy = el("button", "button", () => GitI18n.t("复制"));
  copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(c.sha); GitI18n.text(copy, () => GitI18n.t("已复制")); }
    catch { GitI18n.text(copy, () => GitI18n.t("请手动选中复制")); }
  });
  shaRow.append(copy); target.append(shaRow);
  const meta = el("div", "detail-meta");
  meta.append(el("div", "", () => c.author + " <" + c.email + ">"),
    el("div", "", () => GitI18n.t("编写于 ") + date(c.date, true)));
  if (c.date !== c.committed_date) meta.append(el("div", "", () => GitI18n.t("提交于 ") + date(c.committed_date, true)));
  target.append(meta);
  const messageBody = c.message.startsWith(c.subject) ? c.message.slice(c.subject.length).trim() : c.message;
  if (messageBody) target.append(el("p", "message", () => messageBody));
  if (c.parents.length > 1) {
    const label = el("label", "parent-picker", () => GitI18n.t("合并提交 · 对比父提交"));
    const select = el("select");
    GitI18n.attr(select, "aria-label", () => GitI18n.t("选择对比父提交"));
    c.parents.forEach((p, i) => {
      const option = el("option", "", () => GitI18n.t("父提交 ") + (i + 1) + " · " + p.slice(0, 12));
      option.value = i; option.selected = i === c.parent_index; select.append(option);
    });
    select.addEventListener("change", () => selectCommit(c.sha, Number(select.value)));
    label.append(select); target.append(label);
    window.GitUI.enhance(select);
  } else target.append(el("p", "detail-meta", () => c.parents.length ?
    GitI18n.t("对比父提交 ") + c.parents[0].slice(0, 12) : GitI18n.t("根提交 · 对比空目录")));
  window.GitOperations?.addRevertButton(target, c);
  $("file-section").hidden = false;
  GitI18n.text($("file-count"), () => c.files.length);
  $("files").replaceChildren();
  for (const file of c.files) {
    const button = el("button", "file");
    button.dataset.path = file.path;
    button.append(el("span", "file-status " + (file.status === "A" ? "add" : file.status === "D" ? "del" : ""), () => file.status),
      el("code", "", () => file.path));
    button.addEventListener("click", () => selectFile(file.path));
    $("files").append(button);
  }
  if (!c.files.length) empty($("files"), () => GitI18n.t("没有文件改动"), () => GitI18n.t("此提交相对所选父提交没有差异。"), true);
}
async function selectFile(path) {
  const c = state.detail;
  if (!c) return;
  const version = ++state.patchVersion;
  $("patch-section").hidden = false;
  $("patch-notice").hidden = true;
  GitI18n.text($("patch-path"), () => path);
  GitI18n.text($("patch-stats"), () => "");
  GitI18n.text($("patch"), () => GitI18n.t("正在读取差异…"));
  for (const row of $("files").children) row.classList.toggle("active", row.dataset.path === path);
  try {
    const data = await api("patch", {sha: c.sha, path, parent: c.parent_index});
    if (version !== state.patchVersion) return;
    let added = 0, deleted = 0;
    const frag = document.createDocumentFragment();
    for (const line of data.patch.split("\n")) {
      let cls = "";
      if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff ") ||
          line.startsWith("index ")) cls = "meta";
      else if (line.startsWith("+")) { cls = "add"; added++; }
      else if (line.startsWith("-")) { cls = "del"; deleted++; }
      else if (line.startsWith("@@")) cls = "hunk";
      frag.append(el("span", "diff-line " + cls, () => line || " "));
    }
    $("patch").replaceChildren(frag);
    GitI18n.text($("patch-stats"), () => "+" + added + "  −" + deleted);
    if (data.truncated) {
      GitI18n.text($("patch-notice"), () => GitI18n.t("差异较大，仅展示前 800 KB；增删行数仅统计已展示部分。"));
      $("patch-notice").hidden = false;
    } else if (!data.patch) GitI18n.text($("patch"), () => GitI18n.t("此文件没有可显示的文本差异。"));
  } catch (err) {
    if (version === state.patchVersion && err.name !== "AbortError") {
      GitI18n.text($("patch"), () => GitI18n.t("差异读取失败。")); error(err);
    }
  }
}
$("branch-search").addEventListener("input", renderBranches);
document.querySelectorAll("[data-kind]").forEach(button => button.addEventListener("click", () => {
  state.kind = button.dataset.kind;
  document.querySelectorAll("[data-kind]").forEach(b => {
    b.classList.toggle("active", b === button);
    b.setAttribute("aria-pressed", b === button ? "true" : "false");
  });
  renderBranches();
}));
// Use explicit button/keyboard handlers: MCP sandboxes may disable native forms.
function bindForm(form, button, action) {
  button.addEventListener("click", action);
  form.addEventListener("submit", event => { event.preventDefault(); action(); });
  form.addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.isComposing && event.target.matches("input:not([type=checkbox])")) {
      event.preventDefault(); action();
    }
  });
}
function applyFilters() {
  state.filters = {query: $("commit-search").value.trim(), author: $("author-search").value.trim(),
    first_parent: $("first-parent").checked};
  loadHistory();
}
bindForm($("filters"), $("search-commits"), applyFilters);
$("first-parent").addEventListener("change", applyFilters);
$("clear-filters").addEventListener("click", () => {
  $("filters").reset(); state.filters = {query: "", author: "", first_parent: false}; loadHistory();
});
$("refresh").addEventListener("click", () => refresh());
$("load-more").addEventListener("click", () => loadHistory(true));
$("close-detail").addEventListener("click", () => {
  const sha = state.detail?.sha; closeDetail();
  const row = [...$("commits").children].find(c => c.dataset.sha === sha); row?.focus();
});
$("toggle-branches").addEventListener("click", () => {
  const open = !document.body.classList.contains("branches-open");
  document.body.classList.toggle("branches-open", open);
  $("scrim").hidden = !open;
  $("toggle-branches").setAttribute("aria-expanded", String(open));
  $("sidebar").inert = !open && matchMedia("(max-width:760px)").matches;
  if (open) $("branch-search").focus();
});
$("scrim").addEventListener("click", closeBranches);
document.addEventListener("keydown", event => {
  if (event.key !== "Escape") return;
  if (document.body.classList.contains("branches-open")) closeBranches(); else closeDetail();
});
matchMedia("(max-width:760px)").addEventListener("change", closeBranches);
$("stop").addEventListener("click", async () => {
  try {
    await api("stop", {}, "stop", "POST");
    for (const controller of controllers.values()) controller.abort();
    document.body.replaceChildren(el("div", "empty", () => GitI18n.t("浏览会话已停止。可在 Codex 中重新打开 Git 分支浏览器。")));
  } catch (err) { error(err); }
});
closeBranches();
function renderRepositoryContext(context) {
  const checks = $("repo-context-checks"), paths = $("repo-context-paths");
  checks.replaceChildren(); paths.replaceChildren();
  checks.hidden = !context;
  paths.hidden = !context?.paths?.length;
  $("recheck-context").hidden = !context;
  $("repo-manual-divider").hidden = !context;
  $("open-repo").classList.toggle("primary", !context);
  if (!context) {
    GitI18n.text($("repo-picker-title"), () => GitI18n.t("打开 Git 仓库"));
    return;
  }
  const message = context.message_status, repository = context.repository_status;
  GitI18n.text($("repo-picker-title"), () => repository === "not_found" ? GitI18n.t("当前项目未检测到 Git 仓库") :
    repository === "unavailable" ? GitI18n.t("暂时无法检查 Git 仓库") :
    repository === "multiple" ? GitI18n.t("选择当前项目的 Git 仓库") :
    message === "sent" ? GitI18n.t("暂未识别当前项目目录") :
    message === "not_sent" ? GitI18n.t("请先发送一条消息") : GitI18n.t("先确认任务已发送消息"));
  function step(number, title, value, description, status) {
    const row = el("div", "context-step");
    row.dataset.status = status;
    const content = el("div", "context-step-content");
    content.append(el("strong", "", () => title), el("p", "", () => description));
    row.append(el("span", "context-step-number", () => String(number)), content,
      el("span", "context-step-value", () => value));
    checks.append(row);
  }
  step(1, () => GitI18n.t("任务消息"), () => message === "sent" ? GitI18n.t("已发送") : message === "not_sent" ? GitI18n.t("尚未发送") : GitI18n.t("待确认"),
    () => message === "sent" ? GitI18n.t("已检测到当前任务的用户消息。") :
    message === "not_sent" ? GitI18n.t("请先发送一条消息，再关闭并重新打开「Git 分支」。") :
    GitI18n.t("若还没发过消息，请先发送；若已经发送，请关闭并重新打开「Git 分支」。"),
    message === "sent" ? "done" : "pending");
  step(2, () => GitI18n.t("项目 Git 仓库"), () => repository === "not_found" ? GitI18n.t("未检测到") :
    repository === "unavailable" ? GitI18n.t("检查失败") : repository === "multiple" ? GitI18n.t("已找到多个") : GitI18n.t("待检查"),
    () => repository === "not_found" ? GitI18n.t("已检查下方目录，未检测到 Git 仓库。") :
    repository === "unavailable" ? context.error || GitI18n.t("暂时无法读取项目，请重新检查或手动选择仓库。") :
    repository === "multiple" ? GitI18n.t("从下方列表选择要查看的仓库。") : GitI18n.t("取得当前项目目录后，会自动检查 Git 仓库。"),
    repository === "multiple" ? "done" : repository === "pending" ? "pending" : "problem");
  if (context.paths?.length) {
    paths.append(el("span", "", () => GitI18n.t("检查目录")));
    for (const path of context.paths) paths.append(el("code", "", () => path));
  }
}
function showRepositoryPicker(data = null) {
  renderRepositoryContext(data?.context);
  GitI18n.text($("repo-picker-message"), () => data?.reason || GitI18n.t("输入本地仓库的完整路径，查看分支和提交记录。"));
  const candidates = $("repo-candidates");
  candidates.replaceChildren();
  for (const repo of data?.repositories || []) {
    const button = el("button", "button", () => repo.name);
    button.type = "button";
    GitI18n.attr(button, "title", () => repo.path);
    button.append(el("span", "muted", () => repo.path));
    button.addEventListener("click", () => openRepository(repo.path));
    candidates.append(button);
  }
  candidates.hidden = !candidates.children.length;
  if (!state.repository) {
    GitI18n.text($("repo-name"), () => GitI18n.t("选择仓库"));
    $("repo-input").value = data?.suggested_path || "";
    document.querySelector(".workspace").hidden = true;
  }
  $("repo-picker").hidden = false;
  $("cancel-repo").hidden = !state.repository;
  if (data?.context) $("recheck-context").focus(); else $("repo-input").focus();
}
$("recheck-context").addEventListener("click", async () => {
  $("recheck-context").disabled = true;
  try { await refresh(); } finally { $("recheck-context").disabled = false; }
});
$("choose-repo").addEventListener("click", () => showRepositoryPicker());
$("cancel-repo").addEventListener("click", () => {
  $("repo-picker").hidden = true;
  clearError(); $("choose-repo").focus();
});
async function openRepository(path) {
  if (!path || $("open-repo").disabled) return;
  $("open-repo").disabled = true;
  for (const button of $("repo-candidates").children) button.disabled = true;
  clearError();
  try {
    const data = await nativeHost.query("branches", {repo: path});
    // Discard any in-flight results from the previously selected repository.
    for (const controller of controllers.values()) controller.abort();
    state.historyVersion++; state.detailVersion++; state.patchVersion++;
    state.branch = null; closeDetail();
    await refresh(data);
  } catch (err) { error(err); }
  finally {
    $("open-repo").disabled = false;
    for (const button of $("repo-candidates").children) button.disabled = false;
  }
}
bindForm($("repo-picker"), $("open-repo"), () => openRepository($("repo-input").value.trim()));
async function initialize() {
  if (!nativeHost) { await refresh(); return; }
  $("stop").hidden = true;
  $("choose-repo").hidden = false;
  // Native mode follows Codex's theme by default, independent of browser preferences.
  $("theme").value = "auto";
  try {
    await nativeHost.ready;
    setTheme();
    const data = nativeHost.unpack(await nativeHost.initial);
    await refresh(data);
  } catch (err) { error(err); showRepositoryPicker(); }
}
initialize();
