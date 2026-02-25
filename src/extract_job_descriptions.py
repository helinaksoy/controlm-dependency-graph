#!/usr/bin/env python3
"""
Extract job descriptions from Control-M XML export to CSV.

Output columns:
  folder, application, sub_application, job_name, memname, description,
  desc_program, ref_program, ref_datasets

  desc_program : program name left of '=' (main executing program)
  ref_program  : program name referenced in right side (after FOR/FUER)
  ref_datasets : pipe-separated dataset/table names found in description

Usage:
    python extract_job_descriptions.py
    python extract_job_descriptions.py --controlm path/to/export.xml --output output/job_descriptions.csv
"""

import argparse
import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

# Keywords whose immediately following token is a dataset/table name
_DATASET_KW = re.compile(
    r'\b(?:UNLOAD|LOAD|RELOAD|INSERT\s+INTO|DELETE\s+FROM|SELECT\s+FROM|UPDATE|INTO|OF|IN)\s+([A-Z][A-Z0-9_]{2,})\b',
    re.IGNORECASE
)

# Token in parentheses that looks like a table name  (e.g. "(TFWKURS)" or "(DGTURXXX)")
_PAREN_TOKEN = re.compile(r'\(([A-Z][A-Z0-9_]{3,})\)')

# Reference program: token after FOR or FUER that is a word with 5+ chars
_REF_PROG = re.compile(r'\bF(?:UE?|ÜE?)R\s+([A-Z][A-Z0-9]{4,})\b', re.IGNORECASE)

# Generic noise words that should never be mistaken for table/program names
_NOISE = {
    'DATASET', 'DATASETS', 'FROM', 'INTO', 'WITH', 'AND', 'THE', 'FOR',
    'FUER', 'NACH', 'VON', 'AUS', 'DER', 'DIE', 'DAS', 'ALL', 'ALLE',
    'TABLE', 'TABLES', 'FILE', 'FILES', 'QUERY', 'DATA', 'LIST',
    'OPERATIVE', 'PACKAGES', 'ONLINE', 'FULL', 'INBOUND', 'OUTBOUND',
    'SERVICE', 'MANAGEMENT', 'SYNCHRONIZATION', 'TURKEY',
    'DIRECTORY', 'APPLICATION', 'EXPERT', 'PREMIUM', 'JOURNALS',
    'COLLECTION', 'OPINION', 'WORKAREA', 'CREDIT', 'EXCHANGE',
    'BLOBS', 'RATES', 'CHANGES', 'ENTRIES', 'TASKS', 'RESULTS',
    'PACKAGES', 'RECORDS', 'CONTRACTS', 'MEMBERS', 'BACKUP',
    'RUNSTATS', 'STATISTICS', 'INVENTORY', 'REMAINDER', 'JOBCHAIN',
    'TIMESETTING', 'BATCHPROT', 'SECTRANS', 'START', 'ENDE',
}


def load_config():
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def extract_desc_program(description: str) -> str:
    """Token left of '=' — the main executing program."""
    if not description:
        return ""
    if "=" in description:
        candidate = description.split("=")[0].strip()
        if candidate and " " not in candidate:
            return candidate
    return ""


def extract_ref_program(description: str, desc_program: str) -> str:
    """
    Token after FOR/FUER on the right side of '='.
    Skips if it equals desc_program (self-reference).
    """
    right = description.split("=", 1)[1] if "=" in description else description
    m = _REF_PROG.search(right)
    if m:
        token = m.group(1).upper()
        if token not in _NOISE and token != desc_program.upper():
            return token
    return ""


def extract_ref_datasets(description: str) -> str:
    """
    Extract dataset/table names from the description right side.
    Returns pipe-separated string, e.g. 'GGBUEPA|TFWKURS'
    """
    right = description.split("=", 1)[1] if "=" in description else description
    found = set()

    # After DB2 keywords
    for m in _DATASET_KW.finditer(right):
        token = m.group(1).upper()
        if token not in _NOISE:
            found.add(token)

    # In parentheses
    for m in _PAREN_TOKEN.finditer(right):
        token = m.group(1).upper()
        if token not in _NOISE:
            found.add(token)

    # "IN TXXXXXX" pattern (table names starting with T + 5+ chars)
    for m in re.finditer(r'\bIN\s+(T[A-Z0-9]{4,})\b', right, re.IGNORECASE):
        token = m.group(1).upper()
        if token not in _NOISE:
            found.add(token)

    return "|".join(sorted(found))


def parse_controlm_xml(xml_path: str) -> list:
    """Parse Control-M XML and extract job info."""
    print(f"Parsing: {xml_path}")
    tree = ET.parse(xml_path)
    root = tree.getroot()

    rows = []
    for folder in root.findall("FOLDER"):
        folder_name = folder.get("FOLDER_NAME", "")
        for job in folder.findall("JOB"):
            description = job.get("DESCRIPTION", "")
            desc_program = extract_desc_program(description)
            rows.append({
                "folder":          folder_name,
                "application":     job.get("APPLICATION", ""),
                "sub_application": job.get("SUB_APPLICATION", ""),
                "job_name":        job.get("JOBNAME", ""),
                "memname":         job.get("MEMNAME", ""),
                "description":     description,
                "desc_program":    desc_program,
                "ref_program":     extract_ref_program(description, desc_program),
                "ref_datasets":    extract_ref_datasets(description),
            })

    print(f"  Found {len(rows)} jobs across {len(root.findall('FOLDER'))} folders.")
    return rows


def write_csv(rows: list, output_path: str):
    """Write rows to CSV file."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "folder", "application", "sub_application", "job_name", "memname",
        "description", "desc_program", "ref_program", "ref_datasets"
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved: {output_path}  ({len(rows)} rows)")


def main():
    cfg = load_config()

    parser = argparse.ArgumentParser(description="Extract job descriptions from Control-M XML to CSV")
    parser.add_argument(
        "--controlm",
        default=cfg.get("controlm_xml", r"C:\AVC\Workspace\GlobalControlMExport_PROD.xml"),
        help="Path to Control-M XML export file"
    )
    parser.add_argument(
        "--output",
        default="output/job_descriptions.csv",
        help="Output CSV file path (default: output/job_descriptions.csv)"
    )
    args = parser.parse_args()

    # Resolve relative paths from project root (parent of src/)
    project_root = Path(__file__).resolve().parent.parent
    xml_path = Path(args.controlm)
    if not xml_path.is_absolute():
        xml_path = project_root / xml_path

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = project_root / output_path

    if not xml_path.exists():
        print(f"ERROR: XML file not found: {xml_path}", file=sys.stderr)
        sys.exit(1)

    rows = parse_controlm_xml(str(xml_path))
    write_csv(rows, str(output_path))

    # Quick summary
    with_program  = [r for r in rows if r["desc_program"] and r["desc_program"].upper() not in ("DUMMY", "")]
    with_ref_prog = [r for r in rows if r["ref_program"]]
    with_datasets = [r for r in rows if r["ref_datasets"]]
    print(f"\nSummary:")
    print(f"  Total jobs         : {len(rows)}")
    print(f"  With desc_program  : {len(with_program)}")
    print(f"  With ref_program   : {len(with_ref_prog)}")
    print(f"  With ref_datasets  : {len(with_datasets)}")


if __name__ == "__main__":
    main()
