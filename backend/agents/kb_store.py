import os
import json
import threading
import time
import hashlib
from typing import Any, Dict, List, Optional, Tuple

# If you have a helper that reads from S3, import it here.
# If not available, the code will fall back to a local JSON file.
try:
    from ingest_s3 import fetch_kb_from_s3  # type: ignore
    _HAS_S3_HELPER = True
except Exception:
    fetch_kb_from_s3 = None  # type: ignore
    _HAS_S3_HELPER = False

# configuration (adjust if needed or override with env vars)
S3_BUCKET = os.environ.get("S3_BUCKET", "")  # set to your bucket or leave empty to disable S3
S3_KEY = os.environ.get("S3_KEY", "it_tickets_kb.json")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
LOCAL_FALLBACK = os.path.abspath(os.environ.get("LOCAL_KB_PATH", os.path.join(os.path.dirname(__file__), "..", "it_tickets_kb.json")))

_TICKETS_LOCK = threading.Lock()
_TICKETS: List[Dict[str, Any]] = []
_LAST_UPDATED: Optional[float] = None
_LAST_SOURCE: str = "none"

# Knowledge graph cache
_KG_LOCK = threading.Lock()
_KG_NODES: List[Dict[str, Any]] = []
_KG_EDGES: List[Dict[str, Any]] = []
_KG_LAST_BUILT: Optional[float] = None


def _load_kb_from_local(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def reload_kb_from_s3_or_local() -> Dict[str, Any]:
    """
    Try to fetch KB from S3 (if configured and helper present). On failure, fall back to local file.
    Updates in-memory _TICKETS and metadata.
    Returns a status dict.
    """
    global _TICKETS, _LAST_UPDATED, _LAST_SOURCE
    fetched_from = "none"
    kb = None

    if S3_BUCKET and _HAS_S3_HELPER:
        try:
            kb = fetch_kb_from_s3(S3_BUCKET, S3_KEY, AWS_REGION)
            fetched_from = f"s3://{S3_BUCKET}/{S3_KEY}"
            # attempt to cache locally
            try:
                os.makedirs(os.path.dirname(LOCAL_FALLBACK), exist_ok=True)
                with open(LOCAL_FALLBACK, "w", encoding="utf-8") as wf:
                    json.dump(kb, wf, ensure_ascii=False, indent=2)
            except Exception:
                pass
        except Exception as e:
            fetched_from = f"s3-error:{str(e)}"
            kb = None

    if kb is None:
        kb = _load_kb_from_local(LOCAL_FALLBACK)
        if kb:
            fetched_from = LOCAL_FALLBACK

    if kb is None:
        kb = []

    with _TICKETS_LOCK:
        _TICKETS = kb
        _LAST_UPDATED = time.time()
        _LAST_SOURCE = fetched_from

    # rebuild graph cache after loading new tickets
    try:
        _build_kg_cache()
    except Exception:
        pass

    return {"count": len(kb), "source": fetched_from, "last_updated": _LAST_UPDATED}


# initialize at import time (non-blocking fallback)
try:
    reload_kb_from_s3_or_local()
except Exception:
    # swallow errors to keep import safe
    pass


def get_tickets() -> List[Dict[str, Any]]:
    with _TICKETS_LOCK:
        # return shallow copy
        return list(_TICKETS)


def get_status() -> Dict[str, Any]:
    with _TICKETS_LOCK:
        return {"count": len(_TICKETS), "last_updated": _LAST_UPDATED, "source": _LAST_SOURCE}


def find_ticket(ticket_id_or_display: str) -> Optional[Dict[str, Any]]:
    """
    Lookup a ticket by ticketId or displayId (string match).
    """
    if not ticket_id_or_display:
        return None
    tid = str(ticket_id_or_display).lower()
    with _TICKETS_LOCK:
        for t in _TICKETS:
            if str(t.get("ticketId", "")).lower() == tid or str(t.get("displayId", "")).lower() == tid:
                return t
    return None


def search_tickets_by_text(query: str, top_k: int = 10) -> List[Dict[str, Any]]:
    """
    Lightweight local search: substring match on subject/description.
    Returns top_k matches ordered by simple score (subject match > description).
    """
    if not query:
        return []
    q = query.strip().lower()
    with _TICKETS_LOCK:
        scores = []
        for t in _TICKETS:
            subject = str(t.get("subject", "")).lower()
            desc = str(t.get("description", "")).lower()
            score = 0
            if q in subject:
                score += 10
            if q in desc:
                score += 2
            if score > 0:
                scores.append((score, t))
        scores.sort(key=lambda x: -x[0])
        return [s[1] for s in scores[:top_k]]


# -----------------------------
# Knowledge Graph functions
# -----------------------------

def _make_id(prefix: str, value: str) -> str:
    # make a deterministic node id
    v = str(value or "").strip()
    safe = v.replace(" ", "_")[:200]
    # use a short hash to avoid extremely long ids
    h = hashlib.sha1(v.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}:{safe}:{h}"


def _hash_text(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:10]


def _extract_steps_from_ticket(t: Dict[str, Any]) -> List[str]:
    # Common places where resolution steps might live
    steps = []
    if isinstance(t.get("resolutionSteps"), list):
        steps.extend([str(s) for s in t.get("resolutionSteps")])
    # worklog/work_logs/logs sometimes exist
    for key in ("worklog", "work_log", "work_logs", "logs"):
        val = t.get(key)
        if isinstance(val, list):
            for entry in val:
                if isinstance(entry, dict):
                    text = entry.get("text") or entry.get("note") or entry.get("description")
                    if text:
                        steps.append(str(text))
                else:
                    steps.append(str(entry))
    # some tickets may have a single free-text resolution
    if t.get("resolution") and isinstance(t.get("resolution"), str):
        steps.append(t.get("resolution"))
    # dedupe
    cleaned = []
    seen = set()
    for s in steps:
        s2 = s.strip()
        if s2 and s2 not in seen:
            seen.add(s2)
            cleaned.append(s2)
    return cleaned


def _build_kg_from_tickets(tickets: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Build a simple knowledge graph representation (nodes and edges) from ticket records.

    Node shape: { "id": "type:identifier:hash", "type": "Ticket|Technician|Category|RootCause|Asset|Step|Cluster|Client|Impact", "label": "human label", "meta": { ... } }
    Edge shape: { "source": "id", "target": "id", "type": "relationship_name", "weight": 1.0 }

    This function is intentionally defensive: it tolerates missing fields and attempts to infer sensible node ids.
    """
    nodes_by_key: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []

    def add_node(key: str, node_type: str, label: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if key in nodes_by_key:
            return nodes_by_key[key]
        node = {"id": key, "type": node_type, "label": label, "meta": meta or {}}
        nodes_by_key[key] = node
        return node

    # Helper to add edge
    def add_edge(src: str, tgt: str, rel: str, weight: float = 1.0):
        edges.append({"source": src, "target": tgt, "type": rel, "weight": float(weight)})

    # First pass: create ticket nodes and common related nodes
    for t in tickets:
        tid_raw = t.get("ticketId") or t.get("id") or t.get("displayId")
        if not tid_raw:
            # skip tickets without an id
            continue
        ticket_node_id = _make_id("ticket", str(tid_raw))
        ticket_label = str(t.get("displayId") or t.get("ticketId") or t.get("subject") or ticket_node_id)
        add_node(ticket_node_id, "Ticket", ticket_label, {"ticket": t})

    # Second pass: add related nodes and edges
    for t in tickets:
        tid_raw = t.get("ticketId") or t.get("id") or t.get("displayId")
        if not tid_raw:
            continue
        ticket_node_id = _make_id("ticket", str(tid_raw))

        # Technician -> Ticket (resolved)
        tech = t.get("technician") or t.get("resolver") or t.get("assignedTo")
        if isinstance(tech, dict):
            user_id = tech.get("userId") or tech.get("id")
            name = tech.get("name") or tech.get("displayName")
        else:
            # technician could be a simple string like name or id
            user_id = tech
            name = tech
        if user_id:
            tech_node_id = _make_id("technician", str(user_id))
            add_node(tech_node_id, "Technician", str(name or user_id), {"raw": tech})
            add_edge(tech_node_id, ticket_node_id, "resolved")

        # Category / Subcategory (Ticket -> Category)
        cat = t.get("category") or t.get("type")
        subcat = t.get("subcategory") or t.get("sub_type")
        if cat:
            cat_key = f"{cat}:{subcat}" if subcat else f"{cat}"
            cat_node_id = _make_id("category", cat_key)
            label = f"{cat}{(' / ' + subcat) if subcat else ''}"
            add_node(cat_node_id, "Category", label, {"category": cat, "subcategory": subcat})
            add_edge(ticket_node_id, cat_node_id, "category")

        # Root cause
        rc = t.get("rootCause") or t.get("root_cause") or t.get("cause")
        if rc:
            rc_node_id = _make_id("rootcause", str(rc))
            add_node(rc_node_id, "RootCause", str(rc), {"raw": rc})
            add_edge(ticket_node_id, rc_node_id, "root_cause")

        # Asset
        asset = t.get("asset") or t.get("device") or t.get("cmdb_asset")
        if asset:
            if isinstance(asset, dict):
                aid = asset.get("id") or asset.get("assetId") or asset.get("name")
                label = asset.get("name") or aid
            else:
                aid = asset
                label = str(asset)
            asset_node_id = _make_id("asset", str(aid))
            add_node(asset_node_id, "Asset", str(label), {"raw": asset})
            add_edge(ticket_node_id, asset_node_id, "asset")

        # Resolution Steps
        steps = _extract_steps_from_ticket(t)
        for s in steps:
            # create id by hashing the step text
            step_id = _make_id("step", _hash_text(s))
            add_node(step_id, "Step", (s[:140] + "...") if len(s) > 140 else s, {"step": s})
            add_edge(ticket_node_id, step_id, "step")

        # Client / Site
        client = t.get("client") or t.get("site") or t.get("location")
        if client:
            client_node_id = _make_id("client", str(client))
            add_node(client_node_id, "Client", str(client), {})
            add_edge(ticket_node_id, client_node_id, "client_site")

        # User Impact / Severity
        impact = t.get("impact") or t.get("severity")
        if impact:
            impact_node_id = _make_id("impact", str(impact))
            add_node(impact_node_id, "Impact", str(impact), {})
            add_edge(ticket_node_id, impact_node_id, "impact")

    # Similar Ticket Cluster: attempt to connect tickets either via an explicit similar list or by cheap subject similarity
    id_map = {}
    for t in tickets:
        tid_raw = t.get("ticketId") or t.get("id") or t.get("displayId")
        if not tid_raw:
            continue
        ticket_node_id = _make_id("ticket", str(tid_raw))
        id_map[str(tid_raw)] = ticket_node_id

    # explicit similar links
    for t in tickets:
        tid_raw = t.get("ticketId") or t.get("id") or t.get("displayId")
        if not tid_raw:
            continue
        ticket_node_id = id_map.get(str(tid_raw))
        sim_list = t.get("similar_ticket_ids") or t.get("similar") or t.get("relatedTickets")
        if isinstance(sim_list, list):
            for sid in sim_list:
                sid_str = str(sid)
                if sid_str in id_map:
                    add_edge(ticket_node_id, id_map[sid_str], "similar_to")
                    # add reverse edge to make traversal easier
                    add_edge(id_map[sid_str], ticket_node_id, "similar_to")

    # cheap subject-based similarity (only if no explicit similar links found)
    # Build simple token sets and connect pairs with >50% token overlap
    subjects = []
    for t in tickets:
        tid_raw = t.get("ticketId") or t.get("id") or t.get("displayId")
        if not tid_raw:
            continue
        subj = str(t.get("subject") or "").lower()
        tokens = set([tok for tok in subj.split() if len(tok) > 2])
        subjects.append((str(tid_raw), tokens))
    n = len(subjects)
    for i in range(n):
        for j in range(i + 1, n):
            id_i, tok_i = subjects[i]
            id_j, tok_j = subjects[j]
            if not tok_i or not tok_j:
                continue
            inter = tok_i.intersection(tok_j)
            denom = max(len(tok_i), len(tok_j))
            if denom == 0:
                continue
            score = len(inter) / denom
            if score >= 0.6:  # fairly strict
                a = id_map.get(id_i)
                b = id_map.get(id_j)
                if a and b:
                    add_edge(a, b, "similar_to", weight=score)
                    add_edge(b, a, "similar_to", weight=score)

    # produce lists
    nodes = list(nodes_by_key.values())
    return nodes, edges


def _build_kg_cache() -> None:
    """
    Rebuilds the in-memory KG nodes/edges from the current ticket set and stores them in module-level cache.
    """
    global _KG_NODES, _KG_EDGES, _KG_LAST_BUILT
    with _KG_LOCK:
        tickets = get_tickets()
        nodes, edges = _build_kg_from_tickets(tickets)
        _KG_NODES = nodes
        _KG_EDGES = edges
        _KG_LAST_BUILT = time.time()


# Ensure the KG is built on module import (best-effort)
try:
    _build_kg_cache()
except Exception:
    pass


def get_kg() -> Dict[str, Any]:
    """Return the cached knowledge graph: { nodes: [...], edges: [...], last_built: ts }"""
    with _KG_LOCK:
        return {"nodes": list(_KG_NODES), "edges": list(_KG_EDGES), "last_built": _KG_LAST_BUILT}


def find_node(node_id: str) -> Optional[Dict[str, Any]]:
    with _KG_LOCK:
        for n in _KG_NODES:
            if n.get("id") == node_id:
                return n
    return None


def find_edges_for_node(node_id: str) -> List[Dict[str, Any]]:
    with _KG_LOCK:
        return [e for e in _KG_EDGES if e.get("source") == node_id or e.get("target") == node_id]


def search_nodes_by_text(query: str, top_k: int = 20) -> List[Dict[str, Any]]:
    if not query:
        return []
    q = query.strip().lower()
    results: List[Tuple[int, Dict[str, Any]]] = []
    with _KG_LOCK:
        for n in _KG_NODES:
            label = str(n.get("label", "")).lower()
            meta = json.dumps(n.get("meta", {})).lower()
            score = 0
            if q in label:
                score += 10
            if q in meta:
                score += 3
            if score > 0:
                results.append((score, n))
    results.sort(key=lambda x: -x[0])
    return [r[1] for r in results[:top_k]]


def refresh_kb() -> Dict[str, Any]:
    """
    Public helper to force reload the underlying KB (S3 or local) and rebuild the graph cache.
    Returns the reload status combined with KG metadata.
    """
    status = reload_kb_from_s3_or_local()
    # reload_kb already attempts to rebuild the KG cache, but ensure it here as well
    try:
        _build_kg_cache()
    except Exception:
        pass
    kg = get_kg()
    status.update({"kg_nodes": len(kg.get("nodes", [])), "kg_edges": len(kg.get("edges", [])), "kg_last_built": kg.get("last_built")})
    return status


# -----------------------------
# Backwards-compatible aliasing for the Flask routes in your example
# -----------------------------

# Export functions with names similar to the route handlers used in the example snippet so they can be wired easily.
kb_get_status = get_status
kb_get_tickets = get_tickets
kb_find_ticket = find_ticket
kb_search = search_tickets_by_text
kb_reload = refresh_kb
kb_get_kg = get_kg
kb_find_node = find_node
kb_find_edges = find_edges_for_node
kb_search_nodes = search_nodes_by_text


# If this module is executed directly, offer a tiny CLI for debugging
if __name__ == "__main__":
    print("KB store debug\nStatus:", get_status())
    kg = get_kg()
    print(f"KG nodes: {len(kg['nodes'])}, edges: {len(kg['edges'])}")
    # print a couple of nodes for quick inspection
    for n in kg['nodes'][:5]:
        print(n)

