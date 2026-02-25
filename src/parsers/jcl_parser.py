"""
JCL Parser - Extracts program dependencies from JCL files
 
Supports:
- EXEC PGM=PROGRAMNAME
- RUN PROGRAM(PROGRAMNAME)
- CALL 'PROGRAMNAME'
- PROC calls
- DD statement extraction
"""
 
import re
from pathlib import Path
from typing import Dict, List, Set
 
 
class JCLParser:
    """Parser for JCL (Job Control Language) files"""
   
    def __init__(self):
        # Pattern to match EXEC PGM statements
        # Example: //STEP1 EXEC PGM=ADAQOSL
        self.exec_pgm_pattern = re.compile(
            r'//\w+\s+EXEC\s+PGM=(\w+)',
            re.IGNORECASE
        )
       
        # Pattern to match RUN PROGRAM statements
        # Example: RUN PROGRAM(ADAQOSL)
        self.run_program_pattern = re.compile(
            r'RUN\s+PROGRAM\((\w+)\)',
            re.IGNORECASE
        )
       
        # Pattern to match CALL statements
        # Example: CALL 'PROGRAM' or CALL PROGRAM
        self.call_pattern = re.compile(
            r'CALL\s+[\'"]?(\w+)[\'"]?',
            re.IGNORECASE
        )
       
        # Pattern to match DD statements (dataset definitions)
        # Example: //EKAVL DD *
        self.dd_pattern = re.compile(
            r'//(\w+)\s+DD\s+',
            re.IGNORECASE
        )
       
        # Pattern to match EXEC PROC statements
        # Example: //STEP EXEC PROCNAME
        self.exec_proc_pattern = re.compile(
            r'//\w+\s+EXEC\s+(?!PGM=)(\w+)',
            re.IGNORECASE
        )
       
        # Pattern to match step names
        self.step_pattern = re.compile(
            r'//(\w+)\s+EXEC\s+',
            re.IGNORECASE
        )
       
        # System programs to filter out
        self.system_programs = {
            'IEFBR14', 'IDCAMS', 'IEBGENER', 'SORT', 'DSNTEP2',
            'DSNTIAD', 'IKJEFT01', 'IEBCOPY', 'IEBUPDTE'
        }
       
        # System DD names to filter out
        self.system_dd_names = {
            'STEPLIB', 'SYSPRINT', 'SYSOUT', 'SYSIN', 'SYSTSPRT',
            'SYSUDUMP', 'SYSTSIN', 'SYSABEND'
        }
   
    def parse_file(self, jcl_path: str) -> Dict:
        """
        Parse a JCL file and extract program dependencies.
       
        Args:
            jcl_path: Path to the JCL file
           
        Returns:
            Dictionary containing:
            - jcl_name: Name of the JCL file (without extension)
            - file_path: Full path to the file
            - programs_called: List of programs executed
            - procs_called: List of procedures called
            - datasets: List of dataset names (DD names)
            - steps: List of step names
            - line_count: Number of lines
            - error: Error message if file couldn't be parsed
        """
        jcl_path = Path(jcl_path)
       
        if not jcl_path.exists():
            return {
                'jcl_name': jcl_path.stem,
                'error': f'File not found: {jcl_path}',
                'programs_called': [],
                'procs_called': [],
                'datasets': [],
                'steps': []
            }
       
        try:
            with open(jcl_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            return {
                'jcl_name': jcl_path.stem,
                'error': f'Error reading file: {str(e)}',
                'programs_called': [],
                'procs_called': [],
                'datasets': [],
                'steps': []
            }
       
        programs = self._extract_programs(content)
        procs = self._extract_procs(content)
        datasets = self._extract_datasets(content)
        steps = self._extract_steps(content)
       
        return {
            'jcl_name': jcl_path.stem.upper(),
            'file_path': str(jcl_path),
            'programs_called': sorted(list(programs)),
            'procs_called': sorted(list(procs)),
            'datasets': sorted(list(datasets)),
            'steps': sorted(list(steps)),
            'line_count': len(content.splitlines())
        }
   
    def _extract_programs(self, content: str) -> Set[str]:
        """Extract all program names from JCL content"""
        programs = set()
       
        # Find EXEC PGM= statements
        exec_pgm_matches = self.exec_pgm_pattern.findall(content)
        programs.update(exec_pgm_matches)
       
        # Find RUN PROGRAM statements
        run_program_matches = self.run_program_pattern.findall(content)
        programs.update(run_program_matches)
       
        # Find CALL statements
        call_matches = self.call_pattern.findall(content)
        programs.update(call_matches)
       
        # Convert to uppercase and filter system programs
        programs = {prog.upper() for prog in programs}
        programs = programs - self.system_programs
       
        return programs
   
    def _extract_procs(self, content: str) -> Set[str]:
        """Extract procedure names called by EXEC statements"""
        procs = set()
       
        lines = content.splitlines()
        for line in lines:
            # Skip comment lines
            if line.strip().startswith('//*'):
                continue
               
            # Check if it's an EXEC statement but not EXEC PGM=
            if re.search(r'//\w+\s+EXEC\s+', line, re.IGNORECASE):
                if 'PGM=' not in line.upper():
                    match = self.exec_proc_pattern.search(line)
                    if match:
                        proc_name = match.group(1).upper()
                        # Filter out obvious step names or system utilities
                        if not proc_name.startswith('STEP'):
                            procs.add(proc_name)
       
        return procs
   
    def _extract_datasets(self, content: str) -> Set[str]:
        """Extract dataset names from DD statements"""
        datasets = set()
       
        lines = content.splitlines()
        for line in lines:
            # Skip comment lines
            if line.strip().startswith('//*'):
                continue
               
            match = self.dd_pattern.match(line)
            if match:
                dd_name = match.group(1).upper()
                # Skip common system DD names
                if dd_name not in self.system_dd_names:
                    datasets.add(dd_name)
       
        return datasets
   
    def _extract_steps(self, content: str) -> Set[str]:
        """Extract step names from EXEC statements"""
        steps = set()
       
        lines = content.splitlines()
        for line in lines:
            # Skip comment lines
            if line.strip().startswith('//*'):
                continue
               
            match = self.step_pattern.match(line)
            if match:
                step_name = match.group(1).upper()
                steps.add(step_name)
       
        return steps
   
    def parse_directory(self, directory: str) -> Dict[str, Dict]:
        """
        Parse all JCL files in a directory.
       
        Args:
            directory: Path to directory containing JCL files
           
        Returns:
            Dictionary mapping JCL names to their parsed content
        """
        directory = Path(directory)
        results = {}
       
        if not directory.exists():
            print(f"Warning: Directory not found: {directory}")
            return results
       
        # Find all .jcl files recursively
        jcl_files = list(directory.rglob('*.jcl'))
        print(f"Found {len(jcl_files)} JCL files in {directory}")
       
        for jcl_file in jcl_files:
            result = self.parse_file(str(jcl_file))
            results[result['jcl_name']] = result
       
        return results
   
    def get_summary(self, parsed_results: Dict[str, Dict]) -> Dict:
        """
        Generate a summary of parsed JCL files.
       
        Args:
            parsed_results: Dictionary of parsed JCL files
           
        Returns:
            Summary statistics
        """
        total_jcls = len(parsed_results)
        total_programs = set()
        total_procs = set()
        errors = []
       
        for jcl_name, result in parsed_results.items():
            if 'error' in result:
                errors.append({'jcl': jcl_name, 'error': result['error']})
            else:
                total_programs.update(result['programs_called'])
                total_procs.update(result['procs_called'])
       
        return {
            'total_jcls': total_jcls,
            'total_programs': len(total_programs),
            'total_procs': len(total_procs),
            'unique_programs': sorted(list(total_programs)),
            'unique_procs': sorted(list(total_procs)),
            'errors': errors
        }
 