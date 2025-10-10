import React, { useEffect, useRef, useState } from 'react';
import { Network } from 'vis-network/standalone';
import { DataSet } from 'vis-data/peer';

export default function App() {
  const containerRef = useRef(null);
  const netRef = useRef(null);
  const nodesRef = useRef(new DataSet());
  const edgesRef = useRef(new DataSet());
  const [tickets, setTickets] = useState([]);
  const [nodeDetails, setNodeDetails] = useState('Click a node to inspectit.');
  useEffect(() => {
    const options = {
      nodes: { shape: 'ellipse', size: 16 },
      edges: {
        arrows: { to: { enabled: true, scaleFactor: 0.45 } }, smooth:
          { enabled: true }
      },
      physics: { enabled: false },
      interaction: { hover: true, navigationButtons: true }
    };
    netRef.current = new Network(containerRef.current, {
      nodes:
        nodesRef.current, edges: edgesRef.current
    }, options);
    netRef.current.on('click', params => {
      if (params.nodes && params.nodes.length) {
        const nid = params.nodes[0];
        const n = nodesRef.current.get(nid);
        setNodeDetails(renderNodeDetails(n));
        netRef.current.focus(nid, {
          scale: 1.2, animation: {
            duration:
              300
          }
        });
      } else {
        setNodeDetails('Click a node to inspect it.');
      }
    });
    loadTickets();
    window.addEventListener('resize', () => netRef.current.redraw());
    return () => {
      window.removeEventListener('resize', () =>
        netRef.current.redraw());
    };
  }, []);
  function renderNodeDetails(n) {
    let html = `<div><strong>${n.label}</strong>`;
    if (n.type) html += ` <span>(${n.type})</span>`;
    html += `</div>`;
    if (n.type === 'Ticket') {
      html += `<div>Status: ${n.status || '—'}</div>`;
      if (n.priority) html += `<div>Priority: ${n.priority}</div>`;
      if (n.title) html += `<pre>${n.title}</pre>`;
    } else {
      html += `<pre>${JSON.stringify(n, null, 2)}</pre>`;
    }
    return html;
  }
  async function loadTickets() {
    try {
      const resp = await fetch('http://localhost:5000/tickets');
      const data = await resp.json();
      setTickets(data);
      const { nodeList, edgeList } = buildGraphFromTickets(data);
      nodesRef.current.clear();
      edgesRef.current.clear();
      if (nodeList.length) nodesRef.current.add(nodeList);
      if (edgeList.length) edgesRef.current.add(edgeList);
      netRef.current.fit({ animation: { duration: 400 } });
    } catch (err) {
      console.error('Failed to load tickets', err);
    }
  }
  function buildGraphFromTickets(tickets) {
    const nodeList = [];
    const edgeList = [];
    const seen = {
      tickets: new Set(), requesters: new Set(), technicians:
        new Set(), clients: new Set(), sites: new Set(), tech_groups: new Set()
    };
    tickets.forEach((t, idx) => {
      const tId = `ticket:${String(t.ticketId)}_${idx}`;
      if (!seen.tickets.has(tId)) {
        nodeList.push({
          id: tId, label: t.subject || t.ticketId, title:
            t.description || '', type: 'Ticket', status: t.status || '', priority:
            t.priority || ''
        });
        seen.tickets.add(tId);
      }
      const req = t.requester || {};
      const reqId = req.userId ? `requester:${req.userId}` : null;
      if (reqId && !seen.requesters.has(reqId)) {
        nodeList.push({
          id: reqId,
          label: req.name || req.userId, type: 'Requester'
        });
        seen.requesters.add(reqId);
      }
      if (reqId) edgeList.push({
        from: tId, to: reqId, label:
          'REQUESTED_BY'
      });
      const tech = t.technician || {};
      const techId = tech.userId ? `technician:${tech.userId}` : null;
      if (techId && !seen.technicians.has(techId)) {
        nodeList.push({
          id:
            techId, label: tech.name || tech.userId, type: 'Technician'
        });
        seen.technicians.add(techId);
      }
      if (techId) edgeList.push({
        from: tId, to: techId, label:
          'ASSIGNED_TO'
      });
      const client = t.client || {};
      const clientId = client.accountId ? `client:${client.accountId}` :
        null;
      if (clientId && !seen.clients.has(clientId)) {
        nodeList.push({
          id:
            clientId, label: client.name || client.accountId, type: 'Client'
        });
        seen.clients.add(clientId);
      }
      if (clientId) edgeList.push({
        from: tId, to: clientId, label:
          'FOR_CLIENT'
      });
      const site = t.site || {};
      const siteId = site.id ? `site:${site.id}` : null;
      if (siteId && !seen.sites.has(siteId)) {
        nodeList.push({
          id: siteId,
          label: site.name || site.id, type: 'Site'
        }); seen.sites.add(siteId);
      }
      if (siteId) edgeList.push({ from: tId, to: siteId, label: 'AT_SITE' });
      if (t.techGroup) {
        const g = t.techGroup;
        const gId = g.groupId ? `techgroup:${g.groupId}` : null;
        if (gId && !seen.tech_groups.has(gId)) {
          nodeList.push({
            id: gId,
            label: g.name || g.groupId, type: 'TechGroup'
          });
          seen.tech_groups.add(gId);
        }
        if (gId) edgeList.push({
          from: tId, to: gId, label:
            'HANDLED_BY_GROUP'
        });
      }
    });
    // simple degree-based sizing
    const degree = {};
    edgeList.forEach(e => {
      degree[e.from] = (degree[e.from] || 0) + 1;
      degree[e.to] = (degree[e.to] || 0) + 1;
    });
    const typeColor = {
      'Ticket': '#ffb86b', 'Requester': '#8ecae6',
      'Technician': '#90be6d', 'Client': '#a0c4ff', 'Site': '#cdd9e8',
      'TechGroup': '#ffd6a5'
    };
    nodeList.forEach(n => {
      const d = degree[n.id] || 0;
      const size = 14 + Math.min(18, Math.sqrt(d) * 3);
      n.size = size;
      n.color = { background: typeColor[n.type] || '#ddd', border: '#555' };
      n.font = { size: Math.max(12, Math.min(16, Math.round(size / 1.2))) };
      if (n.label && n.label.length > 40) n.label = n.label.slice(0, 36) +
        '…';
    });
    // compute grid positions
    const total = nodeList.length;
    if (total > 0) {
      const cols = Math.ceil(Math.sqrt(total));
      const rows = Math.ceil(total / cols);
      const spacing = Math.max(80, Math.min(200, Math.round(1800 /
        Math.sqrt(Math.max(1, total)))));
      const startX = -((cols - 1) * spacing) / 2;
      const startY = -((rows - 1) * spacing) / 2;
      nodeList.forEach((n, idx) => {
        const col = idx % cols;
        const row = Math.floor(idx / cols);
        n.x = startX + col * spacing;
        n.y = startY + row * spacing;
      });
    }
    edgeList.forEach(e => { e.width = 1; e.arrows = 'to'; });
    return { nodeList, edgeList };
  }
  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      <div style={{ flex: 1, position: 'relative' }}>
        <div ref={containerRef} style={{ height: '100%' }} />
      </div>
      <div style={{ width: 360, padding: 12, overflow: 'auto' }}
        dangerouslySetInnerHTML={{ __html: nodeDetails }} />
    </div>
  );
}
