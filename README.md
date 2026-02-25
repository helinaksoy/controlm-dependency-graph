# Legacy Code Modernization - Dependency Graph Builder
 
Multi-level dependency graph builder for Control-M, JCL, and PL/I legacy systems.
 
## Features
 
- **Control-M XML Parsing** - Extract job definitions, dependencies (INCOND/OUTCOND), and hierarchy
- **JCL File Analysis** - Parse EXEC PGM, RUN PROGRAM, CALL statements, and dataset references
- **PL/I Program Dependency Extraction** - Analyze CALL statements, %INCLUDE directives, and #PROC definitions
- **Database Table Tracking** - Extract SQL operations (SELECT, INSERT, UPDATE, DELETE) and table access patterns
- **Multi-level Dependency Graph Generation** - Build unified graph across all layers (Job → JCL → PL/I → Database)
- **Interactive Query Tool** - Search, traverse, and analyze dependencies with powerful query interface
- **🌟 NEW: Interactive Web Viewer** - Modern web-based graph visualization with lazy loading and hierarchical navigation
 
## Quick Start
 
### 1. Build Dependency Graph
 
```bash
# Build dependency graph with a single directory containing both JCL and PL/I files
python src/build_dependency_graph.py \
    --controlm data/GlobalControlMExport_PROD.xml \
    --code-dir /path/to/local/repo \
    --output output/dependency_graph.json
```
 
### 2. Query via CLI
 
```bash
# Query the graph
python src/query_graph.py output/dependency_graph.json \
    --program ADAQOSL --deps --dependents
```
 
### 3. Interactive Web Viewer (Recommended)
 
```bash
# Start backend (Terminal 1)
cd webapp/backend
pip install -r requirements.txt
python main.py
 
# Start frontend (Terminal 2)
cd webapp/frontend
python -m http.server 8080
 
# Open browser: http://localhost:8080
```
 
See [webapp/README.md](webapp/README.md) for detailed web viewer documentation.
 
## Requirements
 
- Python 3.7+
- No external dependencies (uses Python standard library only)
 
## System Architecture
 
```
Control-M Job (XML)
    ↓ executes (MEMNAME)
JCL File
    ↓ calls (EXEC PGM, RUN PROGRAM)
PL/I Program
    ├→ calls (CALL) → Other PL/I Programs
    ├→ includes (%INCLUDE) → Copy Members
    └→ accesses (EXEC SQL) → Database Tables
```
 
## Configuration
 
### Option A: Auto-discovery (recommended)
 
Use `--code-dir` to point to the directory (or local repo clone) containing your JCL and PL/I files. The tool will automatically scan for `*.jcl`, `*.pl1`, and `*.pli` files recursively — no manual mapping needed.
 
```bash
python src/build_dependency_graph.py \
    --controlm data/GlobalControlMExport_PROD.xml \
    --code-dir /path/to/local/repo \
    --output output/dependency_graph.json
```
 
If your JCL and PL/I files live in separate directories, use `--jcl-dir` and `--pl1-dir` instead.
 
### Option B: Manual mapping
 
1. **path_mappings.json** - Map Control-M MEMNAME to JCL file paths
2. **program_mappings.json** - Map program names to PL/I source files
 
See [src/config/README.md](src/config/README.md) for details.
 
## Output Format
 
The system generates a JSON dependency graph with:
- **Nodes**: Jobs, JCL files, PL/I programs, DB tables, include files
- **Edges**: Dependencies with type and metadata
- **Metadata**: Statistics, missing references, hierarchies
 
## Example Results
 
Successfully tested with:
- 10,026 Control-M jobs
- 13,756 job dependencies
- Multi-level program call chains
- SQL table access patterns
 
 
## Project Structure
 
```
legacy-code-modernization/
├── src/
│   ├── parsers/          # JCL, PL/I, Control-M parsers
│   ├── config/           # Configuration templates
│   ├── graph_builder.py  # Main orchestrator
│   ├── build_dependency_graph.py  # CLI tool
│   └── query_graph.py    # Query interface
├── webapp/               # 🌟 NEW: Interactive web viewer
│   ├── backend/          # FastAPI REST API
│   └── frontend/         # Vanilla JS + Cytoscape.js
├── output/               # Generated graphs
└── README.md             # This file
```
 
## License
 
DefineX - Internal Tool
 
## Author
 
Developed for DefineX legacy code modernization initiative.
 