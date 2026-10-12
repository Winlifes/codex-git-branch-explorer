"use strict";
const GitDiffView = (() => {
  function parse(patch) {
    let oldLine = 0, newLine = patch.includes("@@ ") ? 0 : 1;
    const lines = patch.split("\n");
    if (lines.at(-1) === "") lines.pop();
    return lines.map(text => {
      const hunk = text.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      if (hunk) { oldLine = Number(hunk[1]); newLine = Number(hunk[2]); return {kind: "hunk", text, old: "", next: ""}; }
      if (/^(diff |index |--- |\+\+\+ |new file |deleted file |old mode |new mode |\\)/.test(text)) return {kind: "meta", text, old: "", next: ""};
      if (text.startsWith("+")) return {kind: "add", text, old: "", next: newLine ? newLine++ : ""};
      if (text.startsWith("-")) return {kind: "del", text, old: oldLine ? oldLine++ : "", next: ""};
      return {kind: "context", text, old: oldLine ? oldLine++ : "", next: newLine ? newLine++ : ""};
    });
  }
  function pairs(rows) {
    const result = [];
    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];
      if (row.kind === "del" || row.kind === "add") {
        const deleted = [], added = [];
        while (i < rows.length && ["del", "add"].includes(rows[i].kind)) {
          (rows[i].kind === "del" ? deleted : added).push(rows[i++]);
        }
        i--;
        for (let n = 0; n < Math.max(deleted.length, added.length); n++) result.push({left: deleted[n], right: added[n]});
      } else result.push({left: row, right: row});
    }
    return result;
  }
  function render(target, data, split = false) {
    target.classList.toggle("split-diff", split);
    target.classList.add("numbered-diff");
    if (/Binary files |GIT binary patch/.test(data.patch || "")) {
      target.replaceChildren();
      const notice = document.createElement("span"); notice.className = "diff-empty";
      GitI18n.text(notice, () => GitI18n.t("二进制文件，无法显示文本差异。")); target.append(notice); return;
    }
    const rows = parse(data.patch || ""), fragment = document.createDocumentFragment();
    function cell(row, side) {
      const node = document.createElement("span"); node.className = "diff-cell " + (row?.kind || "blank");
      if (!row) { node.append(document.createTextNode(" ")); return node; }
      const number = document.createElement("span"); number.className = "diff-number";
      number.textContent = String(side === "left" ? row.old : row.next); node.append(number);
      const code = document.createElement("code"); code.textContent = ["meta", "hunk"].includes(row.kind) || !/^[ +\-]/.test(row.text) ? row.text : row.text.slice(1) || " ";
      node.append(code); return node;
    }
    if (data.notice) { const notice = document.createElement("span"); notice.className = "diff-line meta"; GitI18n.text(notice, () => data.notice); fragment.append(notice); }
    if (split) {
      // Each editor scrolls horizontally as a whole, rather than per line.
      fragment.replaceChildren();
      const columns = ["left", "right"].map(side => {
        const column = document.createElement("span"); column.className = "diff-column";
        if (data.notice) { const notice = document.createElement("span"); notice.className = "diff-line meta"; GitI18n.text(notice, () => data.notice); column.append(notice); }
        for (const pair of pairs(rows)) {
          if (pair.left?.kind === "meta") continue;
          column.append(cell(pair[side], side));
        }
        if (data.truncated) {
          const notice = document.createElement("span"); notice.className = "diff-line meta";
          GitI18n.text(notice, () => GitI18n.t("差异较大，仅展示前 800 KB。")); column.append(notice);
        }
        return column;
      });
      for (const [index, column] of columns.entries()) column.addEventListener("scroll", () => {
        const other = columns[1 - index];
        if (other.scrollTop !== column.scrollTop) other.scrollTop = column.scrollTop;
      });
      fragment.append(...columns);
    } else for (const row of rows) {
      if (row.kind === "meta") continue;
      const node = document.createElement("span"); node.className = "diff-line " + row.kind;
      for (const value of [row.old, row.next]) { const number = document.createElement("span"); number.className = "diff-number"; number.textContent = String(value); node.append(number); }
      const text = document.createElement("code"); text.textContent = row.text || " "; node.append(text); fragment.append(node);
    }
    if (!data.patch) {
      const notice = document.createElement("span"); notice.className = "diff-empty";
      GitI18n.text(notice, () => GitI18n.t("此文件没有可显示的文本差异。")); fragment.append(notice);
    }
    if (data.truncated && !split) {
      const notice = document.createElement("span"); notice.className = "diff-line meta";
      GitI18n.text(notice, () => GitI18n.t("差异较大，仅展示前 800 KB。")); fragment.append(notice);
    }
    target.replaceChildren(fragment);
  }
  return {parse, pairs, render};
})();
if (typeof module !== "undefined") module.exports = GitDiffView;
