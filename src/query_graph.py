#!/usr/bin/env python3
"""
Query Dependency Graph - Interactive tool for exploring dependency graphs

Usage:
    python query_graph.py output/dependency_graph.json
    python query_graph.py output/dependency_graph.json --job TRALCLEA
    python query_graph.py output/dependency_graph.json --program ADAQOSL --deps
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Set
from collections import defaultdict


class DependencyGraphQuery:
    """Query and explore dependency graphs"""
    
    def __init__(self, graph_file: str):
        """Load the dependency graph"""
        self.graph_file = Path(graph_file)
        
        if not self.graph_file.exists():
            raise FileNotFoundError(f"Graph file not found: {graph_file}")
        
        with open(self.graph_file, 'r', encoding='utf-8') as f:
            self.data = json.load(f)
        
        self.nodes = self.data.get('nodes', {})
        self.edges = self.data.get('edges', [])
        self.metadata = self.data.get('metadata', {})
        
        # Build index for fast lookups
        self._build_indices()
    
    def _build_indices(self):
        """Build indices for fast lookups"""
        # Edges by source and target
        self.edges_from = defaultdict(list)  # node_id -> [edges]
        self.edges_to = defaultdict(list)    # node_id -> [edges]
        
        for edge in self.edges:
            self.edges_from[edge['from']].append(edge)
            self.edges_to[edge['to']].append(edge)
        
        # Nodes by type
        self.nodes_by_type = defaultdict(list)
        for node_id, node in self.nodes.items():
            self.nodes_by_type[node['type']].append(node_id)
    
    def search_node(self, name: str, node_type: str = None) -> List[str]:
        """Search for nodes by name (case-insensitive)"""
        name_lower = name.lower()
        matches = []
        
        for node_id, node in self.nodes.items():
            if node_type and node['type'] != node_type:
                continue
            
            if name_lower in node.get('name', '').lower():
                matches.append(node_id)
        
        return matches
    
    def get_node(self, node_id: str) -> Dict:
        """Get node by ID"""
        return self.nodes.get(node_id)
    
    def get_dependencies(self, node_id: str, recursive: bool = False) -> Set[str]:
        """
        Get dependencies of a node (what it depends on).
        
        Args:
            node_id: Node identifier
            recursive: If True, get transitive dependencies
        """
        if not recursive:
            return {edge['from'] for edge in self.edges_to.get(node_id, [])}
        
        # Recursive: BFS traversal
        visited = set()
        to_visit = [node_id]
        
        while to_visit:
            current = to_visit.pop(0)
            if current in visited:
                continue
            visited.add(current)
            
            # Add all nodes that current depends on
            deps = {edge['from'] for edge in self.edges_to.get(current, [])}
            to_visit.extend(deps - visited)
        
        visited.discard(node_id)
        return visited
    
    def get_dependents(self, node_id: str, recursive: bool = False) -> Set[str]:
        """
        Get dependents of a node (what depends on it).
        
        Args:
            node_id: Node identifier
            recursive: If True, get transitive dependents
        """
        if not recursive:
            return {edge['to'] for edge in self.edges_from.get(node_id, [])}
        
        # Recursive: BFS traversal
        visited = set()
        to_visit = [node_id]
        
        while to_visit:
            current = to_visit.pop(0)
            if current in visited:
                continue
            visited.add(current)
            
            # Add all nodes that depend on current
            deps = {edge['to'] for edge in self.edges_from.get(current, [])}
            to_visit.extend(deps - visited)
        
        visited.discard(node_id)
        return visited
    
    def get_full_chain(self, node_id: str) -> Dict:
        """Get complete dependency chain for a node"""
        node = self.get_node(node_id)
        
        if not node:
            return {'error': f'Node not found: {node_id}'}
        
        direct_deps = self.get_dependencies(node_id, recursive=False)
        all_deps = self.get_dependencies(node_id, recursive=True)
        
        direct_dependents = self.get_dependents(node_id, recursive=False)
        all_dependents = self.get_dependents(node_id, recursive=True)
        
        return {
            'node': node,
            'direct_dependencies': sorted(list(direct_deps)),
            'all_dependencies': sorted(list(all_deps)),
            'direct_dependents': sorted(list(direct_dependents)),
            'all_dependents': sorted(list(all_dependents)),
            'direct_deps_count': len(direct_deps),
            'all_deps_count': len(all_deps),
            'direct_dependents_count': len(direct_dependents),
            'all_dependents_count': len(all_dependents)
        }
    
    def get_path(self, from_node: str, to_node: str) -> List[List[str]]:
        """
        Find all paths from one node to another.
        
        Returns list of paths (each path is a list of node IDs)
        """
        if from_node not in self.nodes or to_node not in self.nodes:
            return []
        
        paths = []
        visited = set()
        
        def dfs(current: str, target: str, path: List[str]):
            if current == target:
                paths.append(path.copy())
                return
            
            if current in visited or len(path) > 50:  # Limit depth
                return
            
            visited.add(current)
            
            # Follow edges from current node
            for edge in self.edges_from.get(current, []):
                next_node = edge['to']
                dfs(next_node, target, path + [next_node])
            
            visited.discard(current)
        
        dfs(from_node, to_node, [from_node])
        return paths
    
    def find_cycles(self, node_id: str) -> List[List[str]]:
        """Find circular dependencies involving a node"""
        cycles = []
        
        # Check if node depends on itself (directly or indirectly)
        deps = self.get_dependencies(node_id, recursive=True)
        
        if node_id in deps or any(node_id in self.get_dependencies(dep, recursive=True) for dep in deps):
            # Find actual cycles
            paths = self.get_path(node_id, node_id)
            cycles.extend(paths)
        
        return cycles
    
    def get_impact_analysis(self, node_id: str) -> Dict:
        """Analyze the impact of changing a node"""
        node = self.get_node(node_id)
        
        if not node:
            return {'error': f'Node not found: {node_id}'}
        
        all_dependents = self.get_dependents(node_id, recursive=True)
        
        # Group dependents by type
        impacted_by_type = defaultdict(set)
        for dep_id in all_dependents:
            dep_node = self.get_node(dep_id)
            if dep_node:
                impacted_by_type[dep_node['type']].add(dep_id)
        
        return {
            'node': node,
            'total_impacted': len(all_dependents),
            'impacted_by_type': {
                node_type: sorted(list(nodes))
                for node_type, nodes in impacted_by_type.items()
            }
        }
    
    def print_summary(self):
        """Print graph summary"""
        print("\n" + "="*60)
        print("DEPENDENCY GRAPH SUMMARY")
        print("="*60)
        print(f"\nGraph file: {self.graph_file}")
        print(f"Total nodes: {self.metadata.get('total_nodes', len(self.nodes))}")
        print(f"Total edges: {self.metadata.get('total_edges', len(self.edges))}")
        
        print("\nNodes by type:")
        node_types = self.metadata.get('node_types', {})
        for node_type, count in sorted(node_types.items()):
            print(f"  {node_type:20} {count:>5}")
        
        print("\nEdges by type:")
        edge_types = self.metadata.get('edge_types', {})
        for edge_type, count in sorted(edge_types.items()):
            print(f"  {edge_type:20} {count:>5}")
        
        # Missing references
        missing = self.metadata.get('missing', {})
        if any(missing.values()):
            print("\nMissing references:")
            for category, items in missing.items():
                if items:
                    print(f"  {category}: {len(items)}")
    
    def print_node_info(self, node_id: str, show_deps: bool = False, show_dependents: bool = False):
        """Print detailed node information"""
        chain = self.get_full_chain(node_id)
        
        if 'error' in chain:
            print(f"Error: {chain['error']}")
            return
        
        node = chain['node']
        
        print("\n" + "="*60)
        print(f"{node['type'].upper()}: {node['name']}")
        print("="*60)
        
        # Node details
        for key, value in node.items():
            if key not in ['id', 'type', 'name', 'missing']:
                if value and value != []:
                    print(f"  {key}: {value}")
        
        # Dependencies
        print(f"\nDirect Dependencies: {chain['direct_deps_count']}")
        if show_deps and chain['direct_dependencies']:
            for dep_id in chain['direct_dependencies'][:20]:
                dep_node = self.get_node(dep_id)
                if dep_node:
                    print(f"  -> {dep_node['name']} ({dep_node['type']})")
            if len(chain['direct_dependencies']) > 20:
                print(f"  ... and {len(chain['direct_dependencies']) - 20} more")
        
        print(f"\nAll Dependencies (recursive): {chain['all_deps_count']}")
        
        # Dependents
        print(f"\nDirect Dependents: {chain['direct_dependents_count']}")
        if show_dependents and chain['direct_dependents']:
            for dep_id in chain['direct_dependents'][:20]:
                dep_node = self.get_node(dep_id)
                if dep_node:
                    print(f"  <- {dep_node['name']} ({dep_node['type']})")
            if len(chain['direct_dependents']) > 20:
                print(f"  ... and {len(chain['direct_dependents']) - 20} more")
        
        print(f"\nAll Dependents (recursive): {chain['all_dependents_count']}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Query and explore dependency graphs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show graph summary
  python query_graph.py output/dependency_graph.json

  # Query a Control-M job
  python query_graph.py output/graph.json --job TRALCLEA --deps

  # Query a PL/I program
  python query_graph.py output/graph.json --program ADAQOSL --deps --dependents

  # Find path between two nodes
  python query_graph.py output/graph.json --path TRALCLEA ADAQOSL

  # Impact analysis
  python query_graph.py output/graph.json --impact "DB::VPGMSTEUERUNG"

  # Search nodes
  python query_graph.py output/graph.json --search "ADAQO"
        """
    )
    
    parser.add_argument('graph_file', help='Path to dependency graph JSON file')
    
    # Query options
    parser.add_argument('--job', metavar='NAME', help='Query a Control-M job')
    parser.add_argument('--program', metavar='NAME', help='Query a PL/I program')
    parser.add_argument('--jcl', metavar='NAME', help='Query a JCL file')
    parser.add_argument('--table', metavar='NAME', help='Query a database table')
    
    parser.add_argument('--deps', action='store_true', help='Show dependencies')
    parser.add_argument('--dependents', action='store_true', help='Show dependents')
    
    parser.add_argument('--path', nargs=2, metavar=('FROM', 'TO'), 
                       help='Find path between two nodes')
    parser.add_argument('--impact', metavar='NODE', help='Impact analysis for a node')
    parser.add_argument('--search', metavar='KEYWORD', help='Search nodes by name')
    
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    
    args = parser.parse_args()
    
    try:
        query = DependencyGraphQuery(args.graph_file)
        
        # Search
        if args.search:
            matches = query.search_node(args.search)
            print(f"\nFound {len(matches)} matches for '{args.search}':")
            for node_id in matches:
                node = query.get_node(node_id)
                print(f"  {node_id} - {node.get('name')} ({node.get('type')})")
            return
        
        # Path finding
        if args.path:
            from_name, to_name = args.path
            from_matches = query.search_node(from_name)
            to_matches = query.search_node(to_name)
            
            if not from_matches:
                print(f"Error: No matches for '{from_name}'")
                return
            if not to_matches:
                print(f"Error: No matches for '{to_name}'")
                return
            
            from_node = from_matches[0]
            to_node = to_matches[0]
            
            paths = query.get_path(from_node, to_node)
            
            print(f"\nPaths from {from_node} to {to_node}:")
            if not paths:
                print("  No path found")
            else:
                for i, path in enumerate(paths[:10], 1):
                    print(f"\n  Path {i}:")
                    for node_id in path:
                        node = query.get_node(node_id)
                        print(f"    -> {node.get('name')} ({node.get('type')})")
                if len(paths) > 10:
                    print(f"\n  ... and {len(paths) - 10} more paths")
            return
        
        # Impact analysis
        if args.impact:
            matches = query.search_node(args.impact)
            if not matches:
                print(f"Error: No matches for '{args.impact}'")
                return
            
            impact = query.get_impact_analysis(matches[0])
            
            if args.json:
                print(json.dumps(impact, indent=2))
            else:
                node = impact['node']
                print(f"\n{'='*60}")
                print(f"IMPACT ANALYSIS: {node['name']}")
                print('='*60)
                print(f"\nTotal nodes impacted: {impact['total_impacted']}")
                print("\nImpacted nodes by type:")
                for node_type, nodes in impact['impacted_by_type'].items():
                    print(f"\n  {node_type} ({len(nodes)}):")
                    for node_id in nodes[:10]:
                        n = query.get_node(node_id)
                        print(f"    - {n.get('name')}")
                    if len(nodes) > 10:
                        print(f"    ... and {len(nodes) - 10} more")
            return
        
        # Query specific node
        node_id = None
        if args.job:
            matches = query.search_node(args.job, 'controlm_job')
            node_id = matches[0] if matches else f"CONTROLM::{args.job}"
        elif args.program:
            matches = query.search_node(args.program, 'pl1_program')
            node_id = matches[0] if matches else f"PL1::{args.program}"
        elif args.jcl:
            matches = query.search_node(args.jcl, 'jcl')
            node_id = matches[0] if matches else f"JCL::{args.jcl}"
        elif args.table:
            matches = query.search_node(args.table, 'db_table')
            node_id = matches[0] if matches else f"DB::{args.table}"
        
        if node_id:
            if args.json:
                chain = query.get_full_chain(node_id)
                print(json.dumps(chain, indent=2))
            else:
                query.print_node_info(node_id, show_deps=args.deps, show_dependents=args.dependents)
        else:
            # Default: show summary
            query.print_summary()
    
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
