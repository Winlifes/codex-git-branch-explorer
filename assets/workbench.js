"use strict";
window.GitWorkbench = (() => {
  let mode = "history", fullDiff = null;
  const workspace = document.querySelector(".workspace"), history = document.querySelector(".history");
  function view(next) {
    mode = next;
    document.body.dataset.view = mode;
    history.hidden = mode !== "history";
    $("work-dialog").hidden = mode !== "workspace";
    $("stashes-pane").hidden = mode !== "stashes";
    $("detail").hidden = mode !== "history" || !state.detail;
    $("resize-detail").hidden = mode !== "history" || !state.detail;
    for (const button of document.querySelectorAll("[data-view]")) {
      const active = button.dataset.view === mode;
      button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active));
    }
    if (mode === "history") GitI18n.text($("status-selection"), () => "");
    if (mode === "stashes") { GitI18n.text($("status-selection"), () => ""); window.GitStashes?.load(); }
  }
  $("history-tab").addEventListener("click", () => view("history"));
  $("stashes-tab").addEventListener("click", () => view("stashes"));
  document.querySelector(".commit-scroll").addEventListener("scroll", event => {
    document.querySelector(".commit-columns").style.transform = `translateX(${-event.target.scrollLeft}px)`;
  });
  document.addEventListener("git-workspace-status", event => {
    const data = event.detail;
    GitI18n.text($("status-branch"), () => data.repository.current_ref?.replace(/^refs\/heads\//, "") || GitI18n.t("游离 HEAD"));
    const timestamp = new Date();
    GitI18n.text($("status-updated"), () => GitI18n.t("更新于 ") + new Intl.DateTimeFormat(GitI18n.locale,
      {hour: "2-digit", minute: "2-digit", hourCycle: "h23"}).format(timestamp));
  });
  const sizes = {sidebar: {min: 190, max: 380, fallback: 240}, detail: {min: 300, max: 620, fallback: 370}};
  for (const [pane, limits] of Object.entries(sizes)) {
    const handle = $("resize-" + pane);
    let size = limits.fallback;
    try { size = Number(localStorage.getItem("git-pane-" + pane)) || size; } catch {}
    const resize = value => {
      size = Math.round(Math.max(limits.min, Math.min(limits.max, value)));
      workspace.style.setProperty("--" + pane + "-width", size + "px");
      handle.setAttribute("aria-valuenow", size); handle.setAttribute("aria-valuemin", limits.min); handle.setAttribute("aria-valuemax", limits.max);
    };
    const remember = () => { try { localStorage.setItem("git-pane-" + pane, String(size)); } catch {} };
    resize(size);
    handle.addEventListener("pointerdown", event => {
      event.preventDefault(); handle.setPointerCapture(event.pointerId);
      workspace.classList.add("resizing");
      const start = event.clientX, original = size;
      const move = next => resize(original + (next.clientX - start) * (pane === "detail" ? -1 : 1));
      const end = () => { workspace.classList.remove("resizing"); handle.removeEventListener("pointermove", move); remember(); };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("lostpointercapture", end, {once: true});
      handle.addEventListener("pointerup", next => handle.releasePointerCapture(next.pointerId), {once: true});
    });
    handle.addEventListener("keydown", event => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault(); resize(size + (event.key === "ArrowRight" ? 16 : -16) * (pane === "detail" ? -1 : 1)); remember();
    });
  }
  $("commits").addEventListener("keydown", event => {
    if (event.isComposing || event.metaKey || event.ctrlKey || !["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
    const rows = [...$("commits").querySelectorAll("button.commit")];
    const index = rows.indexOf(event.target.closest("button.commit"));
    if (index < 0) return;
    event.preventDefault();
    const next = rows[event.key === "Home" ? 0 : event.key === "End" ? rows.length - 1 :
      Math.max(0, Math.min(rows.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)))];
    next.focus({preventScroll: true}); next.scrollIntoView({block: "nearest"}); next.click();
  });
  document.addEventListener("keydown", event => {
    if (document.querySelector("dialog[open]") || event.isComposing) return;
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "f") {
      event.preventDefault(); view("history"); $("commit-search").focus(); $("commit-search").select();
    } else if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && mode === "workspace") {
      event.preventDefault(); if (!$("prepare-commit").disabled) $("prepare-commit").click();
    } else if (event.key === "F5") { event.preventDefault(); refresh(); }
  });
  $("expand-diff").addEventListener("click", () => {
    if (!fullDiff) return;
    GitI18n.text($("full-diff-path"), () => fullDiff.path);
    GitDiffView.render($("full-diff"), fullDiff.data);
    $("diff-dialog").showModal();
  });
  $("close-full-diff").addEventListener("click", () => $("diff-dialog").close());
  $("diff-dialog").addEventListener("keydown", event => { if (event.key === "Escape") event.stopPropagation(); });
  view("history");
  return {view, setDiff(path, data) { fullDiff = {path, data}; }};
})();
