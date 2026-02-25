"""
SQL File Parser - Discovers SQL files and extracts basic metadata.

Content parsing (table references, DML operations) is intentionally skipped
in this version. Only file discovery and metadata (name, path, line count)
are extracted. Full SQL AST parsing can be added later.
"""

from pathlib import Path
from typing import Dict


class SQLParser:
    """Discovers *.sql files under a directory and returns per-file metadata."""

    def parse_file(self, sql_path: str) -> Dict:
        """
        Return basic metadata for a single SQL file.

        Returns dict with keys:
            program_name : str  – filename stem, uppercased
            file_path    : str  – absolute path
            line_count   : int
            error        : str  – only present on failure
        """
        sql_path = Path(sql_path)
        result = {
            'program_name': sql_path.stem.upper(),
            'file_path': str(sql_path),
            'line_count': 0,
        }
        if not sql_path.exists():
            result['error'] = f'File not found: {sql_path}'
            return result
        try:
            with open(sql_path, 'r', encoding='utf-8', errors='ignore') as f:
                result['line_count'] = sum(1 for _ in f)
        except Exception as exc:
            result['error'] = f'Error reading file: {exc}'
        return result

    def parse_directory(self, directory: str) -> Dict[str, Dict]:
        """
        Find all *.sql files under *directory* (recursive) and parse each.

        Returns dict: program_name (stem.upper()) -> parse_file() result.
        Files with errors are excluded.
        """
        directory = Path(directory)
        results: Dict[str, Dict] = {}
        if not directory.exists():
            print(f"Warning: Directory not found: {directory}")
            return results

        sql_files = list(directory.rglob('*.sql'))
        print(f"Found {len(sql_files)} SQL files in {directory}")

        for sql_file in sql_files:
            result = self.parse_file(str(sql_file))
            if 'error' not in result:
                results[result['program_name']] = result

        return results
