"use strict";
// Pure topology layout. Lanes follow parent object IDs, never dates or row order.
const GitCommitGraph = (() => {
  const palette = ["#a78bfa", "#6ea8f7", "#69c5a0", "#dfb568", "#d889bb", "#75c6d8"];
  function layout(commits) {
    let lanes = [], color = 0, width = 1;
    const rows = commits.map(commit => {
      const incoming = lanes.some(lane => lane.sha === commit.sha);
      if (!incoming) lanes.push({sha: commit.sha, color: palette[color++ % palette.length]});
      const before = lanes.map(lane => ({...lane}));
      const column = before.findIndex(lane => lane.sha === commit.sha), active = before[column];
      lanes.splice(column, 1);
      const parents = [...new Set(commit.parents || [])];
      let insert = column;
      for (const [index, sha] of parents.entries()) {
        if (!lanes.some(lane => lane.sha === sha)) {
          lanes.splice(Math.min(insert++, lanes.length), 0,
            {sha, color: index === 0 ? active.color : palette[color++ % palette.length]});
        }
      }
      const edges = [];
      before.forEach((lane, index) => {
        if (lane.sha === commit.sha) {
          if (incoming) edges.push({from: index, to: column, start: 0, end: 19, color: active.color});
        } else {
          const to = lanes.findIndex(next => next.sha === lane.sha);
          if (to >= 0) edges.push({from: index, to, start: 0, end: 38, color: lane.color});
        }
      });
      for (const sha of parents) {
        const to = lanes.findIndex(lane => lane.sha === sha);
        edges.push({from: column, to, start: 19, end: 38, color: active.color});
      }
      width = Math.max(width, before.length, lanes.length);
      return {sha: commit.sha, column, color: active.color, merge: parents.length > 1, edges};
    });
    return {rows, width: Math.max(52, width * 18 + 18)};
  }
  function render(row, width) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("width", width); svg.setAttribute("height", 38);
    svg.setAttribute("viewBox", `0 0 ${width} 38`);
    svg.classList.add("commit-graph"); svg.setAttribute("aria-hidden", "true");
    for (const edge of row.edges) {
      const line = document.createElementNS(ns, "path"), x = 14 + edge.from * 18, endX = 14 + edge.to * 18;
      const mid = (edge.start + edge.end) / 2;
      line.setAttribute("d", x === endX ? `M ${x} ${edge.start} V ${edge.end}` :
        `M ${x} ${edge.start} C ${x} ${mid}, ${endX} ${mid}, ${endX} ${edge.end}`);
      line.setAttribute("stroke", edge.color); line.setAttribute("stroke-width", "1.6");
      line.setAttribute("fill", "none"); svg.append(line);
    }
    const dot = document.createElementNS(ns, "circle");
    dot.setAttribute("cx", 14 + row.column * 18); dot.setAttribute("cy", 19);
    dot.setAttribute("r", row.merge ? 4.6 : 3.8);
    dot.setAttribute("fill", row.merge ? "var(--bg)" : row.color);
    dot.setAttribute("stroke", row.color); dot.setAttribute("stroke-width", "1.7"); svg.append(dot);
    return svg;
  }
  return {layout, render};
})();
if (typeof module !== "undefined") module.exports = GitCommitGraph;
