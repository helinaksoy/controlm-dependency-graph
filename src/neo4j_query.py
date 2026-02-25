"""
Neo4j Graph Query - Reads dependency graph from Neo4j with same interface as DependencyGraphQuery.

Used by webapp when Neo4j is configured (primary source). Loads full graph into memory
to match nodes, edges, edges_from, edges_to, metadata, get_node, get_dependencies, get_dependents.
"""

from typing import Dict, List, Set, Optional
from collections import defaultdict

# Neo4j relationship type -> edge type (graph)
REL_TYPE_TO_EDGE = {
    "CONTAINS": "contains",
    "PRODUCES": "produces",
    "REQUIRES": "requires",
    "EXECUTES": "executes",
    "CALLS_PROGRAM": "calls_program",
    "CALLS": "calls",
    "INCLUDES": "includes",
    "DB_ACCESS": "db_access",
    "USES_SQL": "uses_sql",
    "DEPENDS_ON": "depends",
}


class Neo4jGraphQuery:
    """
    Query dependency graph from Neo4j. Same interface as DependencyGraphQuery:
    .nodes, .edges, .edges_from, .edges_to, .metadata, .get_node(), .get_dependencies(), .get_dependents(), .search_node().
    """

    def __init__(self, uri: str, user: Optional[str] = None, password: Optional[str] = None):
        self.uri = uri
        self.user = user or "neo4j"
        self.password = password or ""
        self._driver = None
        self.nodes = {}
        self.edges = []
        self.metadata = {}
        self.edges_from = defaultdict(list)
        self.edges_to = defaultdict(list)
        self.nodes_by_type = defaultdict(list)
        self._load_from_neo4j()

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

    def _load_from_neo4j(self):
        """Load all Node nodes and relationships into memory in DependencyGraphQuery shape."""
        self._driver_connect()

        with self._driver.session() as session:
            # Load nodes: MATCH (n:Node) RETURN n
            result = session.run("MATCH (n:Node) RETURN n")
            for record in result:
                n = record["n"]
                props = dict(n)  # Neo4j Node is dict-like
                node_id = props.get("id")
                if not node_id:
                    continue
                if "type" not in props:
                    props["type"] = "node"
                self.nodes[node_id] = props
                self.nodes_by_type[props["type"]].append(node_id)

            # Load edges: MATCH (a:Node)-[r]->(b:Node) RETURN a.id, type(r), b.id, properties(r)
            result = session.run(
                "MATCH (a:Node)-[r]->(b:Node) RETURN a.id AS from_id, type(r) AS rel_type, b.id AS to_id, properties(r) AS rel_props"
            )
            for record in result:
                from_id = record["from_id"]
                to_id = record["to_id"]
                rel_type = record["rel_type"] or ""
                rel_props = record["rel_props"] or {}
                edge_type = REL_TYPE_TO_EDGE.get(rel_type, "depends")
                edge = {
                    "from": from_id,
                    "to": to_id,
                    "type": edge_type,
                }
                for k, v in rel_props.items():
                    if k not in ("from_id", "to_id"):
                        edge[k] = v
                self.edges.append(edge)
                self.edges_from[from_id].append(edge)
                self.edges_to[to_id].append(edge)

        # Build metadata
        node_types = defaultdict(int)
        for node in self.nodes.values():
            node_types[node.get("type", "node")] += 1
        edge_types = defaultdict(int)
        for edge in self.edges:
            edge_types[edge["type"]] += 1
        self.metadata = {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "node_types": dict(node_types),
            "edge_types": dict(edge_types),
            "missing": {"jcls": [], "programs": [], "includes": []},
        }

    def get_node(self, node_id: str) -> Optional[Dict]:
        """Get node by ID."""
        return self.nodes.get(node_id)

    def get_dependencies(self, node_id: str, recursive: bool = False) -> Set[str]:
        """Get dependencies of a node (what it depends on)."""
        if not recursive:
            return {e["from"] for e in self.edges_to.get(node_id, [])}
        visited = set()
        to_visit = [node_id]
        while to_visit:
            current = to_visit.pop(0)
            if current in visited:
                continue
            visited.add(current)
            deps = {e["from"] for e in self.edges_to.get(current, [])}
            to_visit.extend(deps - visited)
        visited.discard(node_id)
        return visited

    def get_dependents(self, node_id: str, recursive: bool = False) -> Set[str]:
        """Get dependents of a node (what depends on it)."""
        if not recursive:
            return {e["to"] for e in self.edges_from.get(node_id, [])}
        visited = set()
        to_visit = [node_id]
        while to_visit:
            current = to_visit.pop(0)
            if current in visited:
                continue
            visited.add(current)
            deps = {e["to"] for e in self.edges_from.get(current, [])}
            to_visit.extend(deps - visited)
        visited.discard(node_id)
        return visited

    def search_node(self, name: str, node_type: Optional[str] = None) -> List[str]:
        """Search for nodes by name (case-insensitive)."""
        name_lower = name.lower()
        matches = []
        for node_id, node in self.nodes.items():
            if node_type and node.get("type") != node_type:
                continue
            if name_lower in (node.get("name") or "").lower():
                matches.append(node_id)
        return matches
