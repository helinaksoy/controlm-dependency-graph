"""
Control-M XML Parser - Extracts job dependencies from Control-M XML exports
 
Enhanced version with:
- MEMNAME and MEMLIB extraction
- Folder hierarchy support
- Application/Sub-Application grouping
"""
 
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Dict, List, Set
from pathlib import Path
 
 
class ControlMParser:
    """Parser for Control-M XML export files"""
   
    def __init__(self):
        self.jobs = {}  # jobname -> job info
        self.folders = {}  # folder_name -> folder info
        self.applications = defaultdict(set)  # application -> set of jobs
        self.sub_applications = defaultdict(set)  # sub_application -> set of jobs
        self.inconds = defaultdict(list)  # condition_name -> [jobs waiting for it]
        self.outconds = defaultdict(list)  # condition_name -> [jobs setting it]
        self.dependencies = defaultdict(set)  # job -> set of jobs it depends on
        self.dependents = defaultdict(set)  # job -> set of jobs depending on it
       
    def parse_file(self, xml_file: str) -> Dict:
        """
        Parse a Control-M XML export file.
       
        Args:
            xml_file: Path to the Control-M XML file
           
        Returns:
            Dictionary with parsed data structure
        """
        xml_file = Path(xml_file)
       
        if not xml_file.exists():
            return {
                'error': f'File not found: {xml_file}',
                'jobs': {},
                'folders': {},
                'dependencies': {}
            }
       
        try:
            print(f"Parsing {xml_file}...")
            tree = ET.parse(str(xml_file))
            root = tree.getroot()
           
            # Parse folders
            self._parse_folders(root)
           
            # Parse jobs
            self._parse_jobs(root)
           
            # Build dependency graph
            self._build_dependency_graph()
           
            print(f"[OK] Parsed {len(self.folders)} folders, {len(self.jobs)} jobs")
           
            return self._get_results()
           
        except Exception as e:
            return {
                'error': f'Error parsing XML: {str(e)}',
                'jobs': {},
                'folders': {},
                'dependencies': {}
            }
   
    def _parse_folders(self, root):
        """Parse all FOLDER elements"""
        for folder in root.findall('.//FOLDER'):
            folder_name = folder.get('FOLDER_NAME')
            self.folders[folder_name] = {
                'name': folder_name,
                'datacenter': folder.get('DATACENTER', ''),
                'platform': folder.get('PLATFORM', ''),
                'real_folder_id': folder.get('REAL_FOLDER_ID', ''),
                'jobs': []
            }
   
    def _parse_jobs(self, root):
        """Parse all JOB elements"""
        for job in root.findall('.//JOB'):
            jobname = job.get('JOBNAME')
            parent_folder = job.get('PARENT_FOLDER')
            application = job.get('APPLICATION', '')
            sub_application = job.get('SUB_APPLICATION', '')
           
            job_info = {
                'jobname': jobname,
                'application': application,
                'sub_application': sub_application,
                'description': job.get('DESCRIPTION', ''),
                'folder': parent_folder,
                'memname': job.get('MEMNAME', ''),
                'memlib': job.get('MEMLIB', ''),
                'tasktype': job.get('TASKTYPE', ''),
                'cmdline': job.get('CMDLINE', ''),
                'run_as': job.get('RUN_AS', ''),
                'nodeid': job.get('NODEID', ''),
                'inconds': [],
                'outconds': []
            }
           
            # Collect input conditions
            for incond in job.findall('INCOND'):
                cond_name = incond.get('NAME')
                job_info['inconds'].append({
                    'name': cond_name,
                    'odate': incond.get('ODATE', 'ODAT'),
                    'and_or': incond.get('AND_OR', 'A')
                })
                self.inconds[cond_name].append(jobname)
           
            # Collect output conditions
            for outcond in job.findall('OUTCOND'):
                cond_name = outcond.get('NAME')
                job_info['outconds'].append({
                    'name': cond_name,
                    'odate': outcond.get('ODATE', 'STAT'),
                    'sign': outcond.get('SIGN', '+')
                })
                self.outconds[cond_name].append(jobname)
           
            self.jobs[jobname] = job_info
           
            # Update folder
            if parent_folder and parent_folder in self.folders:
                self.folders[parent_folder]['jobs'].append(jobname)
           
            # Update application/sub-application tracking
            if application:
                self.applications[application].add(jobname)
            if sub_application:
                self.sub_applications[sub_application].add(jobname)
   
    def _build_dependency_graph(self):
        """Build the dependency graph from INCOND/OUTCOND"""
        for jobname, job_info in self.jobs.items():
            # For each input condition this job waits for
            for incond in job_info['inconds']:
                cond_name = incond['name']
                # Find all jobs that set this condition
                if cond_name in self.outconds:
                    for provider_job in self.outconds[cond_name]:
                        # jobname depends on provider_job
                        self.dependencies[jobname].add(provider_job)
                        self.dependents[provider_job].add(jobname)
   
    def _get_results(self) -> Dict:
        """Format results for export"""
        return {
            'folders': self.folders,
            'applications': {app: list(jobs) for app, jobs in self.applications.items()},
            'sub_applications': {subapp: list(jobs) for subapp, jobs in self.sub_applications.items()},
            'jobs': self.jobs,
            'dependencies': {job: list(deps) for job, deps in self.dependencies.items()},
            'dependents': {job: list(deps) for job, deps in self.dependents.items()},
            'conditions': {
                'inputs': {cond: list(jobs) for cond, jobs in self.inconds.items()},
                'outputs': {cond: list(jobs) for cond, jobs in self.outconds.items()}
            },
            'statistics': self._get_statistics()
        }
   
    def _get_statistics(self) -> Dict:
        """Calculate statistics"""
        deps_count = sum(len(deps) for deps in self.dependencies.values())
       
        return {
            'total_folders': len(self.folders),
            'total_jobs': len(self.jobs),
            'total_applications': len(self.applications),
            'total_sub_applications': len(self.sub_applications),
            'total_input_conditions': len(self.inconds),
            'total_output_conditions': len(self.outconds),
            'total_dependencies': deps_count,
            'root_jobs_count': len([j for j in self.jobs if not self.dependencies.get(j)]),
            'leaf_jobs_count': len([j for j in self.jobs if not self.dependents.get(j)]),
            'jobs_with_memname': len([j for j in self.jobs.values() if j['memname']])
        }
   
    def get_jobs_with_jcl(self) -> Dict[str, Dict]:
        """Get all jobs that have a MEMNAME (JCL file reference)"""
        jobs_with_jcl = {}
       
        for jobname, job_info in self.jobs.items():
            if job_info['memname']:
                jobs_with_jcl[jobname] = {
                    'memname': job_info['memname'],
                    'memlib': job_info['memlib'],
                    'application': job_info['application'],
                    'sub_application': job_info['sub_application']
                }
       
        return jobs_with_jcl
   
    def get_hierarchy(self) -> Dict:
        """
        Get the organizational hierarchy: Folder → Application → Sub-Application → Jobs
        """
        hierarchy = {}
       
        for folder_name, folder_info in self.folders.items():
            apps_in_folder = defaultdict(lambda: defaultdict(list))
           
            for jobname in folder_info['jobs']:
                job = self.jobs.get(jobname)
                if job:
                    app = job.get('application', 'UNKNOWN')
                    subapp = job.get('sub_application', 'UNKNOWN')
                    apps_in_folder[app][subapp].append(jobname)
           
            hierarchy[folder_name] = {
                'datacenter': folder_info['datacenter'],
                'platform': folder_info['platform'],
                'applications': dict(apps_in_folder)
            }
       
        return hierarchy