#!/usr/bin/env python3
"""
Build Dependency Graph - Main CLI tool for building multi-level dependency graphs

Usage:
    python build_dependency_graph.py --controlm data/GlobalControlMExport_PROD.xml --output output/dependency_graph.json
    python build_dependency_graph.py --jcl-dir data/jcl --pl1-dir data/pl1 --output output/graph.json
    python build_dependency_graph.py --help
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent))

from graph_builder import DependencyGraphBuilder

# Default config path: config.json in project root (parent of src/)
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def load_config():
    """Load config.json if it exists. Returns dict (possibly empty)."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if not str(k).startswith("_")}
    except Exception:
        return {}


def apply_config_defaults(args):
    """Fill in args from config when not provided on command line. JSON output is optional (only if output/config set)."""
    cfg = load_config()
    if not cfg:
        return
    if args.controlm is None:
        args.controlm = cfg.get("controlm_xml")
    if args.code_dir is None:
        args.code_dir = cfg.get("code_dir")
    if args.jcl_dir is None:
        args.jcl_dir = cfg.get("jcl_dir")
    if args.pl1_dir is None:
        args.pl1_dir = cfg.get("pl1_dir")
    if args.output is None:
        args.output = cfg.get("output")
    if getattr(args, "neo4j_uri", None) is None:
        setattr(args, "neo4j_uri", cfg.get("neo4j_uri") or os.environ.get("NEO4J_URI"))
    if getattr(args, "neo4j_user", None) is None:
        setattr(args, "neo4j_user", cfg.get("neo4j_user") or os.environ.get("NEO4J_USER", "neo4j"))
    if getattr(args, "neo4j_password", None) is None:
        setattr(args, "neo4j_password", cfg.get("neo4j_password") or os.environ.get("NEO4J_PASSWORD", ""))


def parse_arguments():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description='Build multi-level dependency graph from Control-M, JCL, and PL/I files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Primary: write to Neo4j only (set neo4j_uri in config or NEO4J_URI)
  python build_dependency_graph.py --controlm data/export.xml

  # Neo4j + optional JSON file
  python build_dependency_graph.py --controlm data/export.xml --output output/graph.json

  # JSON only (no Neo4j)
  python build_dependency_graph.py --controlm data/export.xml -o output/graph.json

  # Full pipeline with code directory
  python build_dependency_graph.py --controlm data/export.xml --code-dir data --neo4j-uri bolt://localhost:7687

Configuration:
  - config.json: neo4j_uri (primary), neo4j_user, neo4j_password, output (optional JSON path)
  - Env: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
  - JSON is written only when --output or config output is set
        """
    )
    
    # Input sources
    parser.add_argument(
        '--controlm',
        metavar='FILE',
        default=r'C:\AVC\Workspace\GlobalControlMExport_PROD.xml',
        help='Path to Control-M XML export file (default: C:\\AVC\\Workspace\\GlobalControlMExport_PROD.xml)'
    )
    
    parser.add_argument(
        '--code-dir',
        metavar='DIR',
        help='Directory containing both JCL and PL/I files (auto-discover mode, replaces --jcl-dir and --pl1-dir)'
    )

    parser.add_argument(
        '--jcl-dir',
        metavar='DIR',
        default=r'C:\AVC\Workspace\v250',
        help='Directory containing JCL files (default: C:\\AVC\\Workspace\\v250)'
    )
    
    parser.add_argument(
        '--pl1-dir',
        metavar='DIR',
        default=r'C:\AVC\Workspace\v250',
        help='Directory containing PL/I files (default: C:\\AVC\\Workspace\\v250)'
    )
    
    # Configuration
    parser.add_argument(
        '--config-dir',
        metavar='DIR',
        default='src/config',
        help='Directory containing configuration files (default: src/config)'
    )
    
    # Output: Neo4j (primary) and JSON (optional)
    parser.add_argument(
        '--neo4j-uri',
        metavar='URI',
        default=None,
        help='Neo4j connection URI (e.g. bolt://localhost:7687). Primary pipeline; also from config or NEO4J_URI.'
    )
    parser.add_argument(
        '--neo4j-user',
        metavar='USER',
        default=None,
        help='Neo4j user (default: from config or NEO4J_USER or neo4j)'
    )
    parser.add_argument(
        '--neo4j-password',
        metavar='PASS',
        default=None,
        help='Neo4j password (default: from config or NEO4J_PASSWORD)'
    )
    parser.add_argument(
        '--output',
        '-o',
        metavar='FILE',
        default=None,
        help='Optional: also write graph to this JSON file. Omit to write only to Neo4j.'
    )
    
    # Utility commands
    parser.add_argument(
        '--list-memnames',
        action='store_true',
        help='List all MEMNAME values from Control-M XML (for configuring path_mappings.json)'
    )
    
    parser.add_argument(
        '--list-programs',
        action='store_true',
        help='List all program names found in JCL files (for configuring program_mappings.json)'
    )
    
    parser.add_argument(
        '--validate-config',
        action='store_true',
        help='Validate configuration files and report missing mappings'
    )
    
    return parser.parse_args()


def list_memnames(controlm_xml: str):
    """List all MEMNAME values from Control-M XML"""
    print("Extracting MEMNAME values from Control-M XML...")
    
    from parsers.controlm_parser import ControlMParser
    
    parser = ControlMParser()
    data = parser.parse_file(controlm_xml)
    
    if 'error' in data:
        print(f"Error: {data['error']}")
        return
    
    jobs_with_jcl = parser.get_jobs_with_jcl()
    
    print(f"\nFound {len(jobs_with_jcl)} jobs with MEMNAME:")
    print("\nAdd these to src/config/path_mappings.json:")
    print("-" * 60)
    
    unique_memnames = sorted(set(job['memname'] for job in jobs_with_jcl.values()))
    
    for memname in unique_memnames:
        print(f'  "{memname}": "path/to/{memname}",')
    
    print()


def list_programs(jcl_dir: str):
    """List all program names from JCL files"""
    print(f"Extracting program names from JCL files in {jcl_dir}...")
    
    from parsers.jcl_parser import JCLParser
    
    parser = JCLParser()
    jcl_data = parser.parse_directory(jcl_dir)
    
    all_programs = set()
    for jcl_info in jcl_data.values():
        all_programs.update(jcl_info.get('programs_called', []))
    
    print(f"\nFound {len(all_programs)} unique programs:")
    print("\nAdd these to src/config/program_mappings.json:")
    print("-" * 60)
    
    for program in sorted(all_programs):
        print(f'  "{program}": "path/to/{program}.pl1",')
    
    print()


def validate_config(config_dir: str, controlm_xml: str = None, jcl_dir: str = None):
    """Validate configuration files"""
    print("Validating configuration files...")
    
    config_path = Path(config_dir)
    
    # Check if config files exist
    path_mappings_file = config_path / 'path_mappings.json'
    program_mappings_file = config_path / 'program_mappings.json'
    
    issues = []
    
    if not path_mappings_file.exists():
        issues.append(f"Missing: {path_mappings_file}")
    
    if not program_mappings_file.exists():
        issues.append(f"Missing: {program_mappings_file}")
    
    if issues:
        print("\n✗ Configuration issues:")
        for issue in issues:
            print(f"  - {issue}")
        return False
    
    # Load configs
    import json
    
    with open(path_mappings_file) as f:
        path_mappings = {k: v for k, v in json.load(f).items() if not k.startswith('_')}
    
    with open(program_mappings_file) as f:
        program_mappings = {k: v for k, v in json.load(f).items() if not k.startswith('_')}
    
    print(f"\n[OK] path_mappings.json: {len(path_mappings)} entries")
    print(f"[OK] program_mappings.json: {len(program_mappings)} entries")
    
    # Check if files exist
    missing_jcl = []
    for memname, path in path_mappings.items():
        if not Path(path).exists():
            missing_jcl.append(f"{memname} → {path}")
    
    missing_pl1 = []
    for program, path in program_mappings.items():
        if not Path(path).exists():
            missing_pl1.append(f"{program} → {path}")
    
    if missing_jcl:
        print(f"\n[WARN] Missing JCL files ({len(missing_jcl)}):")
        for item in missing_jcl[:10]:
            print(f"  - {item}")
        if len(missing_jcl) > 10:
            print(f"  ... and {len(missing_jcl) - 10} more")
    
    if missing_pl1:
        print(f"\n[WARN] Missing PL/I files ({len(missing_pl1)}):")
        for item in missing_pl1[:10]:
            print(f"  - {item}")
        if len(missing_pl1) > 10:
            print(f"  ... and {len(missing_pl1) - 10} more")
    
    if not missing_jcl and not missing_pl1:
        print("\n[OK] All configured files exist")
        return True
    
    return len(missing_jcl) + len(missing_pl1) == 0


def main():
    """Main entry point"""
    args = parse_arguments()
    apply_config_defaults(args)

    # Utility commands
    if args.list_memnames:
        if not args.controlm:
            print("Error: --controlm required for --list-memnames")
            sys.exit(1)
        list_memnames(args.controlm)
        return
    
    if args.list_programs:
        jcl_dir = args.jcl_dir or args.code_dir
        if not jcl_dir:
            print("Error: --jcl-dir or --code-dir required for --list-programs")
            sys.exit(1)
        list_programs(jcl_dir)
        return
    
    if args.validate_config:
        validate_config(args.config_dir, args.controlm, args.jcl_dir)
        return
    
    # Build graph
    if not args.controlm and not args.pl1_dir and not args.code_dir:
        print("Error: At least one input source required (--controlm, --pl1-dir, or --code-dir)")
        print("Run with --help for usage information")
        sys.exit(1)

    # --code-dir sets pl1-dir when not explicitly provided
    if args.code_dir:
        if not args.pl1_dir:
            args.pl1_dir = args.code_dir

    # Validate paths exist before building
    errors = []
    if args.controlm:
        p = Path(args.controlm)
        if not p.exists():
            errors.append(f"Control-M XML dosyası bulunamadı: {args.controlm}")
        elif not p.is_file():
            errors.append(f"Control-M XML yolu bir dosya değil: {args.controlm}")
    if args.pl1_dir:
        p = Path(args.pl1_dir)
        if not p.exists():
            errors.append(f"PL/I klasörü bulunamadı: {args.pl1_dir}")
        elif not p.is_dir():
            errors.append(f"PL/I yolu bir klasör değil: {args.pl1_dir}")
    if errors:
        for msg in errors:
            print(f"Error: {msg}")
        sys.exit(1)

    print("Initializing Dependency Graph Builder...")
    builder = DependencyGraphBuilder(config_dir=args.config_dir)
    
    try:
        graph = builder.build_graph(
            controlm_xml=args.controlm,
            jcl_directory=args.jcl_dir,
            pl1_directory=args.pl1_dir
        )

        # Pipeline 1 (primary): Neo4j
        if args.neo4j_uri:
            try:
                from neo4j_writer import Neo4jWriter
                writer = Neo4jWriter(
                    uri=args.neo4j_uri,
                    user=args.neo4j_user,
                    password=args.neo4j_password,
                )
                writer.write_graph(graph)
                writer.close()
            except Exception as e:
                print(f"\n[ERROR] Neo4j write failed: {e}")
                import traceback
                traceback.print_exc()
                sys.exit(1)
        else:
            print("\n[INFO] Neo4j URI not set; skipping Neo4j write (use --neo4j-uri or config)")

        # Pipeline 2 (optional): JSON only when --output or config.output is set
        if args.output:
            builder.save_graph(args.output)
            print(f"\nNext steps (JSON): python src/query_graph.py {args.output}")
        else:
            print("\n[INFO] No --output specified; JSON file not written")

        print("\n[SUCCESS] Dependency graph built successfully")
        if args.neo4j_uri:
            print("  Primary output: Neo4j")

    except Exception as e:
        print(f"\n[ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
