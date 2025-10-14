import React, { useEffect, useRef, useState } from "react";
import { Network } from "vis-network/standalone";
import { DataSet } from "vis-data/peer";

// KnowledgeGraph — single-file, split-structured React component.
// This updated version contains defensive checks to avoid creating vis.Network
// with a null container (fixes the `hasChildNodes` / `reading 'hasChildNodes'` error)
// and correctly wires the microscope DOM ref into the microscope network creation.

const API_BASE = "http://localhost:5000";

// -----------------------
// Utility helpers
// -----------------------
function formatDateShort(iso) {
  if (!iso) return "unknown time";
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return String(iso);
  }
}

function shortList(arr = [], limit = 3) {
  if (!Array.isArray(arr) || arr.length === 0) return "";
  if (arr.length <= limit) return arr.join(", ");
  return arr.slice(0, limit).join(", ") + ` (and ${arr.length - limit} more)`;
}

function relationSummary(edges = []) {
  if (!edges || edges.length === 0) return "";
  const counts = {};
  edges.forEach((e) => {
    counts[e.type] = (counts[e.type] || 0) + 1;
  });
  const parts = Object.keys(counts).map((k) => `${counts[k]} ${k.replace(/_/g, " ")}`);
  return parts.join(", ");
}

function extractFirstSteps(ticket) {
  if (!ticket) return [];
  const steps = [];
  if (Array.isArray(ticket.resolutionSteps)) steps.push(...ticket.resolutionSteps);
  for (const k of ["worklog", "work_logs", "logs"]) {
    const val = ticket[k];
    if (Array.isArray(val)) {
      for (const entry of val) {
        if (typeof entry === "string") steps.push(entry);
        else if (entry && (entry.text || entry.note || entry.description)) steps.push(entry.text || entry.note || entry.description);
      }
    }
  }
  if (ticket.resolution && typeof ticket.resolution === "string") steps.push(ticket.resolution);
  return steps.map((s) => String(s)).filter(Boolean).slice(0, 8);
}

function buildNaturalSummary(node, edges = []) {
  if (!node) {
    return { title: "No selection", paragraphs: ["Click a node to inspect it."] };
  }
  const type = node.type || node.meta?.type || "Unknown";
  const label = node.label || node.id || "Unnamed";
  const paragraphs = [];

  if (type.toLowerCase() === "ticket" || type === "Ticket") {
    const t = node.meta?.ticket || node.meta || {};
    const subject = t.subject || t.title || label;
    const status = t.status || "Unknown";
    const priority = t.priority || "Normal";
    const client = (t.client && (t.client.name || t.client)) || t.client || "Unknown client";
    const site = (t.site && (t.site.name || t.site)) || t.site || "Unknown site";
    const tech = (t.technician && (t.technician.name || t.technician)) || t.technician || "Unassigned";
    const created = formatDateShort(t.createdTime || t.createdAt || t.created);
    const impact = t.impact || t.severity || "N/A";

    paragraphs.push(`Ticket "${subject}" — status: ${status}, priority: ${priority}, impact: ${impact}.`);
    paragraphs.push(`Created: ${created}. Client / site: ${client} / ${site}. Assigned technician: ${tech}.`);

    const steps = extractFirstSteps(t);
    if (steps.length) {
      paragraphs.push(`Known resolution notes: ${shortList(steps, 4)}.`);
    }

    const relSummary = relationSummary(edges);
    if (relSummary) paragraphs.push(`Connected: ${relSummary}.`);
    return { title: `${subject}`, paragraphs };
  }

  if (type.toLowerCase() === "technician" || type === "Technician") {
    const name = node.label || node.meta?.name || "Technician";
    const resolved = edges.filter((e) => e.type === "resolved").length;
    paragraphs.push(`${name} is a technician linked to ${resolved} ticket(s).`);
    const ticketIds = edges
      .filter((e) => e.type === "resolved" || e.type === "similar_to" || e.type === "client_site")
      .map((e) => (e.source === node.id ? e.target : e.source));
    if (ticketIds.length) paragraphs.push(`Examples: ${shortList(ticketIds, 6)}.`);
    return { title: name, paragraphs };
  }

  if (type.toLowerCase() === "category" || type === "Category") {
    paragraphs.push(`Category: ${node.label || "—"}. Use the microscope to inspect sample tickets and common root causes.`);
    const related = edges.filter((e) => e.type === "category").map((e) => (e.source === node.id ? e.target : e.source));
    if (related.length) paragraphs.push(`Example tickets: ${shortList(related, 6)}.`);
    return { title: node.label || "Category", paragraphs };
  }

  if (type.toLowerCase() === "step" || type === "Step") {
    const stepText = node.meta?.step || node.label || "";
    paragraphs.push(`Resolution step: ${stepText}`);
    const usedIn = edges.filter((e) => e.type === "step").map((e) => (e.source === node.id ? e.target : e.source));
    if (usedIn.length) paragraphs.push(`Used by tickets: ${shortList(usedIn, 6)}.`);
    return { title: node.label || "Step", paragraphs };
  }

  // Generic fallback
  paragraphs.push(`Type: ${type}`);
  const metaString = JSON.stringify(node.meta || {}, null, 2);
  if (metaString && metaString !== "{}") {
    paragraphs.push(`Metadata: ${metaString}`);
  }
  const relSummary = relationSummary(edges);
  if (relSummary) paragraphs.push(`Connected: ${relSummary}.`);
  return { title: node.label || node.id || "Node", paragraphs };
}

// -----------------------
// Subcomponents
// -----------------------
function TopBar({ searchQ, setSearchQ, onSearch, onReload, onRefresh }) {
  return (
    <div className="p-4 border-b border-slate-800 flex items-center justify-between">
      <div className="font-semibold text-lg">Tickets Graph</div>

      <div className="flex items-center gap-2">
        <input
          value={searchQ}
          onChange={(e) => setSearchQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSearch(searchQ)}
          placeholder="Search nodes..."
          className="text-sm px-3 py-2 rounded border border-slate-700 bg-[#071421] placeholder-slate-500"
          style={{ width: 260 }}
        />
        <button className="text-sm px-3 py-2 rounded bg-indigo-600 text-white shadow" onClick={() => onSearch(searchQ)}>Search</button>
        <button className="text-sm px-3 py-2 rounded border border-slate-700" onClick={onReload} title="Reload graph from /kg/graph">Reload</button>
        <button className="text-sm px-3 py-2 rounded border border-slate-700" onClick={onRefresh} title="Force refresh server KB (/kg/refresh)">Refresh KB</button>
      </div>
    </div>
  );
}

function LegendControls({ onFit, onRestabilize, clusteringEnabled, onToggleCluster }) {
  return (
    <div className="absolute top-5 left-6 bg-black/40 backdrop-blur rounded-md p-3 text-xs z-20">
      <div className="flex items-center gap-3 mb-1">
        <div className="w-3 h-3 rounded-full" style={{ background: '#ffb86b' }} /> <span>Ticket</span>
      </div>
      <div className="flex items-center gap-3 mb-1">
        <div className="w-3 h-3 rounded-full" style={{ background: '#90be6d' }} /> <span>Technician</span>
      </div>
      <div className="flex items-center gap-3 mb-1">
        <div className="w-3 h-3 rounded-full" style={{ background: '#a0c4ff' }} /> <span>Category</span>
      </div>

      <div className="mt-2 flex gap-2">
        <button className="px-2 py-1 rounded bg-slate-800/60 text-xs" onClick={onFit}>Fit</button>
        <button className="px-2 py-1 rounded bg-slate-800/60 text-xs" onClick={onRestabilize}>Re-stabilize</button>
        <button className="px-2 py-1 rounded bg-slate-800/60 text-xs" onClick={onToggleCluster}>{clusteringEnabled ? 'Uncluster' : 'Cluster'}</button>
      </div>
    </div>
  );
}

function Sidebar({ selectedNode, selectedEdges, selectedNodeId, onOpenMicroscope, onZoomToNode, microscopeDepth, setMicroscopeDepth, microscopeNodeCountLimit, setMicroscopeNodeCountLimit, statusMsg }) {
  const summary = buildNaturalSummary(selectedNode, selectedEdges);

  return (
    <aside className="w-96">
      <div className="bg-gradient-to-b from-[#071421] to-[#071629] rounded-2xl shadow-lg p-6 sticky top-8">
        <h2 className="font-semibold text-lg mb-3">Node details</h2>

        <div className="mb-3">
          <div className="text-lg font-semibold">{summary.title}</div>
          <div className="text-xs text-slate-400 mb-2">{selectedNode ? selectedNode.type : ''}</div>
          {summary.paragraphs.map((p, i) => (
            <div key={i} className="text-sm text-slate-300 mb-2 break-words whitespace-pre-wrap">{p}</div>
          ))}
        </div>

        <div className="mt-2">
          <div className="flex gap-2">
            <button className="px-3 py-2 rounded-lg bg-indigo-600 text-white flex-1 text-sm" onClick={onOpenMicroscope}>Open Microscope</button>
            <button className="px-3 py-2 rounded-lg border text-sm" onClick={onZoomToNode}>Zoom</button>
          </div>

          <div className="mt-3 text-xs text-slate-400">Status: {statusMsg}</div>

          <div className="mt-4 text-xs">
            <label className="mr-2">Depth</label>
            <select value={microscopeDepth} onChange={(e) => setMicroscopeDepth(Number(e.target.value))} className="text-xs rounded border px-2 py-1 bg-[#071421]">
              <option value={1}>1</option>
              <option value={2}>2</option>
            </select>

            <label className="ml-3 mr-2">Limit</label>
            <input type="number" value={microscopeNodeCountLimit} onChange={(e) => setMicroscopeNodeCountLimit(Number(e.target.value || 120))} className="text-xs rounded border px-2 py-1 w-20 bg-[#071421]" />
          </div>
        </div>

        <div className="mt-6">
          <h4 className="text-sm font-medium mb-2">Connected edges (sample)</h4>
          <div className="text-xs max-h-48 overflow-auto">
            {selectedEdges.length ? (
              <ul className="list-disc pl-5">
                {selectedEdges.slice(0, 50).map((e, idx) => (
                  <li key={idx}>
                    <span className="font-medium">{e.type}</span> — {e.source} → {e.target} {e.weight ? `(w=${e.weight})` : ""}
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-slate-500">No connected edges to display.</div>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}

function MicroscopeModal({ isOpen, onClose, centerNodeId, microscopeContainerRef, microscopeNodesRef, microscopeEdgesRef, microscopeNetRef, microscopeLoading, microscopeDepth, microscopeNodeCountLimit, setMicroscopeDepth, setMicroscopeNodeCountLimit, onSelectNode, startMicroscope }) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-60 flex items-start justify-center bg-black/70 p-6 overflow-auto">
      <div className="w-full max-w-6xl bg-gradient-to-b from-[#071421] to-[#071629] rounded-2xl p-4 relative border border-slate-800 shadow-2xl">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <h3 className="text-lg font-semibold">Microscope View</h3>
            <div className="text-sm text-slate-400">Centered on {centerNodeId || "—"}</div>
            {microscopeLoading && <div className="text-xs text-slate-400 ml-2">Loading…</div>}
          </div>

          <div className="flex items-center gap-2">
            <button className="px-2 py-1 rounded border text-sm" onClick={() => centerNodeId && startMicroscope(centerNodeId)}>Refresh</button>

            <button
              className="px-2 py-1 rounded border text-sm"
              onClick={() => {
                const data = { nodes: microscopeNodesRef.current.get(), edges: microscopeEdgesRef.current.get() };
                const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `microscope_${centerNodeId || "graph"}.json`;
                a.click();
                URL.revokeObjectURL(url);
              }}
            >
              Export JSON
            </button>

            <button className="px-2 py-1 rounded bg-red-600 text-white text-sm" onClick={() => { onClose(); }}>
              Close
            </button>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div className="col-span-2" style={{ minHeight: 480 }}>
            {/* assign the real DOM node to microscopeContainerRef so startMicroscope can create Network */}
            <div ref={microscopeContainerRef} style={{ height: "480px", borderRadius: 8 }} />
          </div>

          <div className="col-span-1">
            <div className="bg-slate-900/40 p-3 rounded">
              <h4 className="text-sm font-medium mb-2">Selected node</h4>
              <div className="text-sm mb-3">{centerNodeId || <span className="text-slate-400">None selected</span>}</div>

              <h4 className="text-sm font-medium mb-2">Controls</h4>
              <div className="flex flex-col gap-2">
                <label className="text-xs">Depth</label>
                <select value={microscopeDepth} onChange={(e) => setMicroscopeDepth(Number(e.target.value))} className="text-xs rounded border px-2 py-1 bg-[#071421]">
                  <option value={1}>1</option>
                  <option value={2}>2</option>
                </select>

                <label className="text-xs mt-2">Node limit</label>
                <input type="number" value={microscopeNodeCountLimit} onChange={(e) => setMicroscopeNodeCountLimit(Number(e.target.value || 120))} className="text-xs rounded border px-2 py-1 w-full bg-[#071421]" />

                <button className="mt-3 px-3 py-2 bg-indigo-600 text-white rounded text-sm" onClick={() => centerNodeId && startMicroscope(centerNodeId)}>Rebuild Microscope</button>
              </div>

              <div className="mt-4">
                <h5 className="text-xs font-medium">Connected nodes</h5>
                <div className="text-xs mt-1 max-h-48 overflow-auto">
                  <ul>
                    {microscopeNodesRef.current.get().slice(0, 200).map((n) => (
                      <li key={n.id} className="py-1">
                        <button className="text-left text-xs underline" onClick={() => { try { microscopeNetRef.current && microscopeNetRef.current.focus(n.id, { scale: 1.2, animation: { duration: 200 } }); } catch { }; onSelectNode(n.id); }}>
                          {n.label}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>

            <div className="mt-3 text-xs text-slate-400">Tip: use the microscope to inspect a small subgraph (depth 1 or 2). Export JSON for offline analysis.</div>
          </div>
        </div>
      </div>
    </div>
  );
}

// -----------------------
// Main KnowledgeGraph
// -----------------------
export default function KnowledgeGraph() {
  const containerRef = useRef(null);
  const netRef = useRef(null);
  const nodesRef = useRef(new DataSet());
  const edgesRef = useRef(new DataSet());

  // microscope refs
  const microscopeContainerRef = useRef(null);
  const microscopeNetRef = useRef(null);
  const microscopeNodesRef = useRef(new DataSet());
  const microscopeEdgesRef = useRef(new DataSet());

  // app state
  const [statusMsg, setStatusMsg] = useState("");
  const [searchQ, setSearchQ] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [selectedEdges, setSelectedEdges] = useState([]);
  const [microscopeOpen, setMicroscopeOpen] = useState(false);
  const [microscopeLoading, setMicroscopeLoading] = useState(false);
  const [microscopeDepth, setMicroscopeDepth] = useState(1);
  const [microscopeNodeCountLimit, setMicroscopeNodeCountLimit] = useState(120);
  const [clusteringEnabled, setClusteringEnabled] = useState(true);

  // build graph from server payload
  function buildGraphFromServer(nodes = [], edges = []) {
    const nodeList = nodes.map((n) => ({
      id: n.id,
      label: n.label || n.id,
      type: n.type,
      meta: n.meta || {},
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
      title: e.type,
    }));

    // degree-based sizing & styling
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
      const d = Math.max(12, Math.min(32, 14 + Math.min(18, Math.sqrt(degree[n.id] || 0) * 3)));
      n.size = d;
      n.color = { background: typeColor[n.type] || "#ddd", border: "#222" };
      n.font = { size: Math.max(12, Math.min(16, Math.round(d / 1.2))) };
      if (n.label && n.label.length > 50) n.label = n.label.slice(0, 46) + "…";
      n.title = `<div style=\"padding:8px;max-width:340px;line-height:1.2\"><strong>${(n.label || n.id)}</strong><div style=\"font-size:12px;color:#999;margin-top:6px\">Type: ${n.type || '—'}</div><pre style=\"white-space:pre-wrap;font-size:12px;color:#888;margin-top:6px\">${JSON.stringify(n.meta || {}, null, 2).slice(0, 300)}</pre></div>`;
    });

    return { nodeList, edgeList };
  }

  // =========================
  // Node selection / details
  // =========================
  async function handleSelectNode(nid) {
    setSelectedNodeId(nid);
    setStatusMsg("Loading node details...");
    if (!nid) {
      setSelectedNode(null);
      setSelectedEdges([]);
      return;
    }
    try {
      const resp = await fetch(`${API_BASE}/kg/node/${encodeURIComponent(nid)}`);
      if (!resp.ok) {
        const local = nodesRef.current.get(nid);
        setSelectedNode(local || null);
        setSelectedEdges([]);
        setStatusMsg("Node details loaded (local cached).");
        return;
      }
      const json = await resp.json();
      setSelectedNode(json.node || nodesRef.current.get(nid) || null);
      setSelectedEdges(json.edges || []);
      setStatusMsg("Node details loaded.");
    } catch (err) {
      console.error("failed to fetch node", err);
      const local = nodesRef.current.get(nid);
      setSelectedNode(local || null);
      setSelectedEdges([]);
      setStatusMsg("Node details loaded (local cache).");
    }
  }

  // =========================
  // Load graph (main)
  // =========================
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

      try {
        if (netRef.current) {
          try { netRef.current.stabilize(); } catch (e) { }
          try { netRef.current.fit({ animation: { duration: 400 } }); } catch (e) { }
        }
      } catch { }

      setStatusMsg(`Loaded ${nodeList.length} nodes, ${edgeList.length} edges`);

      // optional clustering to reduce visual clutter
      setTimeout(() => {
        if (clusteringEnabled) clusterLowDegreeNodes();
      }, 800);
    } catch (err) {
      console.error("Failed to load graph", err);
      setStatusMsg("Failed to load graph");
    }
  }

  async function doSearch(q) {
    if (!q) return;
    setStatusMsg(`Searching for "${q}"...`);
    try {
      const resp = await fetch(`${API_BASE}/kg/nodes/search?q=${encodeURIComponent(q)}&top_k=10`);
      if (!resp.ok) throw new Error(`status ${resp.status}`);
      const json = await resp.json();
      const hits = json.hits || [];
      if (!hits.length) {
        setStatusMsg(`No nodes matched "${q}"`);
        return;
      }
      const nid = hits[0].id;
      try { netRef.current && netRef.current.selectNodes([nid]); netRef.current && netRef.current.focus(nid, { scale: 1.2, animation: { duration: 400 } }); } catch { }
      await handleSelectNode(nid);
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
      await loadGraph();
      setStatusMsg("Refresh complete");
    } catch (err) {
      console.error("refresh failed", err);
      setStatusMsg("Refresh failed");
    }
  }

  function clusterLowDegreeNodes() {
    if (!netRef.current) return;

    try {
      // if previously clustered, first open all
      try {
        netRef.current.openCluster('cluster:leaves');
      } catch (e) { }

      const clusterOptionsByData = {
        joinCondition: function (childOptions) {
          const nd = nodesRef.current.get(childOptions.id);
          const degree = nd?.meta?.degree || 0;
          // cluster true leaf nodes (low-degree) but not cluster center nodes
          return degree <= 1 && !(childOptions.isCluster);
        },
        clusterNodeProperties: {
          id: 'cluster:leaves',
          label: 'Leaf nodes',
          borderWidth: 2,
          shape: 'dot',
          color: { background: '#1f2937', border: '#8b5cf6' },
        },
      };

      netRef.current.cluster(clusterOptionsByData);
    } catch (err) {
      console.warn('clustering failed', err);
    }
  }

  function toggleClustering() {
    if (!netRef.current) return;
    const enabled = !clusteringEnabled;
    setClusteringEnabled(enabled);
    if (enabled) clusterLowDegreeNodes();
    else {
      try {
        netRef.current.getClusters().forEach((c) => {
          try { netRef.current.openCluster(c); } catch { }
        });
      } catch (e) { }
    }
  }

  // =========================
  // Microscope (subgraph) logic
  // =========================
  async function startMicroscope(centerNodeId) {
    if (!centerNodeId) return;
    setMicroscopeOpen(true);
    setMicroscopeLoading(true);

    // Clear previous microscope sets
    microscopeNodesRef.current.clear();
    microscopeEdgesRef.current.clear();

    const maxNodes = Number(microscopeNodeCountLimit) || 120;
    const seen = new Set();
    const queue = [{ id: centerNodeId, depth: 0 }];

    // Use maps to dedupe by id
    const nodesMap = new Map();
    const edgesMap = new Map();

    while (queue.length > 0 && nodesMap.size < maxNodes) {
      const item = queue.shift();
      const id = item.id;
      const depth = item.depth;
      if (seen.has(id)) continue;
      seen.add(id);

      try {
        const resp = await fetch(`${API_BASE}/kg/node/${encodeURIComponent(id)}`);
        if (!resp.ok) {
          console.warn("microscope: node fetch failed", id, resp.status);
          continue;
        }
        const json = await resp.json();
        const node = json.node;
        const edges = json.edges || [];

        // add/update node in nodesMap
        if (node && node.id) {
          const label = node.label || node.id;
          nodesMap.set(node.id, {
            id: node.id,
            label: label,
            type: node.type,
            meta: node.meta || {},
          });
        }

        // process edges
        for (const e of edges) {
          const safeType = String(e.type || "").replace(/\s+/g, "_");
          const edgeId = `e:${String(e.source)}::${String(e.target)}::${safeType}`;
          if (!edgesMap.has(edgeId)) {
            edgesMap.set(edgeId, {
              id: edgeId,
              from: e.source,
              to: e.target,
              label: e.type,
              width: e.weight ? Math.max(1, Math.round(e.weight * 4)) : 1,
              arrows: "to",
            });
          }

          // enqueue neighbor
          if (depth + 1 <= microscopeDepth) {
            const neighborId = e.source === node.id ? e.target : e.source;
            if (!seen.has(neighborId) && nodesMap.size < maxNodes) {
              queue.push({ id: neighborId, depth: depth + 1 });
            }
          }
        }
      } catch (err) {
        console.error("microscope fetch error for", id, err);
      }
    }

    const nodesToAdd = Array.from(nodesMap.values());
    const edgesToAdd = Array.from(edgesMap.values());

    try {
      if (nodesToAdd.length) microscopeNodesRef.current.update(nodesToAdd);
      if (edgesToAdd.length) microscopeEdgesRef.current.update(edgesToAdd);
    } catch (dsErr) {
      console.warn("microscope: DataSet update error (falling back to add with guards)", dsErr);
      for (const n of nodesToAdd) {
        try {
          if (!microscopeNodesRef.current.get(n.id)) microscopeNodesRef.current.add(n);
        } catch (e) { }
      }
      for (const ed of edgesToAdd) {
        try {
          if (!microscopeEdgesRef.current.get(ed.id)) microscopeEdgesRef.current.add(ed);
        } catch (e) { }
      }
    }

    setMicroscopeLoading(false);

    // small timeout to ensure modal DOM ref is mounted before creating the network
    setTimeout(() => {
      try {
        if (microscopeNetRef.current) {
          try { microscopeNetRef.current.destroy(); } catch (dErr) { console.warn(dErr); }
          microscopeNetRef.current = null;
        }
      } catch (dErr) { console.warn("microscope destroy error", dErr); }

      // guard: ensure DOM container exists
      if (!microscopeContainerRef.current) {
        console.warn("microscope container not ready, aborting network creation");
        return;
      }

      const options = {
        nodes: { shape: "dot", size: 12, font: { multi: "html" }, scaling: { min: 8, max: 36 }, borderWidth: 1 },
        edges: { arrows: { to: { enabled: true, scaleFactor: 0.6 } }, smooth: { enabled: true } },
        physics: { enabled: true, stabilization: { enabled: true, iterations: 200 } },
        interaction: { hover: true, navigationButtons: true, multiselect: true },
      };

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

      microscopeNodesRef.current.get().forEach((n) => {
        const deg = (n.meta && n.meta.degree) ? n.meta.degree : 0;
        const size = Math.max(10, Math.min(34, 12 + Math.sqrt(deg || 0) * 3));
        try {
          microscopeNodesRef.current.update({
            id: n.id,
            label: n.label && n.label.length > 40 ? n.label.slice(0, 36) + "…" : n.label,
            size,
            title: `<div style=\"padding:6px;max-width:300px\"><strong>${(n.label || n.id)}</strong><div style=\"font-size:12px;margin-top:6px;color:#888\">${JSON.stringify(n.meta || {}, null, 2).slice(0, 200)}...</div></div>`,
            color: { background: typeColor[n.type] || "#ddd", border: "#222" },
          });
        } catch (uErr) { }
      });

      try {
        microscopeNetRef.current = new Network(microscopeContainerRef.current, { nodes: microscopeNodesRef.current, edges: microscopeEdgesRef.current }, options);

        microscopeNetRef.current.on("click", async (params) => {
          if (params.nodes && params.nodes.length) {
            const nid = params.nodes[0];
            await handleSelectNode(nid);
          }
        });

        setTimeout(() => { try { microscopeNetRef.current.fit({ animation: { duration: 400 } }); } catch (e) { } }, 300);
      } catch (netErr) {
        console.error("failed creating microscope network", netErr);
      }
    }, 50);
  }

  // -----------------------
  // initialize main network safely
  // -----------------------
  useEffect(() => {
    // guard for container
    if (!containerRef.current) return;

    // destroy previous network if present (useful in React StrictMode & hot reload)
    try {
      if (netRef.current) {
        try { netRef.current.destroy(); } catch (dErr) { console.warn(dErr); }
        netRef.current = null;
      }
    } catch (e) { console.warn("network destroy warning", e); }

    const options = {
      nodes: { shape: "dot", size: 14, font: { multi: "html", size: 14, face: 'Inter, system-ui' }, scaling: { min: 8, max: 36 }, borderWidth: 1 },
      edges: { arrows: { to: { enabled: true, scaleFactor: 0.5 } }, smooth: { type: "continuous" }, width: 1, color: { color: "rgba(255,255,255,0.06)", highlight: "rgba(255,255,255,0.12)" } },
      physics: { enabled: true, barnesHut: { gravitationalConstant: -2500, centralGravity: 0.15, springLength: 120, springConstant: 0.01, avoidOverlap: 0.9 }, stabilization: { enabled: true, iterations: 400, updateInterval: 25 } },
      interaction: { hover: true, navigationButtons: true, keyboard: true, multiselect: true, dragView: true, zoomView: true },
      layout: { improvedLayout: true },
    };

    try {
      // final guard before constructing
      if (!containerRef.current) return;
      netRef.current = new Network(containerRef.current, { nodes: nodesRef.current, edges: edgesRef.current }, options);

      netRef.current.on("stabilizationIterationsDone", () => {
        try { netRef.current.setOptions({ physics: { enabled: false } }); } catch (e) { }
      });

      netRef.current.on("click", async (params) => {
        if (params.nodes && params.nodes.length) {
          const nid = params.nodes[0];
          await handleSelectNode(nid);
          try { netRef.current.focus(nid, { scale: 1.3, animation: { duration: 300 } }); } catch { }
        } else {
          setSelectedNodeId(null);
          setSelectedNode(null);
          setSelectedEdges([]);
        }
      });

      const handleResize = () => netRef.current && netRef.current.redraw();
      window.addEventListener("resize", handleResize);
      return () => window.removeEventListener("resize", handleResize);
    } catch (err) {
      console.error("failed creating main network", err);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // initial load
  useEffect(() => { loadGraph(); }, []);

  // expose a small API for UI buttons
  const onFit = () => { try { netRef.current && netRef.current.fit({ animation: { duration: 400 } }); } catch { } };
  const onRestabilize = () => { try { netRef.current && netRef.current.setOptions({ physics: { enabled: true } }); netRef.current && netRef.current.stabilize(); } catch { } };
  const onReload = () => loadGraph();
  const onRefresh = () => doRefresh();

  return (
    <div className="min-h-screen bg-gradient-to-b from-[#071021] via-[#0b1220] to-[#071021] text-slate-100 p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-extrabold tracking-tight">Knowledge Graph</h1>
        <div className="text-sm text-slate-400">Visualize ticket relationships — {statusMsg}</div>
      </div>

      <div className="flex gap-6">
        {/* Graph Card */}
        <div className="flex-1 bg-gradient-to-br from-[#0f1724] to-[#0b1220] rounded-2xl shadow-2xl overflow-hidden relative">
          <TopBar
            searchQ={searchQ}
            setSearchQ={setSearchQ}
            onSearch={doSearch}
            onReload={onReload}
            onRefresh={onRefresh}
          />

          <LegendControls onFit={onFit} onRestabilize={onRestabilize} clusteringEnabled={clusteringEnabled} onToggleCluster={toggleClustering} />

          <div style={{ height: "80vh", padding: 12 }}>
            <div style={{ height: "100%", borderRadius: 12, background: 'linear-gradient(180deg, rgba(10,15,22,0.6), rgba(10,15,22,0.2))' }} ref={containerRef} />
          </div>
        </div>

        {/* Details & Microscope Panel */}
        <Sidebar
          selectedNode={selectedNode}
          selectedEdges={selectedEdges}
          selectedNodeId={selectedNodeId}
          onOpenMicroscope={() => { if (selectedNodeId) startMicroscope(selectedNodeId); else alert("Select a node on the graph first."); }}
          onZoomToNode={() => { if (selectedNodeId) { try { netRef.current && netRef.current.focus(selectedNodeId, { scale: 1.4, animation: { duration: 300 } }); } catch { } } else { alert("Select a node on the graph first."); } }}
          microscopeDepth={microscopeDepth}
          setMicroscopeDepth={setMicroscopeDepth}
          microscopeNodeCountLimit={microscopeNodeCountLimit}
          setMicroscopeNodeCountLimit={setMicroscopeNodeCountLimit}
          statusMsg={statusMsg}
        />
      </div>

      <MicroscopeModal
        isOpen={microscopeOpen}
        onClose={() => { setMicroscopeOpen(false); microscopeNodesRef.current.clear(); microscopeEdgesRef.current.clear(); try { if (microscopeNetRef.current) microscopeNetRef.current.destroy(); microscopeNetRef.current = null; } catch { } }}
        centerNodeId={selectedNodeId}
        microscopeContainerRef={microscopeContainerRef}
        microscopeNodesRef={microscopeNodesRef}
        microscopeEdgesRef={microscopeEdgesRef}
        microscopeNetRef={microscopeNetRef}
        microscopeLoading={microscopeLoading}
        microscopeDepth={microscopeDepth}
        microscopeNodeCountLimit={microscopeNodeCountLimit}
        setMicroscopeDepth={setMicroscopeDepth}
        setMicroscopeNodeCountLimit={setMicroscopeNodeCountLimit}
        onSelectNode={handleSelectNode}
        startMicroscope={startMicroscope}
      />
    </div>
  );
}
