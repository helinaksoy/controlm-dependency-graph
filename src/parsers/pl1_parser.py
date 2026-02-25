"""
PL/I Parser - Extracts dependencies from PL/I source files
 
Supports:
- CALL statements (external program calls)
- %INCLUDE directives (include files)
- EXEC SQL (database table operations)
- #PROC definitions (internal procedures)
- DCL ENTRY (external entry declarations)
"""
 
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple
from collections import defaultdict
 
 
class PL1Parser:
    """Parser for PL/I (Programming Language One) source files"""
   
    def __init__(self):
        # Pattern to match CALL statements
        # Example: CALL PROGNAME(...), CALL PROGNAME;
        self.call_pattern = re.compile(
            r'CALL\s+(\w+)\s*[\(;]',
            re.IGNORECASE
        )
       
        # Pattern to match %INCLUDE directives
        # Example: %INCLUDE FILENAME;
        self.include_pattern = re.compile(
            r'%INCLUDE\s+(\w+)',
            re.IGNORECASE
        )
       
        # Pattern to match #PROC definitions
        # Example: #PROC(PROCNAME) OPTIONS(MAIN);
        self.proc_pattern = re.compile(
            r'#PROC\((\w+)\)',
            re.IGNORECASE
        )
       
        # Pattern to match main procedure
        # Example: #PROC(ADAQOSL) OPTIONS(MAIN)
        self.main_proc_pattern = re.compile(
            r'#PROC\((\w+)\)\s+OPTIONS\(MAIN\)',
            re.IGNORECASE
        )
       
        # SQL table operation patterns
        self.sql_patterns = {
            'SELECT': re.compile(r'FROM\s+(\w+)', re.IGNORECASE),
            'UPDATE': re.compile(r'UPDATE\s+(\w+)', re.IGNORECASE),
            'INSERT': re.compile(r'INSERT\s+INTO\s+(\w+)', re.IGNORECASE),
            'DELETE': re.compile(r'DELETE\s+FROM\s+(\w+)', re.IGNORECASE),
        }
       
        # Pattern to detect EXEC SQL blocks
        self.exec_sql_start = re.compile(r'EXEC\s+SQL', re.IGNORECASE)
       
        # Pattern to match DCL ENTRY statements
        # Example: DCL PROGNAME ENTRY;
        self.entry_pattern = re.compile(
            r'DCL\s+(\w+)\s+ENTRY',
            re.IGNORECASE
        )
       
    def parse_file(self, pl1_path: str) -> Dict:
        """
        Parse a PL/I file and extract all dependencies.
       
        Args:
            pl1_path: Path to the PL/I file
           
        Returns:
            Dictionary containing:
            - program_name: Name of the main program
            - file_path: Full path to the file
            - procedures: List of internal procedures defined
            - calls: List of external programs called
            - includes: List of included files
            - sql_tables: List of SQL tables accessed
            - sql_operations: Dict mapping tables to operations
            - entries: List of declared external entries
            - line_count: Number of lines
            - error: Error message if parsing failed
        """
        pl1_path = Path(pl1_path)
       
        if not pl1_path.exists():
            return {
                'program_name': pl1_path.stem.upper(),
                'error': f'File not found: {pl1_path}',
                'procedures': [],
                'calls': [],
                'includes': [],
                'sql_tables': [],
                'sql_operations': {},
                'entries': []
            }
       
        try:
            with open(pl1_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            return {
                'program_name': pl1_path.stem.upper(),
                'error': f'Error reading file: {str(e)}',
                'procedures': [],
                'calls': [],
                'includes': [],
                'sql_tables': [],
                'sql_operations': {},
                'entries': []
            }
       
        # Extract all components
        program_name = self._extract_program_name(content, pl1_path.stem)
        procedures = self._extract_procedures(content)
        calls = self._extract_calls(content)
        includes = self._extract_includes(content)
        sql_tables, sql_operations = self._extract_sql_dependencies(content)
        entries = self._extract_entries(content)
       
        return {
            'program_name': program_name,
            'file_path': str(pl1_path),
            'procedures': sorted(list(procedures)),
            'calls': sorted(list(calls)),
            'includes': sorted(list(includes)),
            'sql_tables': sorted(list(sql_tables)),
            'sql_operations': {table: sorted(ops) for table, ops in sql_operations.items()},
            'entries': sorted(list(entries)),
            'line_count': len(content.splitlines())
        }
   
    def _extract_program_name(self, content: str, default_name: str) -> str:
        """Extract program name from main PROC definition"""
        match = self.main_proc_pattern.search(content)
       
        if match:
            return match.group(1).upper()
       
        # If no main proc found, use filename
        return default_name.upper()
   
    def _extract_procedures(self, content: str) -> Set[str]:
        """Extract all procedure definitions (#PROC)"""
        procedures = set()
       
        matches = self.proc_pattern.findall(content)
        for proc_name in matches:
            procedures.add(proc_name.upper())
       
        return procedures
   
    def _extract_calls(self, content: str) -> Set[str]:
        """Extract all CALL statements"""
        calls = set()
       
        # Remove comments to avoid false positives
        content_no_comments = self._remove_comments(content)
       
        matches = self.call_pattern.findall(content_no_comments)
        for call_name in matches:
            calls.add(call_name.upper())
       
        return calls
   
    def _extract_includes(self, content: str) -> Set[str]:
        """Extract all %INCLUDE directives"""
        includes = set()
       
        matches = self.include_pattern.findall(content)
        for include_name in matches:
            includes.add(include_name.upper())
       
        return includes
   
    def _extract_sql_dependencies(self, content: str) -> Tuple[Set[str], Dict[str, Set[str]]]:
        """
        Extract SQL table dependencies and operations.
       
        Handles multi-line SQL statements like:
        EXEC SQL DECLARE CURSOR FOR
            SELECT ...
            FROM TABLE1
            WHERE ...;
       
        Returns:
            Tuple of (set of table names, dict mapping tables to operations)
        """
        tables = set()
        operations = defaultdict(set)
       
        # Find EXEC SQL blocks
        lines = content.splitlines()
        in_sql_block = False
        sql_statement = []
       
        for line in lines:
            # Skip comment lines
            stripped = line.strip()
            if stripped.startswith('/*') or stripped.startswith('*'):
                continue
           
            # Check if entering SQL block
            if self.exec_sql_start.search(line):
                in_sql_block = True
                sql_statement = [line]
                continue
           
            # Collect SQL statement lines
            if in_sql_block:
                sql_statement.append(line)
               
                # Check if statement ends (semicolon)
                if ';' in line:
                    full_statement = ' '.join(sql_statement)
                   
                    # Extract tables for each operation type
                    for operation, pattern in self.sql_patterns.items():
                        matches = pattern.findall(full_statement)
                        for table_name in matches:
                            if table_name:  # Ensure not empty
                                table_upper = table_name.upper()
                                tables.add(table_upper)
                                operations[table_upper].add(operation)
                   
                    in_sql_block = False
                    sql_statement = []
       
        return tables, dict(operations)
   
    def _extract_entries(self, content: str) -> Set[str]:
        """Extract external entry declarations (DCL ... ENTRY)"""
        entries = set()
       
        matches = self.entry_pattern.findall(content)
        for entry_name in matches:
            entries.add(entry_name.upper())
       
        return entries
   
    def _remove_comments(self, content: str) -> str:
        """Remove PL/I comments from content"""
        # Remove /* ... */ style comments
        # Use non-greedy matching to avoid removing too much
        content = re.sub(r'/\*.*?\*/', ' ', content, flags=re.DOTALL)
        return content
   
    def parse_directory(self, directory: str) -> Dict[str, Dict]:
        """
        Parse all PL/I files in a directory.
       
        Args:
            directory: Path to directory containing PL/I files
           
        Returns:
            Dictionary mapping program names to their parsed content
        """
        directory = Path(directory)
        results = {}
       
        if not directory.exists():
            print(f"Warning: Directory not found: {directory}")
            return results
       
        # Find all .pl1 and .pli files
        pl1_files = list(directory.rglob('*.pl1')) + list(directory.rglob('*.pli'))
        print(f"Found {len(pl1_files)} PL/I files in {directory}")
       
        for pl1_file in pl1_files:
            result = self.parse_file(str(pl1_file))
            results[result['program_name']] = result
       
        return results
   
    def get_summary(self, parsed_results: Dict[str, Dict]) -> Dict:
        """
        Generate a summary of parsed PL/I files.
       
        Args:
            parsed_results: Dictionary of parsed PL/I files
           
        Returns:
            Summary statistics
        """
        total_programs = len(parsed_results)
        total_procedures = 0
        total_calls = set()
        total_includes = set()
        total_tables = set()
        errors = []
       
        for prog_name, result in parsed_results.items():
            if 'error' in result:
                errors.append({'program': prog_name, 'error': result['error']})
            else:
                total_procedures += len(result.get('procedures', []))
                total_calls.update(result.get('calls', []))
                total_includes.update(result.get('includes', []))
                total_tables.update(result.get('sql_tables', []))
       
        return {
            'total_programs': total_programs,
            'total_procedures': total_procedures,
            'total_calls': len(total_calls),
            'total_includes': len(total_includes),
            'total_tables': len(total_tables),
            'unique_calls': sorted(list(total_calls)),
            'unique_includes': sorted(list(total_includes)),
            'unique_tables': sorted(list(total_tables)),
            'errors': errors
        }
   
    def get_call_graph(self, parsed_results: Dict[str, Dict]) -> Dict[str, List[str]]:
        """
        Build a call graph from parsed results.
       
        Args:
            parsed_results: Dictionary of parsed PL/I files
           
        Returns:
            Dictionary mapping programs to list of programs they call
        """
        call_graph = {}
       
        for prog_name, result in parsed_results.items():
            if 'error' not in result:
                call_graph[prog_name] = result.get('calls', [])
       
        return call_graph
   
    def get_include_graph(self, parsed_results: Dict[str, Dict]) -> Dict[str, List[str]]:
        """
        Build an include dependency graph.
       
        Args:
            parsed_results: Dictionary of parsed PL/I files
           
        Returns:
            Dictionary mapping programs to list of files they include
        """
        include_graph = {}
       
        for prog_name, result in parsed_results.items():
            if 'error' not in result:
                include_graph[prog_name] = result.get('includes', [])
       
        return include_graph