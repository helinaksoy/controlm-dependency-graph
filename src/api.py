"""
Flask REST API for Control-M Dependency Graph Viewer
"""

import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path
from collections import defaultdict

from flask import Flask, jsonify, request, render_template, Response, stream_with_context
from flask_cors import CORS

sys.path.insert(0, str(Path(__file__).parent))

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)
CORS(app)

CONFIG_PATH = Path(__file__).parent.parent / "config.json"
_config: dict = {}
_graph = None
_graph_cache: dict = {}   # (scope, name, drill) -> JSON-serializable dict
_graph_loading = False     # prevent concurrent re-loads


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def load_config() -> None:
    global _config
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            _config = json.load(f)
    except Exception as exc:
        print(f"Warning: could not load config.json: {exc}")
        _config = {}


def get_graph():
    global _graph
    if _graph is not None:
        return _graph

    uri = _config.get("neo4j_uri", "neo4j://127.0.0.1:7687")
    user = _config.get("neo4j_user", "neo4j")
    password = _config.get("neo4j_password", "")

    try:
        from neo4j_query import Neo4jGraphQuery
        print("Connecting to Neo4j …")
        _graph = Neo4jGraphQuery(uri=uri, user=user, password=password)
        meta = _graph.metadata
        print(
            f"Graph loaded: {meta.get('total_nodes', 0)} nodes, "
            f"{meta.get('total_edges', 0)} edges"
        )
    except Exception as exc:
        print(f"Neo4j connection failed: {exc}")
        _graph = None

    return _graph


# ---------------------------------------------------------------------------
# Helper traversal functions
# ---------------------------------------------------------------------------

def _folder_jobs(g, folder_id: str) -> set:
    return {
        e["to"]
        for e in g.edges_from.get(folder_id, [])
        if e["type"] == "contains"
        and g.nodes.get(e["to"], {}).get("type") == "controlm_job"
    }


def _subapp_jobs(g, subapp_id: str) -> set:
    jobs: set = set()
    for e in g.edges_from.get(subapp_id, []):
        if e["type"] == "contains":
            jobs |= _folder_jobs(g, e["to"])
    return jobs


def _app_jobs(g, app_id: str) -> set:
    jobs: set = set()
    for e in g.edges_from.get(app_id, []):
        if e["type"] == "contains":
            jobs |= _subapp_jobs(g, e["to"])
    return jobs


def _build_job_graph(g, job_ids: set, scope: str = "folder") -> tuple[dict, list, list]:
    """
    Return (nodes_dict, edges_list, groups_list) in Cytoscape element format.

    nodes/edges: flat list of job nodes + dependency edges (no compound parents).
    groups:      [{id, label, type, color_index, job_ids}] — used by the
                 frontend to draw background bounding-box rectangles after
                 the dagre layout has placed every node.
    """
    nodes_out: dict = {}
    edges_out: list = []
    seen_edges: set = set()

    # Track group membership  {group_key → {id, label, type, job_ids:[]}}
    groups: dict = {}

    for job_id in job_ids:
        job_node = g.nodes.get(job_id)
        if not job_node:
            continue

        folder_name = job_node.get("folder", "")
        subapp_name = job_node.get("sub_application", "")

        # Determine group key for this job
        if scope == "folder":
            gkey = f"SUBAPP::{subapp_name}" if subapp_name else None
            glabel, gtype = subapp_name, "sub_application"
        elif scope == "subapp":
            gkey = f"FOLDER::{folder_name}" if folder_name else None
            glabel, gtype = folder_name, "folder"
        else:  # app
            # Primary grouping by subapp, secondary by folder
            gkey = f"SUBAPP::{subapp_name}" if subapp_name else (
                f"FOLDER::{folder_name}" if folder_name else None
            )
            glabel = subapp_name or folder_name
            gtype = "sub_application" if subapp_name else "folder"

        if gkey and gkey not in groups:
            groups[gkey] = {
                "id": gkey,
                "label": glabel,
                "type": gtype,
                "color_index": len(groups),  # for distinct colour per group
                "job_ids": [],
            }
        if gkey:
            groups[gkey]["job_ids"].append(job_id)

        node_data = _cy_job_node(job_node, external=False)
        # Embed group info for client-side colour coding
        if gkey:
            node_data["data"]["group_id"] = gkey
            node_data["data"]["group_label"] = glabel
            node_data["data"]["color_index"] = groups[gkey]["color_index"]
        nodes_out[job_id] = node_data

    # Traverse: for every local job that PRODUCES a condition,
    # find every other job that REQUIRES that same condition.
    for job_id in job_ids:
        for edge in g.edges_from.get(job_id, []):
            if edge["type"] != "produces":
                continue
            cond_id = edge["to"]
            cond_node = g.nodes.get(cond_id, {})
            cond_name = cond_node.get("name", cond_id)

            # jobs that require this condition
            for cond_edge in g.edges_to.get(cond_id, []):
                if cond_edge["type"] != "requires":
                    continue
                consumer_id = cond_edge["from"]
                if consumer_id == job_id:
                    continue

                is_ext = consumer_id not in job_ids

                if is_ext and consumer_id not in nodes_out:
                    other = g.nodes.get(consumer_id, {})
                    nodes_out[consumer_id] = _cy_job_node(other, external=True)

                edge_key = (job_id, consumer_id, cond_name)
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    edges_out.append({
                        "data": {
                            "id": f"e_{job_id}__{consumer_id}__{cond_name}",
                            "source": job_id,
                            "target": consumer_id,
                            "type": "job_dependency",
                            "condition": cond_name,
                            "external": is_ext,
                        }
                    })

    return nodes_out, edges_out, list(groups.values())


def _cy_job_node(node: dict, *, external: bool) -> dict:
    data = {k: v for k, v in node.items()}
    data["label"] = node.get("name", node.get("id", "?"))
    data["external"] = external
    if external:
        folder = node.get("folder", "")
        data["label"] = f"[{folder}]\n{data['label']}" if folder else data["label"]
    return {"data": data}


def _add_drill_down(g, job_id: str, nodes_out: dict, edges_out: list, seen: set) -> None:
    """
    Add Job → PL1Program → (PL1Program CALL chain, depth-limited) + DB_ACCESS nodes/edges.
    Uses iterative BFS instead of recursion to avoid stack overflow on large call graphs.
    Only follows: executes (Job→PL1), calls (PL1→PL1, max 2 hops), db_access (PL1→DB), includes (PL1→Include).
    """
    _FOLLOW_TYPES = ("executes", "calls_program", "calls", "db_access", "includes")
    _MAX_CALL_DEPTH = 2   # PL1→PL1 call depth limit to prevent explosion

    # BFS queue: (node_id, depth)
    queue = [(job_id, 0)]
    visited_nodes = set()

    while queue:
        current_id, depth = queue.pop(0)
        if current_id in visited_nodes:
            continue
        visited_nodes.add(current_id)

        current_node = g.nodes.get(current_id, {})
        current_type = current_node.get("type", "")

        for edge in g.edges_from.get(current_id, []):
            etype = edge["type"]
            if etype not in _FOLLOW_TYPES:
                continue

            target_id = edge["to"]
            target_node = g.nodes.get(target_id)
            if not target_node:
                continue

            # Add target node
            if target_id not in nodes_out:
                nodes_out[target_id] = {
                    "data": {
                        **target_node,
                        "label": target_node.get("name", target_id),
                        "external": False,
                    }
                }

            # Add edge
            ek = (current_id, target_id, etype)
            if ek not in seen:
                seen.add(ek)
                edges_out.append({
                    "data": {
                        "id": f"drill_{current_id}__{target_id}__{etype}",
                        "source": current_id,
                        "target": target_id,
                        "type": etype,
                        "external": False,
                    }
                })

            # Recurse into PL1 programs (depth-limited) and DB tables (no further recursion)
            target_type = target_node.get("type", "")
            if target_type == "pl1_program" and depth < _MAX_CALL_DEPTH:
                queue.append((target_id, depth + 1))
            elif target_type in ("db_table", "include_file"):
                pass  # leaf nodes — no further traversal


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/stats")
def api_stats():
    g = get_graph()
    if g is None:
        return jsonify({"error": "Graph not available"}), 503
    return jsonify(g.metadata)


@app.route("/api/tree")
def api_tree():
    """Return only top-level Application nodes. Children loaded lazily via /api/tree/<id>/children."""
    g = get_graph()
    if g is None:
        return jsonify({"error": "Graph not available"}), 503

    app_ids = g.nodes_by_type.get("application", [])
    tree = []
    for app_id in sorted(app_ids):
        node = g.nodes.get(app_id)
        if not node:
            continue
        entry = _tree_node(node)
        # Count direct children of this specific application node
        entry["child_count"] = sum(
            1 for e in g.edges_from.get(app_id, []) if e["type"] == "contains"
        )
        tree.append(entry)
    return jsonify(tree)


@app.route("/api/tree/<path:node_id>/children")
def api_tree_children(node_id: str):
    """Return direct children of a node (lazy tree expansion)."""
    g = get_graph()
    if g is None:
        return jsonify({"error": "Graph not available"}), 503

    cache_key = ("tree_children", node_id)
    if cache_key in _graph_cache:
        return jsonify(_graph_cache[cache_key])

    children_ids = [
        e["to"] for e in g.edges_from.get(node_id, [])
        if e["type"] == "contains"
    ]

    children = []
    for cid in sorted(children_ids):
        child_node = g.nodes.get(cid)
        if not child_node:
            continue
        entry = _tree_node(child_node, leaf=(child_node.get("type") == "controlm_job"))
        # How many direct children does this node have?
        child_count = sum(
            1 for e in g.edges_from.get(cid, []) if e["type"] == "contains"
        )
        entry["child_count"] = child_count
        children.append(entry)

    _graph_cache[cache_key] = children
    return jsonify(children)


def _tree_node(node: dict, leaf: bool = False) -> dict:
    entry: dict = {
        "id": node["id"],
        "name": node.get("name", node["id"]),
        "type": node.get("type", "node"),
    }
    if not leaf:
        entry["children"] = []
    return entry


@app.route("/api/graph")
def api_graph():
    """
    Return Cytoscape-ready graph data for the selected scope.

    Query params:
      scope  : folder | subapp | app
      name   : the node name (e.g. Finance_EndOfMonth)
      drill  : optional job name to expand (shows JCL/PL1/DB chain)
    """
    g = get_graph()
    if g is None:
        return jsonify({"error": "Graph not available"}), 503

    scope = request.args.get("scope", "folder")
    name  = request.args.get("name", "").strip()
    drill = request.args.get("drill", "").strip()

    if not name:
        return jsonify({"error": "name parameter required"}), 400

    scope_map = {
        "folder": ("FOLDER", _folder_jobs),
        "subapp": ("SUBAPP", _subapp_jobs),
        "app":    ("APP",    _app_jobs),
    }
    if scope not in scope_map:
        return jsonify({"error": f"Unknown scope: {scope}"}), 400

    # ── Cache lookup ─────────────────────────────────────────
    cache_key = (scope, name, drill)
    if cache_key in _graph_cache:
        return jsonify(_graph_cache[cache_key])

    prefix, job_fn = scope_map[scope]
    target_id = f"{prefix}::{name}"
    job_ids = job_fn(g, target_id)

    nodes_out, edges_out, groups = _build_job_graph(g, job_ids, scope=scope)

    # Optional drill-down
    if drill:
        drill_id = f"CONTROLM::{drill}"
        if drill_id in job_ids:
            seen: set = {
                (e["data"]["source"], e["data"]["target"], e["data"].get("type", ""))
                for e in edges_out
            }
            _add_drill_down(g, drill_id, nodes_out, edges_out, seen)

    result = {
        "nodes":     list(nodes_out.values()),
        "edges":     edges_out,
        "groups":    groups,
        "scope":     scope,
        "name":      name,
        "job_count": len(job_ids),
    }

    # ── Cache store (only cache non-drill results to keep memory bounded) ──
    if not drill:
        _graph_cache[cache_key] = result

    return jsonify(result)


@app.route("/api/node/<path:node_id>")
def api_node(node_id: str):
    """Return full details for a single node, including cross-folder deps."""
    g = get_graph()
    if g is None:
        return jsonify({"error": "Graph not available"}), 503

    node = g.nodes.get(node_id)
    if not node:
        return jsonify({"error": f"Node not found: {node_id}"}), 404

    out_edges = g.edges_from.get(node_id, [])[:200]
    in_edges = g.edges_to.get(node_id, [])[:200]

    cross_folder: list = []
    if node.get("type") == "controlm_job":
        node_folder = node.get("folder", "")
        # Outgoing: this job produces a condition that another folder's job requires
        for edge in g.edges_from.get(node_id, []):
            if edge["type"] != "produces":
                continue
            cond_id = edge["to"]
            cond_node = g.nodes.get(cond_id, {})
            for ce in g.edges_to.get(cond_id, []):
                if ce["type"] != "requires":
                    continue
                other = g.nodes.get(ce["from"], {})
                if other.get("folder", "") != node_folder:
                    cross_folder.append({
                        "direction": "outgoing",
                        "job": other.get("name", ce["from"]),
                        "job_id": ce["from"],
                        "folder": other.get("folder", ""),
                        "condition": cond_node.get("name", cond_id),
                    })
        # Incoming: another folder's job produces a condition this job requires
        for edge in g.edges_from.get(node_id, []):
            if edge["type"] != "requires":
                continue
            cond_id = edge["to"]
            cond_node = g.nodes.get(cond_id, {})
            for ce in g.edges_to.get(cond_id, []):
                if ce["type"] != "produces":
                    continue
                other = g.nodes.get(ce["from"], {})
                if other.get("folder", "") != node_folder:
                    cross_folder.append({
                        "direction": "incoming",
                        "job": other.get("name", ce["from"]),
                        "job_id": ce["from"],
                        "folder": other.get("folder", ""),
                        "condition": cond_node.get("name", cond_id),
                    })

    return jsonify({
        "node": node,
        "out_edges": out_edges,
        "in_edges": in_edges,
        "cross_folder_deps": cross_folder,
    })


@app.route("/api/search")
def api_search():
    g = get_graph()
    if g is None:
        return jsonify({"error": "Graph not available"}), 503

    q = request.args.get("q", "").strip()
    node_type = request.args.get("type") or None
    if not q:
        return jsonify([])

    matches = g.search_node(q, node_type)
    results = []
    for nid in matches[:100]:
        nd = g.nodes.get(nid, {})
        results.append({
            "id": nid,
            "name": nd.get("name", nid),
            "type": nd.get("type", ""),
            "folder": nd.get("folder", ""),
            "application": nd.get("application", ""),
            "sub_application": nd.get("sub_application", ""),
        })
    return jsonify(results)


@app.route("/api/pl1/<path:node_id>")
def api_pl1_chain(node_id: str):
    """
    Return the full PL/I dependency chain for a given job or PL/I program node.

    Traverses: executes → pl1_program → calls (max 2 hops) → db_access / includes.
    Accepts any node ID (CONTROLM::name or PL1::name).
    """
    g = get_graph()
    if g is None:
        return jsonify({"error": "Graph not available"}), 503

    cache_key = ("pl1", node_id)
    if cache_key in _graph_cache:
        return jsonify(_graph_cache[cache_key])

    node = g.nodes.get(node_id)
    if not node:
        return jsonify({"error": f"Node not found: {node_id}"}), 404

    nodes_out: dict = {
        node_id: {
            "data": {
                **node,
                "label": node.get("name", node_id),
                "external": False,
            }
        }
    }
    edges_out: list = []
    seen:      set  = set()

    _add_drill_down(g, node_id, nodes_out, edges_out, seen)

    # Stats
    pl1_count     = sum(1 for n in nodes_out.values() if n["data"].get("type") == "pl1_program")
    db_count      = sum(1 for n in nodes_out.values() if n["data"].get("type") == "db_table")
    include_count = sum(1 for n in nodes_out.values() if n["data"].get("type") == "include_file")

    result = {
        "nodes": list(nodes_out.values()),
        "edges": edges_out,
        "stats": {
            "pl1_count":     pl1_count,
            "db_count":      db_count,
            "include_count": include_count,
        },
    }

    if nodes_out:
        _graph_cache[cache_key] = result

    return jsonify(result)


@app.route("/api/analyze/<path:node_id>")
def api_analyze(node_id: str):
    """
    Analyze a PL/I program using LLM.
    Reads .pl1 source + optional Rochade .txt from the fixed path,
    sends to LLM, returns Turkish business-level analysis.
    """
    cache_key = ("analyze", node_id)
    if cache_key in _graph_cache:
        return jsonify(_graph_cache[cache_key])

    g = get_graph()
    if g is None:
        return jsonify({"error": "Graph not available"}), 503

    node = g.nodes.get(node_id)
    if not node:
        return jsonify({"error": f"Node not found: {node_id}"}), 404

    # ── PL/I source ───────────────────────────────────────────
    file_path = node.get("file_path", "")
    if not file_path:
        return jsonify({"error": "No file_path for this node"}), 400

    pl1_path = Path(file_path)
    if not pl1_path.exists():
        return jsonify({"error": f"PL/I file not found: {file_path}"}), 404

    try:
        pl1_source = pl1_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return jsonify({"error": f"Cannot read PL/I file: {exc}"}), 500

    # Truncate to stay within LLM context limits
    MAX_PL1 = 6000
    if len(pl1_source) > MAX_PL1:
        pl1_source = pl1_source[:MAX_PL1] + "\n\n[... dosya kesildi ...]\n"

    # ── Rochade documentation (fixed path) ────────────────────
    stem = pl1_path.stem.upper()
    rochade_path = Path("C:/AVC/Workspace/v250/abs/prod/rochade") / f"{stem}.txt"
    has_rochade = False
    rochade_text = ""
    if rochade_path.exists():
        try:
            rochade_text = rochade_path.read_text(encoding="utf-8", errors="replace")
            has_rochade = True
        except Exception:
            pass

    # ── Log files being sent to LLM ───────────────────────────
    print(f"[LLM] PL/I kaynak  : {pl1_path} ({len(pl1_source)} karakter)")
    if has_rochade:
        print(f"[LLM] Rochade dok. : {rochade_path} ({len(rochade_text)} karakter)")
    else:
        print(f"[LLM] Rochade dok. : bulunamadı ({rochade_path})")

    # ── LLM config (env vars override config.json) ────────────
    llm_url   = _config.get("llm_host_url", "") or os.environ.get("LLM_HOST_URL", "")
    llm_key   = _config.get("llm_api_key",  "") or os.environ.get("LLM_API_KEY",  "")
    llm_model = _config.get("llm_model",    "") or os.environ.get("LLM_MODEL", "")

    if not llm_url:
        return jsonify({"error": "LLM yapılandırılmamış (llm_host_url eksik)"}), 503

    # ── Build prompt ──────────────────────────────────────────
    user_content = ""
    if has_rochade:
        user_content += f"=== ROCHADE DOKÜMANTASYONU ===\n{rochade_text}\n\n"
    user_content += f"=== PL/I KAYNAK KOD ({pl1_path.name}) ===\n{pl1_source}"

    messages = [
        {
            "role": "system",
            "content": (
                "Sen deneyimli bir legacy PL/I kod analistsin. "
                "Görevin, verilen PL/I programını iş süreci perspektifinden analiz etmek ve "
                "Türkçe olarak açıklamak. "
                "Teknik PL/I detayları yerine iş sürecini, programın ne işe yaradığını, "
                "hangi veritabanlarına eriştiğini ve diğer programlarla ilişkisini vurgula. "
                "Açıklamayı şu başlıklar altında yaz: "
                "1) Genel Amaç, 2) İş Süreci Adımları, 3) Veritabanı Erişimleri, "
                "4) Dış Program Çağrıları, 5) Önemli Notlar."
            ),
        },
        {
            "role": "user",
            "content": user_content,
        },
    ]

    payload = {
        "model":       llm_model,
        "messages":    messages,
        "temperature": 0.2,
    }

    endpoint = llm_url.rstrip("/") + "/chat/completions"
    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {llm_key}",
    }

    # ── Call LLM (high timeout for long analyses) ─────────────
    try:
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        # Internal/corporate proxy may use self-signed cert → skip SSL verify
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode    = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=120, context=ssl_ctx) as resp:
            body = resp.read().decode("utf-8")
        resp_json = json.loads(body)
        analysis  = resp_json["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"[LLM ERROR] {type(exc).__name__}: {exc}")
        return jsonify({"error": f"LLM hatası: {type(exc).__name__}: {exc}"}), 502

    result = {
        "analysis":    analysis,
        "program":     node.get("name", node_id),
        "has_rochade": has_rochade,
    }
    _graph_cache[cache_key] = result
    return jsonify(result)


# ---------------------------------------------------------------------------
# Streaming analysis endpoint
# ---------------------------------------------------------------------------

@app.route("/api/analyze-stream/<path:node_id>")
def api_analyze_stream(node_id: str):
    """
    Streaming version of api_analyze.
    Returns Server-Sent Events:  meta → chunks → [DONE]
    """
    g = get_graph()
    if g is None:
        return jsonify({"error": "Graph not available"}), 503

    node = g.nodes.get(node_id)
    if not node:
        return jsonify({"error": f"Node not found: {node_id}"}), 404

    file_path = node.get("file_path", "")
    if not file_path:
        return jsonify({"error": "No file_path for this node"}), 400

    pl1_path = Path(file_path)
    if not pl1_path.exists():
        return jsonify({"error": f"PL/I file not found: {file_path}"}), 404

    try:
        pl1_source = pl1_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return jsonify({"error": f"Cannot read PL/I file: {exc}"}), 500

    MAX_PL1 = 6000
    if len(pl1_source) > MAX_PL1:
        pl1_source = pl1_source[:MAX_PL1] + "\n\n[... dosya kesildi ...]\n"

    stem         = pl1_path.stem.upper()
    rochade_path = Path("C:/AVC/Workspace/v250/abs/prod/rochade") / f"{stem}.txt"
    has_rochade  = False
    rochade_text = ""
    if rochade_path.exists():
        try:
            rochade_text = rochade_path.read_text(encoding="utf-8", errors="replace")
            has_rochade  = True
        except Exception:
            pass

    print(f"[LLM] PL/I kaynak  : {pl1_path} ({len(pl1_source)} karakter)")
    if has_rochade:
        print(f"[LLM] Rochade dok. : {rochade_path} ({len(rochade_text)} karakter)")
    else:
        print(f"[LLM] Rochade dok. : bulunamad\u0131 ({rochade_path})")

    llm_url   = _config.get("llm_host_url", "") or os.environ.get("LLM_HOST_URL", "")
    llm_key   = _config.get("llm_api_key",  "") or os.environ.get("LLM_API_KEY",  "")
    llm_model = _config.get("llm_model",    "") or os.environ.get("LLM_MODEL",    "")

    if not llm_url:
        return jsonify({"error": "LLM yap\u0131land\u0131r\u0131lmam\u0131\u015f (llm_host_url eksik)"}), 503

    user_content = ""
    if has_rochade:
        user_content += f"=== ROCHADE DOK\u00dcMANTASYONU ===\n{rochade_text}\n\n"
    user_content += f"=== PL/I KAYNAK KOD ({pl1_path.name}) ===\n{pl1_source}"

    messages = [
        {
            "role": "system",
            "content": (
                "Sen deneyimli bir legacy PL/I kod analistsin. "
                "G\u00f6revin, verilen PL/I program\u0131n\u0131 i\u015f s\u00fcreci perspektifinden analiz etmek ve "
                "T\u00fcrk\u00e7e olarak a\u00e7\u0131klamak. "
                "Teknik PL/I detaylar\u0131 yerine i\u015f s\u00fcrecini, program\u0131n ne i\u015fe yarad\u0131\u011f\u0131n\u0131, "
                "hangi veritabanlar\u0131na eri\u015fti\u011fini ve di\u011fer programlarla ili\u015fkisini vurgula. "
                "A\u00e7\u0131klamay\u0131 \u015fu ba\u015fl\u0131klar alt\u0131nda yaz: "
                "1) Genel Ama\u00e7, 2) \u0130\u015f S\u00fcreci Ad\u0131mlar\u0131, 3) Veritaban\u0131 Eri\u015fimleri, "
                "4) D\u0131\u015f Program \u00c7a\u011fr\u0131lar\u0131, 5) \u00d6nemli Notlar."
            ),
        },
        {"role": "user", "content": user_content},
    ]

    endpoint = llm_url.rstrip("/") + "/chat/completions"
    headers  = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {llm_key}",
    }

    # ── Serve from cache (replay cached text as a fast stream) ────────────
    cache_key = ("analyze", node_id)
    if cache_key in _graph_cache:
        cached = _graph_cache[cache_key]
        def cached_gen():
            yield f'data: {json.dumps({"type":"meta","has_rochade":cached["has_rochade"],"program":cached["program"]})}\n\n'
            text  = cached["analysis"]
            step  = 80
            for i in range(0, len(text), step):
                yield f'data: {json.dumps({"type":"chunk","content":text[i:i+step]})}\n\n'
            yield "data: [DONE]\n\n"
        return Response(
            stream_with_context(cached_gen()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── Live stream from LLM ──────────────────────────────────────────────
    def generate():
        yield f'data: {json.dumps({"type":"meta","has_rochade":has_rochade,"program":node.get("name",node_id)})}\n\n'
        full_text = ""
        payload = {
            "model":       llm_model,
            "messages":    messages,
            "temperature": 0.2,
            "stream":      True,
        }
        try:
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode    = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=120, context=ssl_ctx) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk_data = json.loads(data_str)
                        content    = chunk_data["choices"][0]["delta"].get("content", "")
                        if content:
                            full_text += content
                            yield f'data: {json.dumps({"type":"chunk","content":content})}\n\n'
                    except Exception:
                        pass
            _graph_cache[cache_key] = {
                "analysis":    full_text,
                "program":     node.get("name", node_id),
                "has_rochade": has_rochade,
            }
        except Exception as exc:
            print(f"[LLM STREAM ERROR] {type(exc).__name__}: {exc}")
            yield f'data: {json.dumps({"type":"error","message":f"{type(exc).__name__}: {exc}"})}\n\n'
        yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    load_config()
    app.run(debug=True, port=5000, host="0.0.0.0", use_reloader=False)
