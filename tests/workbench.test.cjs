const {test} = require("node:test");
const assert = require("node:assert/strict");
const Graph = require("../assets/commit-graph.js");
const Files = require("../assets/file-tree.js");
const Diff = require("../assets/diff-view.js");
const commit = (sha, ...parents) => ({sha, parents});

test("linear graph carries the same lane and stops at the root", () => {
  const before = [commit("tip", "middle"), commit("middle", "root"), commit("root")];
  const copy = JSON.stringify(before), {rows, width} = Graph.layout(before);
  assert.equal(width, 52);
  assert.ok(rows.every(row => row.column === 0 && row.color === rows[0].color));
  assert.equal(rows[0].edges.length, 1);
  assert.equal(rows[1].edges.length, 2);
  assert.equal(rows[2].edges[0].end, 19);
  assert.equal(JSON.stringify(before), copy);
});

test("merge graph splits by parents, preserves other lanes and rejoins common ancestry", () => {
  const {rows} = Graph.layout([commit("merge", "main", "feature"), commit("main", "base"), commit("feature", "base"), commit("base")]);
  assert.equal(rows[0].merge, true);
  assert.deepEqual(rows[0].edges.map(edge => edge.to), [0, 1]);
  assert.equal(rows[2].column, 1);
  assert.ok(rows[2].edges.some(edge => edge.from === 1 && edge.to === 0 && edge.start === 19));
  assert.equal(rows[3].column, 0);
  assert.equal(rows[3].edges.length, 1);
});

test("octopus parents and disconnected tips have deterministic, distinct lanes", () => {
  const graph = Graph.layout([commit("m", "a", "b", "c", "b"), commit("other"), commit("a"), commit("b"), commit("c")]);
  assert.deepEqual(graph.rows[0].edges.map(edge => edge.to), [0, 1, 2]);
  assert.equal(graph.rows[1].column, 3);
  assert.ok(graph.width >= 90);
  assert.deepEqual(Graph.layout([]), {rows: [], width: 52});
});

test("file hierarchy groups nested Unity paths without changing Git paths", () => {
  const files = [{path:"Assets/Scripts/UI/ChatPanel.cs"}, {path:"Assets/Scripts/Core/Game.cs"}, {path:"README.md"}];
  const copy = JSON.stringify(files), tree = Files.build(files);
  assert.equal(tree[0].name, "Assets");
  assert.equal(tree[0].files.length, 2);
  assert.deepEqual(tree[0].children[0].children.map(node => node.name), ["Core", "UI"]);
  assert.equal(tree[0].children[0].children[1].children[0].file, files[0]);
  assert.equal(tree[1].file, files[2]);
  assert.equal(JSON.stringify(files), copy);
  assert.equal(Files.build([{path:"__proto__/constructor/空 格.cs"}])[0].name, "__proto__");
});

test("folder checkbox supports indeterminate state and excludes unoperable/conflicted files", () => {
  const files = [{path:"a"}, {path:"b"}, {path:"conflict", conflict:true}, {path:"invalid", operable:false}];
  assert.deepEqual(Files.selection(files, new Set(["a"])), {checked:false, indeterminate:true, disabled:false, paths:["a", "b"]});
  assert.equal(Files.selection(files, new Set(["a","b"])).checked, true);
  assert.equal(Files.selection([], new Set()).disabled, true);
});

test("diff line numbers restart per hunk and headers never count as changes", () => {
  const rows = Diff.parse("--- a/file\n+++ b/file\n@@ -10,2 +20,3 @@\n context\n-old\n+new\n+extra\n@@ -50 +60 @@\n-last\n+next");
  assert.equal(rows[0].kind, "meta");
  assert.equal(rows[3].old, 10); assert.equal(rows[3].next, 20);
  assert.equal(rows[4].old, 11); assert.equal(rows[5].next, 21);
  assert.equal(rows.at(-2).old, 50); assert.equal(rows.at(-1).next, 60);
});

test("split diff pairs replacements and leaves unmatched lines on their correct side", () => {
  const rows = Diff.pairs(Diff.parse("@@ -1,2 +1 @@\n-old 1\n-old 2\n+new 1"));
  assert.equal(rows[1].left.text, "-old 1"); assert.equal(rows[1].right.text, "+new 1");
  assert.equal(rows[2].left.text, "-old 2"); assert.equal(rows[2].right, undefined);
  assert.equal(Diff.parse("+untracked first\n+second")[1].next, 2);
  assert.equal(Diff.parse("@@ -0,0 +1 @@\n+one line\n").length, 2);
});
