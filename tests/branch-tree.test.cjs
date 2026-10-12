const {test} = require("node:test");
const assert = require("node:assert/strict");
const {build, ancestors, folderId, Expansion} = require("../assets/branch-tree.js");

const branch = (name, remote = false, current = false) => ({name, remote, current,
  ref: (remote ? "refs/remotes/" : "refs/heads/") + name, sha: "1234567", tracking: ""});
const flatten = nodes => nodes.flatMap(node => node.type === "branch" ? [node] : flatten(node.children));
const storage = () => {
  const values = new Map();
  return {getItem: key => values.get(key), setItem: (key, value) => values.set(key, value)};
};

test("nested slash prefixes become folders while leaf refs and Git data stay unchanged", () => {
  const data = [branch("codex/card-collection"), branch("dyy/1.0/1.0.8_dyy_leveleditor", false, true), branch("1.1.4_win")];
  const before = JSON.stringify(data), [local] = build(data);
  assert.equal(local.count, 3);
  assert.deepEqual(local.children.map(node => node.name), ["codex", "dyy", "1.1.4_win"]);
  const dyy = local.children[1], version = dyy.children[0], leaf = version.children[0];
  assert.equal(version.name, "1.0");
  assert.equal(leaf.name, "1.0.8_dyy_leveleditor");
  assert.equal(leaf.branch, data[1]);
  assert.equal(dyy.current, true);
  assert.equal(version.count, 1);
  assert.equal(JSON.stringify(data), before);
});

test("local and remote folders preserve separate identities and the remote name", () => {
  const data = [branch("origin/main"), branch("origin/main", true), branch("upstream/feature/a", true)];
  const [local, remote] = build(data);
  assert.equal(local.group, "local");
  assert.equal(remote.count, 2);
  assert.notEqual(local.children[0].id, remote.children[0].id);
  assert.deepEqual(remote.children.map(node => node.name), ["origin", "upstream"]);
  assert.equal(flatten([remote])[0].branch.ref, "refs/remotes/origin/main");
});

test("search matches complete paths without losing hierarchy or the branch-type filter", () => {
  const data = [branch("codex/card-collection"), branch("codex/card-fix"), branch("codex/中文"), branch("origin/codex/card-collection", true)];
  const local = build(data, "CODEX/CARD-COLLECTION", "local");
  assert.equal(local[0].count, 1);
  assert.equal(local[0].children[0].name, "codex");
  assert.equal(flatten(local)[0].branch, data[0]);
  assert.equal(flatten(build(data, "中文"))[0].name, "中文");
  assert.equal(flatten(build(data, "card", "remote"))[0].branch, data[3]);
  assert.deepEqual(build(data, "missing"), []);
});

test("folders sort naturally before leaves and branch leaves keep input recency order", () => {
  const data = [branch("release10/b"), branch("main"), branch("release2/z"), branch("release2/a"), branch("older")];
  const [root] = build(data);
  assert.deepEqual(root.children.map(node => node.name), ["release2", "release10", "main", "older"]);
  assert.deepEqual(root.children[0].children.map(node => node.name), ["z", "a"]);
  assert.equal(root.children[0].count, 2);
});

test("same leaf names and object-prototype words remain distinct ordinary Git names", () => {
  const data = [branch("__proto__/main"), branch("constructor/main"), branch("feature/main")];
  const leaves = flatten(build(data));
  assert.equal(leaves.length, 3);
  assert.equal(new Set(leaves.map(node => node.id)).size, 3);
  assert.equal(build(data)[0].children.find(node => node.name === "__proto__").children[0].branch, data[0]);
});

test("the initial current path opens and manually closed folders survive reload", () => {
  const saved = storage(), current = branch("feature/topic", false, true);
  const [root] = build([current]), folder = root.children[0];
  const first = new Expansion(saved);
  first.use("/repo", current);
  assert.equal(first.expanded(root), true);
  assert.equal(first.expanded(folder), true);
  first.set(folder, false);
  const restored = new Expansion(saved);
  restored.use("/repo", current);
  assert.equal(restored.expanded(folder), false);
  restored.reveal(current);
  assert.equal(restored.expanded(folder), true);
  assert.deepEqual(ancestors(current), [folderId("local"), folderId("local", "feature")]);
});

test("search expands matching folders temporarily and does not overwrite saved choices", () => {
  const saved = storage(), current = branch("main", false, true), view = new Expansion(saved);
  const [root] = build([current, branch("feature/topic")]), folder = root.children[0];
  view.use("/repo", current);
  view.set(folder, false);
  view.filter("topic");
  assert.equal(view.expanded(folder), true);
  view.set(folder, false);
  assert.equal(view.expanded(folder), false);
  view.filter("feature");
  assert.equal(view.expanded(folder), true);
  view.filter("");
  assert.equal(view.expanded(folder), false);
  const restored = new Expansion(saved); restored.use("/repo", current);
  assert.equal(restored.expanded(folder), false);
});

test("expansion state is isolated per repository and tolerates unavailable storage", () => {
  const saved = storage(), current = branch("main", false, true), view = new Expansion(saved);
  const [root] = build([current, branch("feature/topic")]), folder = root.children[0];
  view.use("/a", current); view.set(folder, true);
  view.use("/b", current); assert.equal(view.expanded(folder), false);
  view.set(root, false);
  view.use("/a", current); assert.equal(view.expanded(folder), true); assert.equal(view.expanded(root), true);
  const unavailable = new Expansion({getItem() {throw Error("denied");}, setItem() {throw Error("denied");}});
  unavailable.use("/a", current); unavailable.set(root, false);
  assert.equal(unavailable.expanded(root), false);
  const corrupt = new Expansion({getItem: () => "{broken"});
  corrupt.use("/a", branch("feature/topic", false, true));
  assert.equal(corrupt.expanded(folder), true);
});

test("empty repos and detached HEAD remain browsable without inventing path components", () => {
  assert.deepEqual(build([]), []);
  const head = {...branch("HEAD", false, true), ref: "deadbeef", detached: true};
  const [local] = build([head]);
  assert.equal(local.children[0].branch, head);
  assert.deepEqual(ancestors(head), [folderId("local")]);
});

test("tags preserve their full identity and form a separate searchable group", () => {
  const tag = {...branch("release/v1.0"), ref: "refs/tags/release/v1.0", tag: true};
  const groups = build([branch("release/v1.0"), tag]);
  assert.deepEqual(groups.map(group => group.group), ["local", "tags"]);
  assert.equal(groups[1].children[0].children[0].branch, tag);
  assert.notEqual(groups[0].children[0].id, groups[1].children[0].id);
  assert.equal(flatten(build([tag], "V1.0"))[0].branch.ref, tag.ref);
  assert.deepEqual(build([tag], "", "local"), []);
});
