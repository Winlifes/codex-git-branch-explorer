"use strict";
// Shared, host-themed controls. Hidden selects remain the value/event model;
// their platform-native popup is never opened.
window.GitUI = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const paths = {
    branch: [['circle', {cx:6,cy:5,r:2.5}], ['circle', {cx:6,cy:19,r:2.5}], ['circle', {cx:18,cy:6,r:2.5}], ['path', {d:'M6 7.5v9M18 8.5v1A6.5 6.5 0 0 1 11.5 16H6'}]],
    detached: [['circle',{cx:12,cy:12,r:8}],['circle',{cx:12,cy:12,r:2}]],
    merge: [['circle',{cx:6,cy:5,r:2}],['circle',{cx:6,cy:19,r:2}],['circle',{cx:18,cy:5,r:2}],['path',{d:'M6 7v10M18 7v2a6 6 0 0 1-6 6H6'}]],
    switch: [['path',{d:'M4 7h15m-4-4 4 4-4 4M20 17H5m4-4-4 4 4 4'}]],
    trash: [['path',{d:'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7'}]],
    check: [['path',{d:'m5 12 4 4L19 6'}]],
    chevron: [['path',{d:'m7 10 5 5 5-5'}]],
    plus: [['path',{d:'M12 5v14M5 12h14'}]],
    minus: [['path',{d:'M5 12h14'}]],
    refresh: [['path',{d:'M20 7v5h-5M4 17v-5h5M19 11a7 7 0 0 0-12-5L4 9m1 4a7 7 0 0 0 12 5l3-3'}]],
    undo: [['path',{d:'m9 4-5 5 5 5M4 9h10a6 6 0 0 1 0 12h-3'}]],
    'arrow-up': [['path',{d:'M12 20V4m-6 6 6-6 6 6'}]],
    'arrow-down': [['path',{d:'M12 4v16m-6-6 6 6 6-6'}]],
    'arrow-left': [['path',{d:'M20 12H4m6-6-6 6 6 6'}]],
    download: [['path',{d:'M12 3v12m-5-5 5 5 5-5M4 16v4h16v-4'}]],
    close: [['path',{d:'m6 6 12 12M6 18 18 6'}]],
    power: [['path',{d:'M12 3v9M6.3 5.8a8 8 0 1 0 11.4 0'}]],
    panel: [['rect',{x:3,y:4,width:18,height:16,rx:2}],['path',{d:'M9 4v16'}]],
    monitor: [['rect',{x:3,y:4,width:18,height:13,rx:2}],['path',{d:'M8 21h8M12 17v4'}]],
    moon: [['path',{d:'M20.5 13A8.5 8.5 0 0 1 11 3.5 8.5 8.5 0 1 0 20.5 13Z'}]],
    sun: [['circle',{cx:12,cy:12,r:4}],['path',{d:'M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5'}]],
  };
  function icon(name, className = "ui-icon") {
    const svg = document.createElementNS(NS, "svg");
    const attrs = {viewBox:"0 0 24 24", width:16, height:16, fill:"none", stroke:"currentColor",
      "stroke-width":1.65, "stroke-linecap":"round", "stroke-linejoin":"round", "aria-hidden":"true", focusable:"false", class:className};
    for (const [key, value] of Object.entries(attrs)) svg.setAttribute(key, value);
    for (const [tag, attrs] of paths[name] || paths.branch) {
      const child = document.createElementNS(NS, tag);
      for (const [key, value] of Object.entries(attrs)) child.setAttribute(key, value);
      svg.append(child);
    }
    return svg;
  }
  function node(tag, cls, text) {
    const n = document.createElement(tag); n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  const controls = new WeakMap();
  let active = null, nextId = 0;
  class SelectControl {
    constructor(source) {
      this.source = source;
      this.menu = source.id === "branch-action";
      this.name = this.label();
      this.wrapper = node("span", "select-control" + (source.id === "theme" ? " theme-control" : ""));
      source.before(this.wrapper); this.wrapper.append(source);
      source.hidden = true; source.tabIndex = -1; source.setAttribute("aria-hidden", "true");
      this.button = node("button", "select-trigger"); this.button.type = "button";
      this.button.id = (source.id || "git-select-" + (++nextId)) + "-trigger";
      this.button.setAttribute("aria-label", this.name);
      this.button.setAttribute("aria-haspopup", this.menu ? "menu" : "listbox");
      if (!this.menu) this.button.setAttribute("role", "combobox");
      this.button.setAttribute("aria-expanded", "false");
      this.popup = node("div", "select-popup"); this.popup.id = this.button.id + "-popup";
      this.popup.setAttribute("popover", "manual");
      this.popup.setAttribute("role", this.menu ? "menu" : "listbox");
      this.popup.setAttribute("aria-label", this.name);
      this.popup.hidden = true;
      this.button.setAttribute("aria-controls", this.popup.id);
      this.wrapper.append(this.button, this.popup);
      this.button.addEventListener("click", () => active === this ? this.close() : this.open());
      this.button.addEventListener("keydown", event => this.keydown(event));
      this.button.addEventListener("blur", event => {
        if (active === this && !this.wrapper.contains(event.relatedTarget)) this.close(false);
      });
      this.popup.addEventListener("keydown", event => this.keydown(event));
      this.popup.addEventListener("focusout", event => {
        if (active === this && !this.wrapper.contains(event.relatedTarget)) this.close(false);
      });
      // Retain combobox focus while using its pointer-driven listbox.
      this.popup.addEventListener("pointerdown", event => {
        if (event.pointerType === "mouse" && event.target.closest(".select-option")) event.preventDefault();
      });
      source.addEventListener("change", () => this.sync());
      this.sync();
    }
    label() {
      return this.source.getAttribute("aria-label") || [...(this.source.labels || [])].map(label =>
        [...label.childNodes].filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent).join("").trim()).join(" ") || GitI18n.t("选择选项");
    }
    sync() {
      this.name = this.label();
      this.button.setAttribute("aria-label", this.name);
      this.popup.setAttribute("aria-label", this.name);
      const selected = this.source.selectedOptions[0];
      const label = this.menu ? GitI18n.t("分支操作") : selected?.textContent || GitI18n.t("选择…");
      this.button.replaceChildren(node("span", "select-value", label), icon("chevron", "ui-icon select-chevron"));
      this.button.disabled = this.source.disabled;
      this.button.title = this.source.title || (this.menu ? this.name : this.name + GitI18n.t("：") + label);
      if (active === this) { this.render(); this.position(); }
    }
    render() {
      const previous = this.items?.[this.index]?.value;
      this.items = [...this.source.options].filter(option => !option.hidden && (!this.menu || option.value !== ""));
      this.popup.replaceChildren();
      this.rows = this.items.map((option, i) => {
        const row = node("button", "select-option"); row.type = "button"; row.tabIndex = -1;
        row.id = this.popup.id + "-" + i; row.title = option.textContent;
        row.setAttribute("role", this.menu ? "menuitem" : "option");
        row.disabled = option.disabled;
        row.setAttribute("aria-disabled", String(option.disabled));
        if (!this.menu) row.setAttribute("aria-selected", String(option.selected));
        if (this.menu) {
          row.append(icon({switch:"switch", merge:"merge", delete:"trash"}[option.value] || "branch"));
          row.classList.toggle("destructive", option.value === "delete");
          if (option.value === "delete") row.classList.add("with-separator");
        } else if (this.source.id === "theme") row.append(icon({auto:"monitor", light:"sun", dark:"moon"}[option.value]));
        row.append(node("span", "select-option-label", option.textContent));
        if (!this.menu) {
          const tick = icon("check", "ui-icon select-check");
          tick.style.visibility = option.selected ? "visible" : "hidden"; row.append(tick);
        }
        row.addEventListener("pointermove", () => { if (!option.disabled) this.highlight(i); });
        row.addEventListener("click", () => this.choose(i));
        this.popup.append(row); return row;
      });
      let index = this.items.findIndex(o => o.value === previous && !o.disabled);
      if (index < 0) index = this.items.findIndex(o => o.selected && !o.disabled);
      if (index < 0) index = this.items.findIndex(o => !o.disabled);
      this.highlight(index);
    }
    highlight(index, scroll = false) {
      this.index = index;
      this.rows.forEach((row, i) => row.classList.toggle("highlighted", i === index));
      if (index >= 0) {
        if (!this.menu) this.button.setAttribute("aria-activedescendant", this.rows[index].id);
        else if (active === this && !this.popup.hidden) this.rows[index].focus({preventScroll:true});
        if (scroll) this.rows[index].scrollIntoView({block:"nearest"});
      } else this.button.removeAttribute("aria-activedescendant");
    }
    position() {
      const box = this.button.getBoundingClientRect(), pad = 8;
      const width = Math.min(Math.max(box.width, this.source.id === "theme" ? 160 : 208), innerWidth - pad * 2);
      this.popup.style.width = width + "px";
      this.popup.style.maxHeight = Math.min(304, innerHeight - pad * 2) + "px";
      const height = this.popup.getBoundingClientRect().height;
      const below = innerHeight - box.bottom - pad - 5, above = box.top - pad - 5;
      const up = below < height && above > below;
      const available = Math.max(44, up ? above : below);
      this.popup.style.maxHeight = Math.min(304, available) + "px";
      const actualHeight = this.popup.getBoundingClientRect().height;
      this.popup.style.left = Math.max(pad, Math.min(box.left, innerWidth - width - pad)) + "px";
      this.popup.style.top = Math.max(pad, up ? box.top - actualHeight - 5 : box.bottom + 5) + "px";
    }
    open() {
      if (this.source.disabled) return;
      active?.close(false); active = this; this.index = -1;
      this.render(); this.popup.hidden = false;
      if (this.popup.showPopover) this.popup.showPopover();
      this.button.setAttribute("aria-expanded", "true");
      this.position(); this.highlight(this.index, true);
    }
    close(focus = true) {
      if (active !== this) return;
      if (this.popup.hidePopover && this.popup.matches(":popover-open")) this.popup.hidePopover();
      this.popup.hidden = true; active = null; this.prefix = "";
      this.button.setAttribute("aria-expanded", "false");
      this.button.removeAttribute("aria-activedescendant");
      if (focus && this.button.isConnected) this.button.focus({preventScroll:true});
    }
    choose(index) {
      const option = this.items[index];
      if (!option || option.disabled) return;
      const changed = this.source.value !== option.value;
      this.source.value = option.value;
      this.close();
      if (changed || this.menu) this.source.dispatchEvent(new Event("change", {bubbles:true}));
      this.sync();
    }
    keydown(event) {
      if (event.isComposing || event.ctrlKey || event.metaKey) return;
      const open = active === this, key = event.key;
      if (key === "Tab") { if (open) this.close(this.menu); return; }
      if (key === "Escape") {
        if (open) { event.preventDefault(); event.stopPropagation(); this.close(); }
        return;
      }
      if (["ArrowDown", "ArrowUp", "Home", "End", "Enter", " "].includes(key)) {
        event.preventDefault(); event.stopPropagation();
        if (!open) { this.open(); if (key === "ArrowUp") this.highlight(this.items.findLastIndex(o => !o.disabled), true); return; }
        if (key === "Enter" || key === " ") { this.choose(this.index); return; }
        const enabled = this.items.map((o, i) => o.disabled ? -1 : i).filter(i => i >= 0);
        if (!enabled.length) return;
        const at = enabled.indexOf(this.index), direction = key === "ArrowUp" ? -1 : 1;
        const i = key === "Home" ? enabled[0] : key === "End" ? enabled[enabled.length - 1] : enabled[(at + direction + enabled.length) % enabled.length];
        this.highlight(i, true); return;
      }
      if (key.length === 1 && !event.altKey) {
        event.preventDefault();
        if (!open) this.open();
        this.prefix = Date.now() - (this.typedAt || 0) < 800 ? (this.prefix || "") + key : key;
        this.typedAt = Date.now();
        const index = this.items.findIndex(o => !o.disabled && o.textContent.toLocaleLowerCase().startsWith(this.prefix.toLocaleLowerCase()));
        if (index >= 0) this.highlight(index, true);
      }
    }
  }
  function enhance(source) {
    if (!controls.has(source)) controls.set(source, new SelectControl(source));
    return controls.get(source);
  }
  document.addEventListener("pointerdown", event => {
    if (active && !active.wrapper.contains(event.target)) active.close(false);
  }, true);
  document.addEventListener("scroll", event => {
    if (active && !active.popup.contains(event.target)) active.close(false);
  }, true);
  window.addEventListener("resize", () => active?.close(false));
  document.addEventListener("git-language-changed", () => {
    for (const source of document.querySelectorAll("select")) controls.get(source)?.sync();
  });
  for (const source of document.querySelectorAll("select")) enhance(source);
  for (const button of document.querySelectorAll("[data-icon]")) button.prepend(icon(button.dataset.icon));
  return {icon, enhance, sync: source => controls.get(source)?.sync(), focus: source => enhance(source).button.focus(), closeMenus: () => active?.close(false)};
})();
