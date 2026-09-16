"use strict";
// Only explicit UI messages are translated. Git names, paths, messages and diffs are data.
window.GitI18n = (() => {
  const catalog = window.GitEnglish || {};
  const bindings = new Set(), nodeBindings = new WeakMap();
  let locale = "en-US", writtenLang = "";
  function validLocale(value) {
    if (typeof value !== "string" || value.length > 100 || !value.trim()) return null;
    try { return Intl.getCanonicalLocales(value.trim().replace(/_/g, "-"))[0] || null; } catch { return null; }
  }
  function resolveLocale(...candidates) {
    const requested = candidates.map(validLocale).find(Boolean) || "en-US";
    return /^(en|zh)(-|$)/i.test(requested) ? requested : "en-US";
  }
  function format(value) {
    if (typeof value === "function") return format(value());
    if (!value || typeof value !== "object" || value._gitMessage !== true) return String(value ?? "");
    if (value.key === "$concat") return value.values.parts.map(format).join("");
    const template = locale.toLowerCase().startsWith("zh") ? value.key : catalog[value.key] ?? value.key;
    return template.replace(/\{(\w+)\}/g, (_, key) => format(value.values[key]));
  }
  function message(key, values = {}) { return {key, values, _gitMessage: true}; }
  function t(key, values) {
    return format(typeof key === "string" ? message(key, values) : key);
  }
  function bind(node, attribute, value) {
    const render = () => {
      const result = format(value);
      if (attribute) node.setAttribute(attribute, result); else node.textContent = result;
    };
    let entries = nodeBindings.get(node);
    if (!entries) {
      nodeBindings.set(node, entries = new Map());
      bindings.add(new WeakRef(node));
    }
    entries.set(attribute, render); render();
  }
  function text(node, value) {
    const child = document.createTextNode("");
    node.replaceChildren(child);
    bind(child, null, value);
  }
  function attr(node, name, value) { bind(node, name, value); }
  function applyLocale(next) {
    next = resolveLocale(next);
    const changed = next !== locale;
    locale = next; writtenLang = next;
    if (document.documentElement.lang !== next) document.documentElement.lang = next;
    if (!changed) return;
    for (const reference of bindings) {
      const node = reference.deref();
      if (!node) { bindings.delete(reference); continue; }
      if (!node.isConnected) continue;
      const entries = nodeBindings.get(node);
      for (const render of entries.values()) render();
    }
    document.dispatchEvent(new CustomEvent("git-language-changed", {detail: {locale}}));
  }
  function localizedError(value) {
    const error = new Error(format(value));
    Object.defineProperty(error, "message", {get: () => format(value)});
    return error;
  }
  function hydrate(data, messages = []) {
    for (const entry of messages) {
      if (!Array.isArray(entry.path) || !entry.path.length || !entry.message?._gitMessage) continue;
      if (entry.path.some(key => ["__proto__", "prototype", "constructor"].includes(key))) continue;
      let parent = data;
      for (const key of entry.path.slice(0, -1)) parent = parent?.[key];
      const key = entry.path[entry.path.length - 1];
      if (parent && Object.hasOwn(parent, key)) parent[key] = entry.message;
    }
    return data;
  }
  // Bind the trusted template once, before any repository data is inserted.
  const walker = document.createTreeWalker(document.documentElement, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.parentElement.closest("script, style")) nodes.push(node);
  }
  for (const node of nodes) {
    const key = node.textContent.trim();
    if (Object.hasOwn(catalog, key)) {
      const leading = node.textContent.match(/^\s*/)[0], trailing = node.textContent.match(/\s*$/)[0];
      bind(node, null, () => leading + t(key) + trailing);
    }
  }
  for (const node of document.querySelectorAll("[title], [aria-label], [placeholder]")) {
    for (const attribute of ["title", "aria-label", "placeholder"]) {
      const key = node.getAttribute(attribute);
      if (Object.hasOwn(catalog, key)) attr(node, attribute, () => t(key));
    }
  }
  // MCP host context is authoritative; DOM lang supports hosts that mirror it.
  document.addEventListener("git-host-context", event => {
    const next = validLocale(event.detail?.locale);
    if (next) applyLocale(next);
  });
  new MutationObserver(() => {
    if (document.documentElement.lang !== writtenLang && validLocale(document.documentElement.lang)) {
      applyLocale(document.documentElement.lang);
    }
  }).observe(document.documentElement, {attributes: true, attributeFilter: ["lang"]});
  window.addEventListener("languagechange", () => {
    if (!window.GitHost?.context.locale) applyLocale(navigator.language);
  });
  // Template bindings were created before the locale was resolved.
  locale = "";
  applyLocale(resolveLocale(document.documentElement.lang, navigator.language));
  return {t, message, text, attr, format, hydrate, error: localizedError, resolveLocale,
    get locale() { return locale; }};
})();
