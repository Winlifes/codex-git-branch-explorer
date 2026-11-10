"use strict";
// Bootstrap is only available in the native panel, for an explicit project.
window.GitGithub = (() => {
  const dialog = $("github-dialog"), content = $("github-content"), confirm = $("confirm-github");
  let project = "", version = 0, busy = false, preview = null, job = null, submit = null;
  let returnFocus = null;
  const templates = {existing: "仅使用现有规则", common: "通用", unity: "Unity", node: "Node.js", python: "Python"};
  function context(data) {
    const available = Boolean(nativeHost && !state.repository && data?.context?.repository_status === "not_found");
    $("github-start").hidden = !available;
    $("recheck-context").classList.toggle("primary", !available);
  }
  function showError(error) {
    GitI18n.text($("github-error"), () => error.message);
    $("github-error").hidden = false;
  }
  function field(label, node, identifier) {
    node.id = "github-" + identifier;
    const wrapper = el("label", "operation-field", () => label);
    wrapper.htmlFor = node.id; wrapper.append(node); content.append(wrapper);
    return node;
  }
  function input(label, value, identifier, length) {
    const node = el("input"); node.type = "text"; node.value = value; node.maxLength = length;
    node.autocomplete = "off"; node.spellcheck = false;
    return field(label, node, identifier);
  }
  function checkbox(label, checked, identifier) {
    const node = el("input"); node.type = "checkbox"; node.checked = checked; node.id = "github-" + identifier;
    const wrapper = el("label", "operation-checkbox"); wrapper.append(node, el("span", "", () => label));
    content.append(wrapper); return node;
  }
  function controls(running) {
    $("close-github").disabled = running;
    $("cancel-github").disabled = running;
  }
  function close() {
    if (busy) return;
    version++; preview = null; submit = null; job = null;
    dialog.close(); returnFocus?.focus();
  }
  function link(label, url) {
    const anchor = el("a", "github-link", () => label);
    anchor.href = url; anchor.target = "_blank"; anchor.rel = "noopener noreferrer";
    anchor.addEventListener("click", event => {
      event.preventDefault();
      nativeHost.request("ui/open-link", {url}).catch(showError);
    });
    return anchor;
  }
  async function inspect() {
    const turn = ++version;
    preview = null; submit = null; confirm.disabled = true;
    content.replaceChildren(el("p", "muted", () => GitI18n.t("正在检查 GitHub 账号…")));
    $("github-error").hidden = true;
    try {
      const data = await nativeHost.operation("github_project", {project, action: "inspect"});
      if (!dialog.open || turn !== version) return;
      content.replaceChildren();
      if (!data.ready) {
        content.append(el("p", "operation-description", () => data.message));
        const command = data.auth_state === "gh_missing" ? data.install_command : data.login_command;
        content.append(el("code", "github-command", () => command));
        content.append(el("p", "muted", () => GitI18n.t("完成安装或登录后重新检查。账号凭据由 GitHub CLI 管理。")));
        content.append(link(() => GitI18n.t("GitHub CLI 安装与登录说明"), data.auth_state === "gh_missing" ? "https://cli.github.com/" : "https://cli.github.com/manual/gh_auth_login"));
        GitI18n.text(confirm, () => GitI18n.t("重新检查账号"));
        confirm.disabled = false; submit = inspect; return;
      }
      renderForm(data);
    } catch (error) {
      if (turn !== version) return;
      content.replaceChildren(); showError(error);
      GitI18n.text(confirm, () => GitI18n.t("重新检查账号"));
      confirm.disabled = false; submit = inspect;
    }
  }
  function renderForm(data, draft = {}) {
    const account = el("div", "github-account");
    account.append(el("span", "muted", () => GitI18n.t("当前 GitHub 账号")),
      el("strong", "", () => data.account.login), el("span", "muted", () => data.account.name));
    content.append(account);
    const checkAccount = checkbox(() => GitI18n.t("确认使用账号 {account} 创建仓库", {account: data.account.login}), false, "account-confirmed");
    const switcher = el("details", "github-account-help");
    switcher.append(el("summary", "", () => GitI18n.t("需要更换账号？")),
      el("p", "muted", () => GitI18n.t("在终端切换或登录另一个 GitHub CLI 账号，再重新检查。")),
      el("code", "github-command", () => data.switch_command));
    const recheck = el("button", "button", () => GitI18n.t("重新检查账号")); recheck.type = "button";
    recheck.addEventListener("click", inspect); switcher.append(recheck); content.append(switcher);
    const name = input(() => GitI18n.t("仓库名称"), draft.name ?? data.suggested_name, "name", 100);
    const description = input(() => GitI18n.t("描述（可选）"), draft.description ?? "", "description", 350);
    const visibility = el("fieldset", "github-visibility");
    visibility.append(el("legend", "", () => GitI18n.t("仓库可见性")));
    let privateRadio;
    for (const value of ["private", "public"]) {
      const wrapper = el("label", "github-visibility-option");
      const radio = el("input"); radio.type = "radio"; radio.name = "github-visibility"; radio.value = value; radio.checked = value === (draft.visibility ?? "private");
      const text = el("span");
      text.append(el("strong", "", () => GitI18n.t(value === "private" ? "私有" : "公开")),
        el("span", "muted", () => GitI18n.t(value === "private" ? "仅你和授权成员可访问" : "任何人都能查看上传的内容")));
      wrapper.append(radio, text); visibility.append(wrapper);
      if (value === "private") privateRadio = radio;
    }
    content.append(visibility);
    const branch = input(() => GitI18n.t("初始分支"), draft.branch ?? "main", "branch", 240);
    const ignore = el("select");
    for (const [value, text] of Object.entries(templates)) {
      const option = el("option", "", () => GitI18n.t(text)); option.value = value; ignore.append(option);
    }
    ignore.value = draft.template ?? data.suggested_template;
    field(() => GitI18n.t("忽略规则"), ignore, "template"); GitUI.enhance(ignore);
    content.append(el("p", "muted", () => GitI18n.t("保留现有 .gitignore。所选模板补充生成文件、缓存和常见凭据文件的忽略规则。")));
    const upload = checkbox(() => GitI18n.t("创建首次提交并上传项目文件"), draft.upload ?? true, "upload");
    const message = input(() => GitI18n.t("首次提交说明"), draft.message ?? "Initial commit", "message", 10000);
    content.append(el("p", "muted", () => GitI18n.t("取消首次上传时，只初始化本地 Git、创建空仓库并连接 origin。")));
    GitI18n.text(confirm, () => GitI18n.t("预览创建"));
    const validity = () => { message.disabled = !upload.checked; confirm.disabled = !checkAccount.checked || !name.value.trim() || !branch.value.trim() || (upload.checked && !message.value.trim()); };
    for (const node of [checkAccount, name, branch, upload, message]) { node.addEventListener("input", validity); node.addEventListener("change", validity); }
    validity();
    submit = () => prepare({name: name.value.trim(), description: description.value.trim(), visibility: privateRadio.checked ? "private" : "public",
      branch: branch.value.trim(), template: ignore.value, upload: upload.checked, message: message.value,
      account: data.account.login, account_confirmed: checkAccount.checked}, data);
    name.focus();
  }
  async function prepare(settings, data) {
    const turn = ++version;
    confirm.disabled = true; $("github-error").hidden = true;
    GitI18n.text(confirm, () => GitI18n.t("正在检查…"));
    try {
      const result = await nativeHost.operation("github_prepare", {project, ...settings});
      if (!dialog.open || turn !== version) return;
      preview = result; content.replaceChildren();
      GitI18n.text($("github-title"), () => result.title);
      const badge = el("div", "github-preview-target"); badge.dataset.visibility = result.visibility;
      badge.append(el("strong", "", () => result.full_name), el("span", "", () => GitI18n.t(result.visibility === "private" ? "私有" : "公开")));
      content.append(badge);
      for (const text of result.details) content.append(el("p", "operation-description", () => text));
      if (result.files.length) {
        content.append(el("p", "muted", () => GitI18n.t("首次上传：{count} 个文件，约 {size} MiB", {count: result.files.length, size: (result.bytes / 1048576).toFixed(2)})));
        const list = el("div", "operation-files");
        for (const path of result.files) list.append(el("code", "", () => path));
        content.append(list);
      }
      if (result.excluded.length) {
        const excluded = el("details", "github-excluded");
        excluded.append(el("summary", "", () => GitI18n.t("本次不上传的文件：{count}", {count: result.excluded.length})));
        for (const file of result.excluded) excluded.append(el("code", "", () => file.path + " · " + GitI18n.format(file.reason)));
        content.append(excluded);
      }
      const back = el("button", "button", () => GitI18n.t("返回修改选项")); back.type = "button";
      back.addEventListener("click", () => { version++; preview = null; content.replaceChildren(); GitI18n.text($("github-title"), () => GitI18n.t("创建 GitHub 仓库")); renderForm(data, settings); });
      content.append(back);
      GitI18n.text(confirm, () => GitI18n.t(result.upload ? "确认创建并上传" : "确认创建空仓库"));
      confirm.disabled = false; submit = execute;
      if (result.visibility === "public") {
        const acknowledge = checkbox(() => GitI18n.t("我已确认以上文件可以公开"), false, "public-confirmed");
        confirm.disabled = true;
        acknowledge.addEventListener("change", () => { confirm.disabled = !acknowledge.checked; });
      }
      $("cancel-github").focus();
    } catch (error) {
      if (turn !== version) return;
      showError(error); GitI18n.text(confirm, () => GitI18n.t("预览创建")); confirm.disabled = false;
    }
  }
  function renderProgress(data) {
    content.replaceChildren();
    const status = el("p", "github-job-state", () => data.message); status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
    content.append(status);
    const steps = el("ol", "github-job-steps");
    for (const step of data.steps) steps.append(el("li", "", () => step));
    content.append(steps);
    if (data.url) content.append(link(() => GitI18n.t("查看 GitHub 仓库"), data.url), el("code", "github-command", () => data.url));
    if (data.recovery) content.append(el("p", "operation-description", () => data.recovery));
    if (data.remote_state === "unknown") content.append(el("p", "operation-description", () => GitI18n.t("GitHub 创建结果待确认，请先到 GitHub 检查是否已存在同名仓库。")));
  }
  async function poll() {
    if (!job) return;
    const identifier = job;
    try {
      const data = await nativeHost.operation("github_project", {project, action: "progress", job: identifier});
      if (identifier !== job || !dialog.open) return;
      renderProgress(data);
      if (data.state === "running") { setTimeout(poll, 1000); return; }
      busy = false; controls(false); confirm.disabled = false;
      GitI18n.text(confirm, () => GitI18n.t(data.local_initialized ? "打开本地仓库" : "重新检查账号"));
      GitI18n.text($("cancel-github"), () => GitI18n.t("关闭"));
      submit = data.local_initialized ? async () => { close(); await openRepository(project); } : inspect;
      if (data.state === "succeeded") {
        await nativeHost.query("branches", {repo: project}).then(refresh).catch(showError);
      }
    } catch (error) {
      if (identifier !== job || !dialog.open) return;
      busy = false; controls(false); showError(error);
      content.append(el("p", "operation-description", () => GitI18n.t("进度查询失败，创建可能仍在进行；可重新查询，不会重复执行创建。")));
      GitI18n.text(confirm, () => GitI18n.t("重新查询进度")); confirm.disabled = false;
      submit = () => { busy = true; controls(true); confirm.disabled = true; poll(); };
    }
  }
  async function execute() {
    if (!preview || busy) return;
    const chosen = preview; preview = null; submit = null;
    busy = true; controls(true); confirm.disabled = true; $("github-error").hidden = true;
    GitI18n.text(confirm, () => GitI18n.t("正在创建…"));
    try {
      const data = await nativeHost.operation("github_apply", {project, token: chosen.token});
      job = data.job; renderProgress(data); poll();
    } catch (error) {
      busy = false; controls(false); showError(error);
      content.replaceChildren(el("p", "operation-description", () => GitI18n.t("请先检查本地与 GitHub 状态；不会自动重复创建。")));
      GitI18n.text(confirm, () => GitI18n.t("重新检查账号")); confirm.disabled = false; submit = inspect;
    }
  }
  async function open() {
    if (!nativeHost || busy) return;
    project = $("repo-input").value.trim();
    if (!project) { $("repo-input").focus(); return; }
    returnFocus = document.activeElement; preview = null; job = null;
    GitUI.closeMenus(); content.replaceChildren(); controls(false);
    GitI18n.text($("github-title"), () => GitI18n.t("创建 GitHub 仓库"));
    GitI18n.text($("github-project-path"), () => project);
    GitI18n.text($("cancel-github"), () => GitI18n.t("取消"));
    dialog.showModal(); await inspect();
  }
  $("create-github").addEventListener("click", open);
  $("close-github").addEventListener("click", close);
  $("cancel-github").addEventListener("click", close);
  confirm.addEventListener("click", () => { if (!confirm.disabled) submit?.(); });
  dialog.addEventListener("cancel", event => { event.preventDefault(); close(); });
  return {context, open};
})();
