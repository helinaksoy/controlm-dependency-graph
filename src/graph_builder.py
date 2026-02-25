"""
Dependency Graph Builder - Orchestrates all parsers to build a unified dependency graph

Multi-level dependency resolution:
1. Control-M Job → Job (via INCOND/OUTCOND)
2. Control-M Job → PL/I Program (via DESCRIPTION field: 'PROGNAME = ...')
3. PL/I Program → PL/I Program (via CALL)
4. PL/I Program → Include Files (via %INCLUDE)
5. PL/I Program → DB Tables (via EXEC SQL)
"""

import json
from pathlib import Path
from typing import Dict, List, Set, Optional
from collections import defaultdict

from parsers.controlm_parser import ControlMParser
from parsers.jcl_parser import JCLParser
from parsers.pl1_parser import PL1Parser


class DependencyGraphBuilder:
    """Builds a unified multi-level dependency graph"""
    
    def __init__(self, config_dir: str = 'src/config'):
        """
        Initialize the graph builder.
        
        Args:
            config_dir: Directory containing path_mappings.json and program_mappings.json
        """
        self.config_dir = Path(config_dir)
        
        # Initialize parsers
        self.controlm_parser = ControlMParser()
        self.jcl_parser = JCLParser()
        self.pl1_parser = PL1Parser()
        
        # Load configuration
        self.path_mappings = self._load_config('path_mappings.json')
        self.program_mappings = self._load_config('program_mappings.json')
        
        # Data structures
        self.controlm_data = {}
        self.jcl_data = {}  # jcl_name -> parsed JCL
        self.pl1_data = {}  # program_name -> parsed PL/I
        self.pl1_file_index = {}  # filename_stem.upper() -> program_name (fallback lookup)
        self.inc_file_index = {}   # filename_stem.upper() -> file_path (include files in v250)
        
        # Unified dependency graph
        self.graph = {
            'nodes': {},  # id -> node data
            'edges': []   # list of {from, to, type}
        }
        
        # Missing references tracking
        self.missing_jcls = set()
        self.missing_programs = set()
        self.missing_includes = set()
        
    def _load_config(self, filename: str) -> Dict:
        """Load a configuration JSON file"""
        config_path = self.config_dir / filename
        
        if not config_path.exists():
            return {}
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Filter out comment keys
                return {k: v for k, v in data.items() if not k.startswith('_')}
        except Exception as e:
            print(f"Error loading {filename}: {e}")
            return {}
    
    def build_graph(self, 
                   controlm_xml: Optional[str] = None,
                   jcl_directory: Optional[str] = None,
                   pl1_directory: Optional[str] = None) -> Dict:
        """
        Build the complete dependency graph.
        
        Args:
            controlm_xml: Path to Control-M XML export file
            jcl_directory: Directory containing JCL files (alternative to path_mappings)
            pl1_directory: Directory containing PL/I files (alternative to program_mappings)
            
        Returns:
            Complete dependency graph dictionary
        """
        print("="*60)
        print("BUILDING MULTI-LEVEL DEPENDENCY GRAPH")
        print("="*60)
        
        # Step 1: Parse Control-M XML
        if controlm_xml:
            print("\n[1/3] Parsing Control-M XML...")
            self.controlm_data = self.controlm_parser.parse_file(controlm_xml)
            self._add_controlm_nodes()

        # Step 2: Parse PL/I files
        print("\n[2/3] Parsing PL/I files...")
        self._parse_pl1_files(pl1_directory)

        # Step 3: Build relationships
        print("\n[3/3] Building relationships...")
        self._build_relationships()
        
        # Summary
        self._print_summary()
        
        return self._export_graph()
    
    def _add_controlm_nodes(self):
        """Add Control-M hierarchy (Folder/Application/SubApplication), Job, and Condition nodes"""
        if 'error' in self.controlm_data:
            print(f"  [X] Error: {self.controlm_data['error']}")
            return

        jobs = self.controlm_data.get('jobs', {})
        folders_data = self.controlm_data.get('folders', {})

        # --- Folder nodes ---
        for folder_name, folder_info in folders_data.items():
            if not folder_name:
                continue
            node_id = f"FOLDER::{folder_name}"
            self.graph['nodes'][node_id] = {
                'id': node_id,
                'type': 'folder',
                'name': folder_name,
                'datacenter': folder_info.get('datacenter', ''),
                'platform': folder_info.get('platform', ''),
            }

        # Hierarchy: Application -> SubApplication -> Folder -> Job
        app_subapps = defaultdict(set)    # app -> {subapp, ...}
        subapp_folders = defaultdict(set) # subapp -> {folder, ...}
        folder_jobs = defaultdict(list)   # folder -> [jobname, ...]

        for jobname, job_info in jobs.items():
            folder = job_info.get('folder', '')
            app = job_info.get('application', '')
            sub_app = job_info.get('sub_application', '')
            if app and sub_app:
                app_subapps[app].add(sub_app)
            if sub_app and folder:
                subapp_folders[sub_app].add(folder)
            if folder:
                folder_jobs[folder].append(jobname)

        # --- Application nodes ---
        all_apps = set(app_subapps.keys())
        for app_name in all_apps:
            node_id = f"APP::{app_name}"
            self.graph['nodes'][node_id] = {
                'id': node_id,
                'type': 'application',
                'name': app_name,
            }

        # --- SubApplication nodes ---
        all_subapps = set(subapp_folders.keys()) | {s for subapps in app_subapps.values() for s in subapps}
        for subapp_name in all_subapps:
            node_id = f"SUBAPP::{subapp_name}"
            self.graph['nodes'][node_id] = {
                'id': node_id,
                'type': 'sub_application',
                'name': subapp_name,
            }

        # --- Job nodes (keep folder/application/sub_application as properties for backward compat) ---
        for jobname, job_info in jobs.items():
            node_id = f"CONTROLM::{jobname}"
            self.graph['nodes'][node_id] = {
                'id': node_id,
                'type': 'controlm_job',
                'name': jobname,
                'application': job_info.get('application', ''),
                'sub_application': job_info.get('sub_application', ''),
                'folder': job_info.get('folder', ''),
                'memname': job_info.get('memname', ''),
                'memlib': job_info.get('memlib', ''),
                'tasktype': job_info.get('tasktype', ''),
                'description': job_info.get('description', ''),
            }

        # --- Condition nodes (with producer/consumer job names for name matching) ---
        conditions = self.controlm_data.get('conditions', {})
        inputs = conditions.get('inputs', {})   # cond_name -> [jobs that REQUIRE this]
        outputs = conditions.get('outputs', {}) # cond_name -> [jobs that PRODUCE this]
        all_cond_names = set(inputs.keys()) | set(outputs.keys())
        for cond_name in all_cond_names:
            node_id = f"COND::{cond_name}"
            self.graph['nodes'][node_id] = {
                'id': node_id,
                'type': 'condition',
                'name': cond_name,
                'producer_jobs': list(outputs.get(cond_name, [])),
                'consuming_jobs': list(inputs.get(cond_name, [])),
            }

        # --- CONTAINS edges: Application -> SubApplication -> Folder -> Job ---
        contains_count = 0
        seen_contains = set()
        for app, subapps in app_subapps.items():
            for subapp in subapps:
                key = (f"APP::{app}", f"SUBAPP::{subapp}")
                if key not in seen_contains:
                    seen_contains.add(key)
                    self.graph['edges'].append({
                        'from': key[0], 'to': key[1],
                        'type': 'contains', 'label': 'contains',
                    })
                    contains_count += 1
        for subapp, folders in subapp_folders.items():
            for folder in folders:
                key = (f"SUBAPP::{subapp}", f"FOLDER::{folder}")
                if key not in seen_contains:
                    seen_contains.add(key)
                    self.graph['edges'].append({
                        'from': key[0], 'to': key[1],
                        'type': 'contains', 'label': 'contains',
                    })
                    contains_count += 1
        for folder, jobnames in folder_jobs.items():
            for jn in jobnames:
                key = (f"FOLDER::{folder}", f"CONTROLM::{jn}")
                if key not in seen_contains:
                    seen_contains.add(key)
                    self.graph['edges'].append({
                        'from': key[0], 'to': key[1],
                        'type': 'contains', 'label': 'contains',
                    })
                    contains_count += 1

        # --- PRODUCES / REQUIRES edges (replace old job_dependency) ---
        produces_count = 0
        requires_count = 0
        for jobname, job_info in jobs.items():
            for outcond in job_info.get('outconds', []):
                cond_name = outcond.get('name', '')
                if not cond_name:
                    continue
                self.graph['edges'].append({
                    'from': f"CONTROLM::{jobname}",
                    'to': f"COND::{cond_name}",
                    'type': 'produces',
                    'label': 'produces',
                    'sign': outcond.get('sign', '+'),
                    'odate': outcond.get('odate', ''),
                })
                produces_count += 1
            for incond in job_info.get('inconds', []):
                cond_name = incond.get('name', '')
                if not cond_name:
                    continue
                self.graph['edges'].append({
                    'from': f"CONTROLM::{jobname}",
                    'to': f"COND::{cond_name}",
                    'type': 'requires',
                    'label': 'requires',
                    'and_or': incond.get('and_or', 'A'),
                    'odate': incond.get('odate', ''),
                })
                requires_count += 1

        print(f"  [OK] Added {len(folders_data)} folders, {len(all_apps)} applications, {len(all_subapps)} sub-applications")
        print(f"  [OK] Added {len(jobs)} Control-M jobs")
        print(f"  [OK] Added {len(all_cond_names)} conditions")
        print(f"  [OK] Added {contains_count} CONTAINS, {produces_count} PRODUCES, {requires_count} REQUIRES edges")
    
    def _parse_jcl_files(self, jcl_directory: Optional[str]):
        """Parse JCL files from mappings or directory"""
        if jcl_directory:
            # Parse entire directory
            self.jcl_data = self.jcl_parser.parse_directory(jcl_directory)
        else:
            # Parse individual files from mappings
            for memname, jcl_path in self.path_mappings.items():
                full_path = Path(jcl_path)
                if full_path.exists():
                    result = self.jcl_parser.parse_file(str(full_path))
                    if 'error' not in result:
                        self.jcl_data[result['jcl_name']] = result
                else:
                    self.missing_jcls.add(memname)
                    print(f"  [WARN] JCL not found: {jcl_path}")
        
        # Add JCL nodes
        for jcl_name, jcl_info in self.jcl_data.items():
            node_id = f"JCL::{jcl_name}"
            self.graph['nodes'][node_id] = {
                'id': node_id,
                'type': 'jcl',
                'name': jcl_name,
                'file_path': jcl_info.get('file_path', ''),
                'programs_called': jcl_info.get('programs_called', []),
                'procs_called': jcl_info.get('procs_called', []),
                'datasets': jcl_info.get('datasets', []),
                'steps': jcl_info.get('steps', [])
            }
        
        print(f"  [OK] Parsed {len(self.jcl_data)} JCL files")
        if self.missing_jcls:
            print(f"  [WARN] Missing {len(self.missing_jcls)} JCL files")
    
    def _parse_pl1_files(self, pl1_directory: Optional[str]):
        """Parse PL/I files from mappings or directory"""
        if pl1_directory:
            # Parse entire directory
            self.pl1_data = self.pl1_parser.parse_directory(pl1_directory)
            # Build filename-stem → program_name fallback index
            # (handles cases where #PROC name differs from the file name)
            self.pl1_file_index = {
                Path(info['file_path']).stem.upper(): name
                for name, info in self.pl1_data.items()
                if info.get('file_path')
            }
            # Build include file index: stem.upper() -> file_path
            self.inc_file_index = {
                f.stem.upper(): str(f)
                for f in Path(pl1_directory).rglob('*.inc')
            }
            print(f"  [OK] Found {len(self.inc_file_index)} include files (.inc) in {pl1_directory}")
        else:
            # Parse individual files from mappings
            for program_name, pl1_path in self.program_mappings.items():
                full_path = Path(pl1_path)
                if full_path.exists():
                    result = self.pl1_parser.parse_file(str(full_path))
                    if 'error' not in result:
                        self.pl1_data[result['program_name']] = result
                else:
                    self.missing_programs.add(program_name)
                    print(f"  [WARN] PL/I not found: {pl1_path}")
        
        # Add PL/I nodes
        for program_name, pl1_info in self.pl1_data.items():
            node_id = f"PL1::{program_name}"
            self.graph['nodes'][node_id] = {
                'id': node_id,
                'type': 'pl1_program',
                'name': program_name,
                'file_path': pl1_info.get('file_path', ''),
                'procedures': pl1_info.get('procedures', []),
                'calls': pl1_info.get('calls', []),
                'includes': pl1_info.get('includes', []),
                'sql_tables': pl1_info.get('sql_tables', []),
                'sql_operations': pl1_info.get('sql_operations', {})
            }
        
        # Add DB table nodes
        all_tables = set()
        for pl1_info in self.pl1_data.values():
            all_tables.update(pl1_info.get('sql_tables', []))
        
        for table_name in all_tables:
            node_id = f"DB::{table_name}"
            if node_id not in self.graph['nodes']:
                self.graph['nodes'][node_id] = {
                    'id': node_id,
                    'type': 'db_table',
                    'name': table_name
                }
        
        print(f"  [OK] Parsed {len(self.pl1_data)} PL/I programs")
        print(f"  [OK] Found {len(all_tables)} unique database tables")
        if self.missing_programs:
            print(f"  [WARN] Missing {len(self.missing_programs)} PL/I programs")
    
    @staticmethod
    def _extract_desc_program(description: str) -> str:
        """Extract program name from description: 'PROGNAME = ...' → 'PROGNAME'"""
        if not description or '=' not in description:
            return ''
        candidate = description.split('=')[0].strip()
        if candidate and ' ' not in candidate:
            return candidate.upper()
        return ''

    def _link_controlm_to_pl1_direct(self):
        """Link Control-M jobs directly to PL/I programs via DESCRIPTION field."""
        # Programs that are utilities/OS tools, not real PL/I source files
        _SKIP = {
            'DUMMY', 'MFCMDLNE', 'SCRIPT', 'REXX', 'IEFBR14', 'FTP', 'FTPLS',
            'IEBGENER', 'ALLOC', 'CONDCHK', 'BACKUP', 'UNLOAD', 'DB2UTIL',
            'DSNTEP2', 'IKJEFT01', 'RZWRITER', 'IOACND', 'DB2LOAD',
        }
        count = 0
        for jobname, job_info in self.controlm_data.get('jobs', {}).items():
            description = job_info.get('description', '')
            prog = self._extract_desc_program(description)
            if not prog or prog in _SKIP:
                continue
            # Try program name first, then filename stem as fallback
            resolved = prog if prog in self.pl1_data else self.pl1_file_index.get(prog)
            if resolved:
                self.graph['edges'].append({
                    'from': f"CONTROLM::{jobname}",
                    'to': f"PL1::{resolved}",
                    'type': 'executes',
                    'label': 'executes',
                })
                count += 1
        print(f"  [OK] Linked {count} Control-M jobs directly to PL/I programs")

    def _build_relationships(self):
        """Build all dependency relationships"""
        edge_count = len(self.graph['edges'])

        # 1. Control-M Job → PL/I (direct via description)
        self._link_controlm_to_pl1_direct()

        # 2. PL/I → PL/I (CALL dependencies)
        self._link_pl1_to_pl1()

        # 3. PL/I → Include Files
        self._link_pl1_to_includes()

        # 4. PL/I → Database Tables
        self._link_pl1_to_db()

        new_edges = len(self.graph['edges']) - edge_count
        print(f"  [OK] Created {new_edges} cross-layer dependencies")
    
    def _link_controlm_to_jcl(self):
        """Link Control-M jobs to their JCL files"""
        for jobname, job_info in self.controlm_data.get('jobs', {}).items():
            memname = job_info.get('memname', '')
            if not memname:
                continue
            
            # Extract JCL name from MEMNAME (e.g., "AUCOPY.jcl" → "AUCOPY")
            jcl_name = memname.replace('.jcl', '').upper()
            
            if jcl_name in self.jcl_data:
                self.graph['edges'].append({
                    'from': f"CONTROLM::{jobname}",
                    'to': f"JCL::{jcl_name}",
                    'type': 'executes',
                    'label': 'runs'
                })
            else:
                if memname not in self.missing_jcls:
                    self.missing_jcls.add(memname)
    
    def _link_jcl_to_pl1(self):
        """Link JCL files to PL/I programs they call"""
        for jcl_name, jcl_info in self.jcl_data.items():
            programs = jcl_info.get('programs_called', [])
            
            for program_name in programs:
                if program_name in self.pl1_data:
                    self.graph['edges'].append({
                        'from': f"JCL::{jcl_name}",
                        'to': f"PL1::{program_name}",
                        'type': 'calls_program',
                        'label': 'executes'
                    })
                else:
                    if program_name not in self.missing_programs:
                        self.missing_programs.add(program_name)
    
    def _link_pl1_to_pl1(self):
        """Link PL/I programs to other PL/I programs they call"""
        for program_name, pl1_info in self.pl1_data.items():
            calls = pl1_info.get('calls', [])
            
            for called_program in calls:
                # Resolve: program name first, filename stem as fallback
                # If not found in v250 source at all — skip (no ghost nodes)
                resolved = called_program if called_program in self.pl1_data \
                           else self.pl1_file_index.get(called_program)
                if not resolved:
                    continue

                self.graph['edges'].append({
                    'from': f"PL1::{program_name}",
                    'to': f"PL1::{resolved}",
                    'type': 'calls',
                    'label': 'CALL'
                })
    
    def _link_pl1_to_includes(self):
        """Link PL/I programs to include files"""
        for program_name, pl1_info in self.pl1_data.items():
            includes = pl1_info.get('includes', [])
            
            for include_file in includes:
                # Skip if this include doesn't exist as a real .inc file in v250
                if include_file not in self.inc_file_index:
                    continue

                include_node_id = f"INCLUDE::{include_file}"

                # Create include node if not exists
                if include_node_id not in self.graph['nodes']:
                    self.graph['nodes'][include_node_id] = {
                        'id': include_node_id,
                        'type': 'include_file',
                        'name': include_file,
                        'file_path': self.inc_file_index[include_file],
                    }

                self.graph['edges'].append({
                    'from': f"PL1::{program_name}",
                    'to': include_node_id,
                    'type': 'includes',
                    'label': '%INCLUDE'
                })
    
    def _link_pl1_to_db(self):
        """Link PL/I programs to database tables"""
        for program_name, pl1_info in self.pl1_data.items():
            sql_operations = pl1_info.get('sql_operations', {})
            
            for table_name, operations in sql_operations.items():
                for operation in operations:
                    self.graph['edges'].append({
                        'from': f"PL1::{program_name}",
                        'to': f"DB::{table_name}",
                        'type': 'db_access',
                        'label': operation,
                        'operation': operation
                    })
    
    def _print_summary(self):
        """Print summary statistics"""
        print("\n" + "="*60)
        print("DEPENDENCY GRAPH SUMMARY")
        print("="*60)
        
        # Node counts by type
        node_types = defaultdict(int)
        for node in self.graph['nodes'].values():
            node_types[node['type']] += 1
        
        print("\nNodes:")
        for node_type, count in sorted(node_types.items()):
            print(f"  {node_type:20} {count:>5}")
        print(f"  {'TOTAL':20} {len(self.graph['nodes']):>5}")
        
        # Edge counts by type
        edge_types = defaultdict(int)
        for edge in self.graph['edges']:
            edge_types[edge['type']] += 1
        
        print("\nEdges:")
        for edge_type, count in sorted(edge_types.items()):
            print(f"  {edge_type:20} {count:>5}")
        print(f"  {'TOTAL':20} {len(self.graph['edges']):>5}")
        
        # Warnings
        if self.missing_programs or self.missing_includes:
            print("\nWarnings:")
            if self.missing_programs:
                print(f"  [WARN] {len(self.missing_programs)} missing PL/I programs (called but not in source dir)")
            if self.missing_includes:
                print(f"  [WARN] {len(self.missing_includes)} missing include files")
    
    def _export_graph(self) -> Dict:
        """Export the complete graph"""
        return {
            'metadata': {
                'total_nodes': len(self.graph['nodes']),
                'total_edges': len(self.graph['edges']),
                'node_types': {
                    node_type: len([n for n in self.graph['nodes'].values() if n['type'] == node_type])
                    for node_type in set(n['type'] for n in self.graph['nodes'].values())
                },
                'edge_types': {
                    edge_type: len([e for e in self.graph['edges'] if e['type'] == edge_type])
                    for edge_type in set(e['type'] for e in self.graph['edges'])
                },
                'missing': {
                    'jcls': sorted(list(self.missing_jcls)),
                    'programs': sorted(list(self.missing_programs)),
                    'includes': sorted(list(self.missing_includes))
                }
            },
            'nodes': self.graph['nodes'],
            'edges': self.graph['edges'],
            'controlm_data': self.controlm_data
        }
    
    def save_graph(self, output_file: str):
        """Save the graph to a JSON file"""
        graph_data = self._export_graph()
        
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(graph_data, f, indent=2, ensure_ascii=False)
        
        print(f"\n[OK] Graph saved to: {output_path}")
        print(f"  File size: {output_path.stat().st_size / 1024:.1f} KB")
