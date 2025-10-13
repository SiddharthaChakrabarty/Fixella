import React, { useEffect, useRef, useState } from "react";
import { Network } from "vis-network/standalone";
import { DataSet } from "vis-data/peer";

// Uses the Flask KG routes (default localhost:8080). You can override with REACT_APP_KG_API_URL
const API_BASE = "http://localhost:5000";

export default function KnowledgeGraph() {
  const containerRef = useRef(null);
  const netRef = useRef(null);
  const nodesRef = useRef(new DataSet());
  const edgesRef = useRef(new DataSet());
  const [nodeDetails, setNodeDetails] = useState(
    "<div class='text-slate-500'>Click a node to inspect it.</div>"
  );
  const [searchQ, setSearchQ] = useState("");
  const [statusMsg, setStatusMsg] = useState("");

  useEffect(() => {
    const options = {
      nodes: { shape: "ellipse", size: 16, font: { multi: "html" } },
      edges: {
        arrows: { to: { enabled: true, scaleFactor: 0.45 } },
        smooth: { enabled: true },
      },
      physics: { enabled: false },
      interaction: { hover: true, navigationButtons: true },
    };

    netRef.current = new Network(
      containerRef.current,
      { nodes: nodesRef.current, edges: edgesRef.current },
      options
    );

    netRef.current.on("click", async (params) => {
      if (params.nodes && params.nodes.length) {
        const nid = params.nodes[0];
        // fetch node details from the server route
        try {
          const resp = await fetch(`${API_BASE}/kg/node/${encodeURIComponent(nid)}`);
          if (resp.ok) {
            const json = await resp.json();
            const n = json.node || nodesRef.current.get(nid);
            const edges = json.edges || [];
            setNodeDetails(renderNodeDetailsFromServer(n, edges));
            netRef.current.focus(nid, { scale: 1.2, animation: { duration: 300 } });
          } else {
            // fallback to local node info
            const n = nodesRef.current.get(nid);
            setNodeDetails(renderNodeDetails(n));
          }
        } catch (err) {
          console.error("failed to fetch node", err);
          const n = nodesRef.current.get(nid);
          setNodeDetails(renderNodeDetails(n));
        }
      } else {
        setNodeDetails("<div class='text-slate-500'>Click a node to inspect it.</div>");
      }
    });

    loadGraph();

    const handleResize = () => netRef.current && netRef.current.redraw();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  function renderNodeDetails(n) {
    if (!n) return "<div class='text-slate-500'>No details available.</div>";
    let html = `<div class=\"space-y-2\">`;
    html += `<div class=\"flex items-center gap-2\"><div class=\"text-lg font-semibold\">${escapeHtml(n.label || n.id)}</div> <div class=\"text-xs text-slate-400\">(${escapeHtml(n.type || "—")})</div></div>`;
    html += `<pre class=\"whitespace-pre-wrap text-xs bg-slate-50 dark:bg-slate-800 p-2 rounded\">${escapeHtml(JSON.stringify(n, null, 2))}</pre>`;
    html += `</div>`;
    return html;
  }

  function renderNodeDetailsFromServer(node, edges = []) {
    if (!node) return "<div class='text-slate-500'>No details available.</div>";
    let html = `<div class=\"space-y-2\">`;
    html += `<div class=\"flex items-center gap-2\"><div class=\"text-lg font-semibold\">${escapeHtml(node.label || node.id)}</div> <div class=\"text-xs text-slate-400\">(${escapeHtml(node.type || node.meta?.type || "—")})</div></div>`;

    if (node.meta && Object.keys(node.meta).length) {
      html += `<div class=\"text-sm text-slate-600 dark:text-slate-300\">Meta:</div>`;
      html += `<pre class=\"whitespace-pre-wrap text-xs bg-slate-50 dark:bg-slate-800 p-2 rounded\">${escapeHtml(JSON.stringify(node.meta, null, 2))}</pre>`;
    }

    if (edges && edges.length) {
      html += `<div class=\"text-sm text-slate-600 dark:text-slate-300\">Connected edges:</div>`;
      html += `<ul class=\"text-xs list-disc pl-5\">`;
      edges.slice(0, 20).forEach((e) => {
        html += `<li>${escapeHtml(e.type)} — ${escapeHtml(e.source)} → ${escapeHtml(e.target)}${e.weight ? ` (w=${e.weight})` : ""}</li>`;
      });
      html += `</ul>`;
    }

    html += `</div>`;
    return html;
  }

  // small helper to avoid accidental HTML injection from node labels (keeps innerHTML usage)
  function escapeHtml(str = "") {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  async function loadGraph() {
    setStatusMsg("Loading graph...");
    try {
      const resp = await fetch(`${API_BASE}/kg/graph`);
      if (!resp.ok) throw new Error(`status ${resp.status}`);
      const json = await resp.json();
      const { nodes = [], edges = [] } = json;
      const { nodeList, edgeList } = buildGraphFromServer(nodes, edges);
      nodesRef.current.clear();
      edgesRef.current.clear();
      if (nodeList.length) nodesRef.current.add(nodeList);
      if (edgeList.length) edgesRef.current.add(edgeList);
      netRef.current.fit({ animation: { duration: 400 } });
      setStatusMsg(`Loaded ${nodeList.length} nodes, ${edgeList.length} edges`);
    } catch (err) {
      console.error("Failed to load graph", err);
      setStatusMsg("Failed to load graph");
    }
  }

  function buildGraphFromServer(nodes = [], edges = []) {
    const nodeList = nodes.map((n) => ({
      id: n.id,
      label: n.label || n.id,
      type: n.type,
      meta: n.meta || {},
      // allow server to provide x/y but don't require it
      x: n.x,
      y: n.y,
    }));

    const edgeList = edges.map((e, idx) => ({
      id: `e:${idx}`,
      from: e.source,
      to: e.target,
      label: e.type,
      width: e.weight ? Math.max(1, Math.round(e.weight * 4)) : 1,
      arrows: "to",
    }));

    // degree-based sizing & simple styling
    const degree = {};
    edgeList.forEach((e) => {
      degree[e.from] = (degree[e.from] || 0) + 1;
      degree[e.to] = (degree[e.to] || 0) + 1;
    });

    const typeColor = {
      Ticket: "#ffb86b",
      Technician: "#90be6d",
      Category: "#a0c4ff",
      RootCause: "#ffd6a5",
      Asset: "#cdd9e8",
      Step: "#8ecae6",
      Client: "#c7f9cc",
      Impact: "#ffd6a5",
    };

    nodeList.forEach((n) => {
      const d = degree[n.id] || 0;
      const size = 14 + Math.min(18, Math.sqrt(d) * 3);
      n.size = size;
      n.color = { background: typeColor[n.type] || "#ddd", border: "#333" };
      n.font = { size: Math.max(12, Math.min(16, Math.round(size / 1.2))) };
      if (n.label && n.label.length > 60) n.label = n.label.slice(0, 56) + "…";
    });

    // if server didn't provide positions, do a light grid so graph is readable before any layout
    const total = nodeList.length;
    if (total > 0 && !nodeList.some((n) => typeof n.x === "number")) {
      const cols = Math.ceil(Math.sqrt(total));
      const rows = Math.ceil(total / cols);
      const spacing = Math.max(80, Math.min(200, Math.round(1800 / Math.sqrt(Math.max(1, total)))));
      const startX = -((cols - 1) * spacing) / 2;
      const startY = -((rows - 1) * spacing) / 2;
      nodeList.forEach((n, idx) => {
        const col = idx % cols;
        const row = Math.floor(idx / cols);
        n.x = startX + col * spacing;
        n.y = startY + row * spacing;
      });
    }

    return { nodeList, edgeList };
  }

  async function doSearch(q) {
    if (!q) return;
    setStatusMsg(`Searching for \"${q}\"...`);
    try {
      const resp = await fetch(`${API_BASE}/kg/nodes/search?q=${encodeURIComponent(q)}&top_k=10`);
      if (!resp.ok) throw new Error(`status ${resp.status}`);
      const json = await resp.json();
      const hits = json.hits || [];
      if (!hits.length) {
        setStatusMsg(`No nodes matched \"${q}\"`);
        return;
      }
      // focus the first match and show details
      const nid = hits[0].id;
      netRef.current.focus(nid, { scale: 1.2, animation: { duration: 400 } });
      // optionally select the node
      try {
        netRef.current.selectNodes([nid]);
      } catch (e) {
        // selectNodes may not exist in some versions; ignore
      }
      // fetch server-side node info to display
      const nodeResp = await fetch(`${API_BASE}/kg/node/${encodeURIComponent(nid)}`);
      if (nodeResp.ok) {
        const nodeJson = await nodeResp.json();
        setNodeDetails(renderNodeDetailsFromServer(nodeJson.node, nodeJson.edges));
      } else {
        const local = nodesRef.current.get(nid);
        setNodeDetails(renderNodeDetails(local));
      }
      setStatusMsg(`Found ${hits.length} match(es)`);
    } catch (err) {
      console.error("search failed", err);
      setStatusMsg("Search failed");
    }
  }

  async function doRefresh() {
    setStatusMsg("Refreshing KB... (this may take a moment)");
    try {
      const resp = await fetch(`${API_BASE}/kg/refresh`, { method: "POST" });
      if (!resp.ok) throw new Error(`status ${resp.status}`);
      const json = await resp.json();
      await loadGraph();
      setStatusMsg(`Refresh complete: ${json.count || json.kg_nodes || 0} tickets`);
    } catch (err) {
      console.error("refresh failed", err);
      setStatusMsg("Refresh failed");
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-[#0f1724] text-slate-900 dark:text-slate-100 p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Knowledge Graph</h1>
        <div className="text-sm text-slate-500">Visualize ticket relationships</div>
      </div>

      <div className="flex gap-6">
        {/* Graph Card */}
        <div className="flex-1 bg-white dark:bg-slate-800 rounded-2xl shadow-md overflow-hidden">
          <div className="p-4 border-b border-slate-100 dark:border-slate-700 flex items-center justify-between">
            <div className="font-semibold">Tickets Graph</div>
            <div className="flex items-center gap-2">
              <input
                value={searchQ}
                onChange={(e) => setSearchQ(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && doSearch(searchQ)}
                placeholder="Search nodes..."
                className="text-sm px-2 py-1 rounded border"
                style={{ width: 220 }}
              />
              <button
                className="text-sm px-3 py-1 rounded bg-indigo-600 text-white"
                onClick={() => doSearch(searchQ)}
              >
                Search
              </button>
              <button
                className="text-sm px-3 py-1 rounded border"
                onClick={() => loadGraph()}
                title="Reload graph from /kg/graph"
              >
                Reload
              </button>
              <button
                className="text-sm px-3 py-1 rounded border"
                onClick={() => doRefresh()}
                title="Force refresh server KB (/kg/refresh)"
              >
                Refresh KB
              </button>
            </div>
          </div>

          <div style={{ height: "80vh", padding: 12 }}>
            <div
              ref={containerRef}
              style={{ height: "100%", borderRadius: 12, background: "transparent" }}
            />
          </div>
        </div>

        {/* Details Panel */}
        <aside className="w-96">
          <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-md p-6 sticky top-8">
            <h2 className="font-semibold text-lg mb-3">Node details</h2>
            <div
              className="prose prose-sm text-slate-700 dark:prose-invert dark:text-slate-300 text-sm"
              dangerouslySetInnerHTML={{ __html: nodeDetails }}
            />
            <div className="mt-4 text-xs text-slate-500">{statusMsg}</div>
            <div className="mt-4">
              <button
                className="w-full px-3 py-2 rounded-lg bg-indigo-600 text-white text-sm hover:bg-indigo-700 transition"
                onClick={() => {
                  netRef.current && netRef.current.fit({ animation: { duration: 400 } });
                }}
              >
                Recenter graph
              </button>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
