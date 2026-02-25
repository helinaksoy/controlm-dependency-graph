"""
Neo4j Graph Writer - Writes dependency graph (metadata, nodes, edges) to Neo4j.

Pipeline 1 (primary): Build writes to Neo4j. Uses batch UNWIND for large graphs.
"""

import json
from typing import Dict, List, Any, Optional

# Edge type (graph) -> Neo4j relationship type
EDGE_TYPE_TO_REL = {
    "contains": "CONTAINS",
    "produces": "PRODUCES",
    "requires": "REQUIRES",
    "executes": "EXECUTES",
    "calls_program": "CALLS_PROGRAM",
    "calls": "CALLS",
    "includes": "INCLUDES",
    "db_access": "DB_ACCESS",
}

# Node type (graph) -> Neo4j secondary label (PascalCase)
NODE_TYPE_TO_LABEL = {
    "folder": "Folder",
    "application": "Application",
    "sub_application": "SubApplication",
    "controlm_job": "ControlMJob",
    "condition": "Condition",
    "jcl": "JCL",
    "pl1_program": "PL1Program",
    "db_table": "DBTable",
    "include_file": "IncludeFile",
}

DEFAULT_NODE_BATCH = 5000
DEFAULT_EDGE_BATCH = 10000


def _serialize_property(value: Any) -> Any:
    """Convert node/edge property to Neo4j-safe value (no nested dict)."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_serialize_property(v) for v in value]
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _node_properties(node_id: str, data: Dict) -> Dict:
    """Build Neo4j property map for a node; all keys as-is, values serialized."""
    out = {"id": node_id}
    for k, v in data.items():
        if k == "id":
            continue
        out[k] = _serialize_property(v)
    return out


class Neo4jWriter:
    """Writes dependency graph to Neo4j with optional clear and batch support."""

    def __init__(
        self,
        uri: str,
        user: Optional[str] = None,
        password: Optional[str] = None,
        clear_before_write: bool = True,
        node_batch_size: int = DEFAULT_NODE_BATCH,
        edge_batch_size: int = DEFAULT_EDGE_BATCH,
    ):
        self.uri = uri
        self.user = user or "neo4j"
        self.password = password or ""
        self.clear_before_write = clear_before_write
        self.node_batch_size = node_batch_size
        self.edge_batch_size = edge_batch_size
        self._driver = None

    def _driver_connect(self):
        if self._driver is not None:
            return
        try:
            from neo4j import GraphDatabase
        except ImportError:
            raise ImportError("Neo4j Python driver required. Install with: pip install neo4j")
        self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))

    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None

    def _ensure_constraint(self, session):
        """Create unique constraint on Node.id if not exists."""
        session.run(
            "CREATE CONSTRAINT node_id_unique IF NOT EXISTS FOR (n:Node) REQUIRE n.id IS UNIQUE"
        )

    def _clear_graph(self, session):
        """Delete all Node nodes and their relationships."""
        session.run("MATCH (n:Node) DETACH DELETE n")

    def write_graph(self, graph_data: Dict) -> None:
        """
        Write full graph to Neo4j. Expects graph_data with keys:
        - metadata (optional)
        - nodes: dict id -> node data
        - edges: list of {from, to, type, label?, operation?}
        """
        metadata = graph_data.get("metadata", {})
        nodes = graph_data.get("nodes", {})
        edges = graph_data.get("edges", [])

        self._driver_connect()

        with self._driver.session() as session:
            self._ensure_constraint(session)
            if self.clear_before_write:
                self._clear_graph(session)

            # Write nodes in batches (group by label for UNWIND)
            node_items = list(nodes.items())
            for i in range(0, len(node_items), self.node_batch_size):
                batch = node_items[i : i + self.node_batch_size]
                self._write_nodes_batch(session, batch)

            # Write edges in batches
            for i in range(0, len(edges), self.edge_batch_size):
                batch = edges[i : i + self.edge_batch_size]
                self._write_edges_batch(session, batch)

        print(f"  [OK] Neo4j: wrote {len(nodes)} nodes, {len(edges)} edges")

    def _write_nodes_batch(self, session, batch: List[tuple]) -> None:
        """Write a batch of (node_id, node_data) as Node + type label; grouped by type, UNWIND."""
        by_label = {}
        for node_id, data in batch:
            ntype = data.get("type", "")
            secondary = NODE_TYPE_TO_LABEL.get(ntype, "Node")
            props = _node_properties(node_id, data)
            if secondary not in by_label:
                by_label[secondary] = []
            by_label[secondary].append(props)

        for secondary, rows in by_label.items():
            labels = ":Node:" + secondary
            query = f"UNWIND $rows AS row MERGE (n{labels} {{id: row.id}}) SET n += row"
            session.run(query, rows=rows)

    def _write_edges_batch(self, session, batch: List[Dict]) -> None:
        """Create relationships in batch; group by relationship type and UNWIND."""
        by_rel = {}
        for edge in batch:
            etype = edge.get("type", "")
            rel_type = EDGE_TYPE_TO_REL.get(etype, "DEPENDS_ON")
            if rel_type not in by_rel:
                by_rel[rel_type] = []
            by_rel[rel_type].append(edge)

        for rel_type, edges in by_rel.items():
            rows = []
            for e in edges:
                props = {}
                for k, v in e.items():
                    if k not in ("from", "to", "type"):
                        props[k] = _serialize_property(v) if v else ""
                rows.append({"from_id": e.get("from"), "to_id": e.get("to"), "props": props})
            query = (
                "UNWIND $rows AS row "
                "MERGE (a:Node {id: row.from_id}) MERGE (b:Node {id: row.to_id}) "
                "CREATE (a)-[r:%s]->(b) SET r += row.props"
            ) % rel_type
            session.run(query, rows=rows)
