const {test} = require("node:test");
const assert = require("node:assert/strict");
const Scope = require("../assets/history-scope.js");
const branch = (name, options = {}) => ({name, ref: "refs/heads/" + name, sha: name + "-oid", ...options});
const branches = [branch("feature", {current:true, upstream:"refs/remotes/origin/feature"}), branch("master"),
  branch("origin/master", {ref:"refs/remotes/origin/master", remote:true}),
  branch("origin/feature", {ref:"refs/remotes/origin/feature", remote:true}), branch("unrelated")];

test("default log uses all branches, with current and mainline refs ready for selection", () => {
  const scope = new Scope.Selection().use("repo", branches);
  assert.deepEqual(scope.query(), {all_branches:true});
  assert.deepEqual(scope.refs, branches.slice(0, 4).map(b => b.ref));
  scope.configure("selected");
  assert.deepEqual(scope.query(), {refs:branches.slice(0, 4).map(b => b.ref)});
  scope.configure("all");
  assert.equal(scope.refs.length, 4);
});

test("multi-branch pagination sends immutable roots, not moving branch names", () => {
  const scope = new Scope.Selection().use("repo", branches);
  const roots = ["a".repeat(40), "b".repeat(40)];
  assert.deepEqual(scope.query(roots), {snapshot:roots});
  assert.notEqual(scope.query(roots).snapshot, roots);
  assert.deepEqual(scope.query([]), {snapshot:[]});
});

test("saved selections are isolated per repository and prune deleted branches on refresh", () => {
  const saved = new Map();
  const storage = {getItem:key => saved.get(key), setItem:(key, value) => saved.set(key, value)};
  const scope = new Scope.Selection(storage).use("repo-a", branches);
  scope.configure("selected", [branches[0].ref, branches[1].ref]);
  scope.use("repo-b", branches);
  assert.equal(scope.mode, "all");
  scope.use("repo-a", branches);
  assert.deepEqual(scope.refs, branches.slice(0, 2).map(b => b.ref));
  scope.use("repo-a", branches.filter(b => b.name !== "master"));
  assert.deepEqual(scope.refs, [branches[0].ref]);
  assert.equal(scope.configure("selected", []), false);
  assert.equal(scope.configure("selected", ["--all"]), false);
  assert.deepEqual(scope.refs, [branches[0].ref]);
});

test("malformed or blocked storage and unborn branches do not break initial history", () => {
  const bad = new Scope.Selection({getItem:() => "{invalid"}).use("repo", branches);
  assert.equal(bad.mode, "all");
  const blocked = new Scope.Selection({getItem:() => {throw Error("blocked");}, setItem:() => {throw Error("blocked");}});
  blocked.use("repo", branches); assert.ok(blocked.configure("selected"));
  const empty = new Scope.Selection().use("empty", [branch("main", {sha:null, current:true})]);
  assert.deepEqual(empty.query(), {all_branches:true}); assert.deepEqual(empty.refs, []);
});

test("selected tags and detached HEAD remain valid without changing checkout", () => {
  const head = branch("HEAD", {ref:"a".repeat(40), current:true, detached:true});
  const tag = branch("v1", {ref:"refs/tags/v1", tag:true});
  const scope = new Scope.Selection().use("repo", [head], [tag]);
  assert.ok(scope.configure("selected", [tag.ref, head.ref, tag.ref]));
  assert.deepEqual(scope.refs, [tag.ref, head.ref]);
});

test("every tip reference survives decoration, with current and mainline branches before tags", () => {
  const sha = "shared-tip";
  const tips = branches.map(b => ({...b, sha}));
  const tags = Array.from({length:8}, (_, i) => ({...branch("v" + i), tag:true, sha}));
  const refs = Scope.references(tips, tags, sha);
  assert.equal(refs.length, 13);
  assert.equal(refs[0].name, "feature");
  assert.ok(refs.findIndex(b => b.name === "master") < refs.findIndex(b => b.tag));
  assert.ok(refs.findIndex(b => b.name === "origin/master") < refs.findIndex(b => b.tag));
});
