"use strict";
// MCP Apps JSON-RPC bridge. Only the actual parent frame may send host messages.
window.GitHost = (() => {
  let nextId = 0, hostOrigin = "*", initialResolve;
  const pending = new Map();
  const context = {};
  const initial = new Promise(resolve => { initialResolve = resolve; });
  function notify(method, params = {}) {
    window.parent.postMessage({jsonrpc: "2.0", method, params}, hostOrigin);
  }
  function request(method, params = {}, signal) {
    if (signal?.aborted) return Promise.reject(new DOMException("已取消", "AbortError"));
    return new Promise((resolve, reject) => {
      const id = "git-" + (++nextId);
      const finish = (fn, value) => {
        pending.delete(id); clearTimeout(timer); signal?.removeEventListener("abort", abort); fn(value);
      };
      const abort = () => finish(reject, new DOMException("已取消", "AbortError"));
      const timer = setTimeout(() => finish(reject, new Error("Codex 响应超时，请重试。")), 90000);
      pending.set(id, {resolve: value => finish(resolve, value), reject: err => finish(reject, err)});
      signal?.addEventListener("abort", abort, {once: true});
      window.parent.postMessage({jsonrpc: "2.0", id, method, params}, hostOrigin);
    });
  }
  function updateContext(next) {
    Object.assign(context, next);
    document.dispatchEvent(new CustomEvent("git-host-context", {detail: context}));
  }
  function unpack(result) {
    if (result?.isError) throw new Error(result.content?.find(c => c.type === "text")?.text || "Git 查询失败。");
    const data = result?._meta?.gitExplorer || result?.structuredContent;
    if (!data || typeof data !== "object") throw new Error("Codex 返回的数据格式无效。");
    return data;
  }
  window.addEventListener("message", event => {
    if (event.source !== window.parent) return;
    const message = event.data;
    if (!message || message.jsonrpc !== "2.0") return;
    if (hostOrigin !== "*" && event.origin !== hostOrigin) return;
    // Sandboxed MCP hosts may have an opaque origin, requiring targetOrigin '*'.
    if (event.origin && event.origin !== "null") hostOrigin = event.origin;
    if (message.id !== undefined && !message.method) {
      const call = pending.get(message.id);
      if (message.error) call?.reject(new Error(message.error.message || "Codex 请求失败。"));
      else call?.resolve(message.result);
    } else if (message.method === "ui/notifications/tool-result") initialResolve(message.params);
    else if (message.method === "ui/notifications/host-context-changed") updateContext(message.params || {});
    else if (message.method === "ui/resource-teardown") {
      for (const call of [...pending.values()]) call.reject(new DOMException("面板已关闭", "AbortError"));
      window.parent.postMessage({jsonrpc: "2.0", id: message.id, result: {}}, hostOrigin);
    }
  });
  const ready = request("ui/initialize", {appInfo: {name: "git-branch-explorer", version: "0.2.0"},
    appCapabilities: {}, protocolVersion: "2026-01-26"}).then(result => {
      updateContext(result.hostContext || {});
      notify("ui/notifications/initialized");
      return context;
    });
  return {ready, initial, context, unpack, request,
    async operation(name, args) {
      // Unlike queries, mutations are never cancelled or automatically retried.
      return unpack(await request("tools/call", {name, arguments: args}));
    },
    async query(action, args, signal) {
      return unpack(await request("tools/call", {name: "git_query", arguments: {action, ...args}}, signal));
    }};
})();
