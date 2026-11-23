const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const Scope = require("../assets/history-scope.js");
const Branches = require("../assets/branch-tree.js");

// Exercise the real app event handlers and async query controller. Layout and
// browser input are checked separately against the running MCP panel.
function application() {
  const elements = new Map();
  function element() {
    return {value:"", checked:false, hidden:false, children:[], dataset:{}, listeners:{}, textContent:"",
      style:{setProperty() {}}, classList:{add() {}, remove() {}, toggle() {}, contains() {return false;}},
      addEventListener(name, callback) {(this.listeners[name] ||= []).push(callback);},
      setAttribute() {}, toggleAttribute() {}, focus() {}, contains() {return false;},
      append(...children) {this.children.push(...children);}, replaceChildren(...children) {this.children = children;},
      querySelectorAll() {return [];}};
  }
  function get(id) {if (!elements.has(id)) elements.set(id, element()); return elements.get(id);}
  const harness = {calls:[], responses:[], events:[]};
  const document = {getElementById:get, querySelector:get, querySelectorAll:()=>[],
    createElement:element, documentElement:element(), body:element(), addEventListener() {},
    dispatchEvent:event => harness.events.push(event.type)};
  const i18n = {locale:"en-US", t:(text, values = {}) => text.replace(/\{(\w+)\}/g, (_, key) => values[key] ?? ""),
    text:(node, value) => {node.textContent = typeof value === "function" ? value() : value;}, attr() {}};
  const ui = {sync:source => {get(source === get("history-scope") ? "history-scope-trigger" : "theme-trigger").textContent = source.value;}};
  const context = vm.createContext({document, console, harness, GitI18n:i18n, GitUI:ui, GitHistoryScope:Scope,
    GitBranchTree:Branches, Map, Set, Date, Intl, AbortController, URLSearchParams,
    CustomEvent:class {constructor(type) {this.type = type;}},
    matchMedia:()=>({matches:false, addEventListener() {}}),
    window:{GitUI:ui, GitHost:{context:{theme:"dark"}, ready:new Promise(()=>{})}},
    localStorage:{getItem:()=>null, setItem() {}}});
  vm.runInContext(fs.readFileSync(require.resolve("../assets/app.js"), "utf8"), context);
  vm.runInContext(`
    renderBranches = () => {};
    renderCommits = () => {};
    closeDetail = () => {};
    selectCommit = () => {};
    api = async (route, params) => {
      harness.calls.push({route, params});
      return harness.responses.length ? await harness.responses.shift() : await new Promise(() => {});
    };
    selectedRepository = "repo";
    state.repository = {path:"repo", head:"old", current_ref:"refs/heads/feature"};
    state.branches = [{ref:"refs/heads/feature", name:"feature", sha:"old", current:true},
      {ref:"refs/heads/master", name:"master", sha:"master-old"}];
    state.tags = [];
    state.branch = state.branches[1];
    historyScope.use("repo", state.branches);
    historyScope.configure("selected");
    updateHistoryScope();
  `, context);
  return {get, harness, run:source => vm.runInContext(source, context),
    fire:(id, event) => get(id).listeners[event].forEach(callback => callback({}))};
}
function page(head, master, commits = [{sha:head}], next = 1) {
  return {commits, snapshot:[head, master], next_offset:next, has_more:true, log_context:{
    repository:{path:"repo", head, current_ref:"refs/heads/feature"},
    branches:[{ref:"refs/heads/feature", name:"feature", sha:head, current:true},
      {ref:"refs/heads/master", name:"master", sha:master}],
    tags:[{ref:"refs/tags/release", name:"release", sha:master, tag:true}]}};
}
const plain = value => JSON.parse(JSON.stringify(value));

test("clear search keeps selected scope and allows a subsequent switch to all branches", () => {
  const app = application();
  app.get("commit-search").value = "term"; app.get("author-search").value = "author";
  app.get("first-parent").checked = true;
  // Model native form reset: the scope select's default is all.
  app.get("filters").reset = () => {app.get("history-scope").value = "all";};
  app.fire("clear-filters", "click");
  assert.equal(app.get("history-scope").value, "selected");
  assert.equal(app.get("history-scope-trigger").textContent, "selected");
  assert.equal(app.get("commit-search").value, ""); assert.equal(app.get("author-search").value, "");
  assert.equal(app.get("first-parent").checked, false);
  assert.ok(app.harness.calls.at(-1).params.refs.includes("refs/heads/master"));
  app.get("history-scope").value = "all";
  app.fire("history-scope", "change");
  assert.equal(app.harness.calls.at(-1).params.all_branches, true);
});

test("new queries update graph labels, HEAD, sidebar and operation target from returned context", async () => {
  const app = application();
  app.harness.responses.push(page("new-head", "new-master"));
  await app.run("loadHistory()");
  assert.equal(app.run("state.historyHead"), "new-head");
  assert.equal(app.run("state.historyBranches.find(b => b.name === 'master').sha"), "new-master");
  assert.equal(app.run("state.branch.sha"), "new-master");
  assert.equal(app.run("state.repository.head"), "new-head");
  assert.equal(app.run("state.historyTags[0].sha"), "new-master");
  assert.equal(app.harness.events.at(-1), "git-repository-loaded");
});

test("loading more preserves first-page labels and HEAD while using frozen query roots", async () => {
  const app = application();
  app.harness.responses.push(page("new-head", "new-master"));
  await app.run("loadHistory()");
  app.harness.responses.push({commits:[{sha:"parent"}], snapshot:["new-head", "new-master"], next_offset:2, has_more:false});
  await app.run("loadHistory(true)");
  assert.deepEqual(plain(app.harness.calls.at(-1).params.snapshot), ["new-head", "new-master"]);
  assert.equal(app.run("state.historyHead"), "new-head");
  assert.equal(app.run("state.historyBranches.find(b => b.name === 'master').sha"), "new-master");
  assert.equal(app.run("state.historyTags[0].sha"), "new-master");
  assert.deepEqual(plain(app.run("state.commits.map(c => c.sha)")), ["new-head", "parent"]);
});

test("a slow earlier query cannot overwrite newer log context or branch decorations", async () => {
  const app = application();
  let finishOld;
  app.harness.responses.push(new Promise(resolve => {finishOld = resolve;}));
  const earlier = app.run("loadHistory()");
  app.harness.responses.push(page("latest-head", "latest-master"));
  await app.run("loadHistory()");
  finishOld(page("outdated-head", "outdated-master"));
  await earlier;
  assert.equal(app.run("state.historyHead"), "latest-head");
  assert.equal(app.run("state.branch.sha"), "latest-master");
  assert.deepEqual(plain(app.run("state.commits.map(c => c.sha)")), ["latest-head"]);
});
