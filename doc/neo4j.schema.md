# Neo4j Graph Schema
 
Legacy Code Modernization - Dependency Graph Database Schema
 
## Graph Model Overview
 
```
Application -[:CONTAINS]-> SubApplication -[:CONTAINS]-> Folder -[:CONTAINS]-> Job
Job -[:PRODUCES]-> Condition <-[:REQUIRES]- Job
Job -[:EXECUTES]-> PL1Program
PL1Program -[:CALLS]-> PL1Program
PL1Program -[:INCLUDES]-> IncludeFile
PL1Program -[:DB_ACCESS]-> DBTable
```

> **Note:** JCL layer has been removed. Jobs now link **directly** to PL/I programs
> via the `DESCRIPTION` field pattern `PROGNAME = ...` matched against source files in `code_dir`.
## Node Labels & Properties
 
Every node carries the base label `:Node` plus a type-specific label.
 
### :Node:Folder
 
Control-M folder (top-level organizational unit).
 
| Property     | Type   | Key? | Description                                 |
|-------------|--------|------|---------------------------------------------|
| id          | String | PK   | `FOLDER::<folder_name>`                     |
| type        | String |      | `"folder"`                                  |
| name        | String |      | Folder name (= `FOLDER_NAME` in XML)        |
| datacenter  | String |      | Datacenter the folder belongs to             |
| platform    | String |      | Platform (e.g. UNIX, Windows)                |
 
### :Node:Application
 
Control-M application grouping.
 
| Property | Type   | Key? | Description                     |
|---------|--------|------|---------------------------------|
| id      | String | PK   | `APP::<application_name>`       |
| type    | String |      | `"application"`                 |
| name    | String |      | Application name (= `APPLICATION` in XML) |
 
### :Node:SubApplication
 
Control-M sub-application grouping.
 
| Property | Type   | Key? | Description                         |
|---------|--------|------|-------------------------------------|
| id      | String | PK   | `SUBAPP::<sub_application_name>`    |
| type    | String |      | `"sub_application"`                 |
| name    | String |      | Sub-application name (= `SUB_APPLICATION` in XML) |
 
### :Node:ControlMJob
 
A scheduled job/task in Control-M.
 
| Property        | Type   | Key? | Description                                      |
|----------------|--------|------|--------------------------------------------------|
| id             | String | PK   | `CONTROLM::<jobname>`                            |
| type           | String |      | `"controlm_job"`                                 |
| name           | String |      | Job name (= `JOBNAME` in XML)                    |
| folder         | String |      | Parent folder name (backward compat property)     |
| application    | String |      | Application name (backward compat property)       |
| sub_application| String |      | Sub-application name (backward compat property)   |
| memname        | String |      | JCL member name (= `MEMNAME` in XML)             |
| memlib         | String |      | JCL member library                                |
| tasktype       | String |      | Task type (e.g. Job, Command, Dummy)              |
| description    | String |      | Job description                                   |
 
### :Node:Condition
 
Control-M scheduling condition (INCOND/OUTCOND). Producer/consumer job names are stored so condition names (e.g. `AZT-TR3DB1G-OK`) are explicitly matched to job names (e.g. `TR3DB1G`) without string rules.
 
| Property        | Type     | Key? | Description                                              |
|----------------|----------|------|----------------------------------------------------------|
| id             | String   | PK   | `COND::<condition_name>`                                |
| type           | String   |      | `"condition"`                                            |
| name           | String   |      | Condition name as in XML (e.g. `AZT-TR3DB1G-OK`)         |
| producer_jobs  | String[] |      | Job names that set this condition (OUTCOND)             |
| consuming_jobs | String[] |      | Job names that wait for this condition (INCOND)          |
 
### :Node:JCL
 
JCL (Job Control Language) file.
 
| Property        | Type     | Key? | Description                      |
|----------------|----------|------|----------------------------------|
| id             | String   | PK   | `JCL::<jcl_name>`               |
| type           | String   |      | `"jcl"`                         |
| name           | String   |      | JCL file name                    |
| file_path      | String   |      | Source file path                  |
| programs_called| String[] |      | Programs referenced in JCL       |
| procs_called   | String[] |      | Procedures referenced in JCL     |
| datasets       | String[] |      | Datasets referenced              |
| steps          | String   |      | JCL steps (JSON-encoded)         |
 
### :Node:PL1Program
 
PL/I source program.
 
| Property       | Type     | Key? | Description                        |
|---------------|----------|------|------------------------------------|
| id            | String   | PK   | `PL1::<program_name>`             |
| type          | String   |      | `"pl1_program"`                   |
| name          | String   |      | Program name                       |
| file_path     | String   |      | Source file path                    |
| procedures    | String[] |      | Procedures defined in source       |
| calls         | String[] |      | Programs called via CALL           |
| includes      | String[] |      | Include files via %INCLUDE         |
| sql_tables    | String[] |      | DB tables accessed via EXEC SQL    |
| sql_operations| String   |      | Table -> operations map (JSON)     |
| missing       | Boolean  |      | True if source not found           |
 
### :Node:DBTable
 
Database table accessed via SQL.
 
| Property | Type   | Key? | Description              |
|---------|--------|------|--------------------------|
| id      | String | PK   | `DB::<table_name>`       |
| type    | String |      | `"db_table"`             |
| name    | String |      | Table name               |
 
### :Node:IncludeFile
 
PL/I include / copy member.
 
| Property | Type    | Key? | Description                  |
|---------|---------|------|------------------------------|
| id      | String  | PK   | `INCLUDE::<include_name>`    |
| type    | String  |      | `"include_file"`             |
| name    | String  |      | Include file name             |
| missing | Boolean |      | True if source not found      |
 
---
 
## Relationship Types & Properties
 
### CONTAINS
 
Hierarchy: Folder -> Application -> SubApplication -> Job.
 
| Direction                            | Properties |
|--------------------------------------|------------|
| `(:Folder)-[:CONTAINS]->(:Application)` | label      |
| `(:Application)-[:CONTAINS]->(:SubApplication)` | label |
| `(:SubApplication)-[:CONTAINS]->(:ControlMJob)` | label |
 
### PRODUCES
 
A job sets/produces a scheduling condition (OUTCOND).
 
| Direction                                  | Properties |
|--------------------------------------------|------------|
| `(:ControlMJob)-[:PRODUCES]->(:Condition)` | label, sign (`+` = set, `-` = clear), odate |
 
### REQUIRES
 
A job waits for / requires a scheduling condition (INCOND).
 
| Direction                                  | Properties |
|--------------------------------------------|------------|
| `(:ControlMJob)-[:REQUIRES]->(:Condition)` | label, and_or (`A` = AND, `O` = OR), odate |
 
### EXECUTES
 
A job directly executes a PL/I program (resolved via `DESCRIPTION` field: `PROGNAME = ...`).

| Direction                                        | Properties |
|--------------------------------------------------|------------|
| `(:ControlMJob)-[:EXECUTES]->(:PL1Program)`     | label      |
 
A PL/I program calls another PL/I program (via CALL statement).
 
| Direction                                    | Properties |
|----------------------------------------------|------------|
| `(:PL1Program)-[:CALLS]->(:PL1Program)`     | label      |
 
### INCLUDES
 
A PL/I program includes a copy member (via %INCLUDE).
 
| Direction                                      | Properties |
|------------------------------------------------|------------|
| `(:PL1Program)-[:INCLUDES]->(:IncludeFile)`   | label      |
 
### DB_ACCESS
 
A PL/I program accesses a database table (via EXEC SQL).
 
| Direction                                    | Properties          |
|----------------------------------------------|---------------------|
| `(:PL1Program)-[:DB_ACCESS]->(:DBTable)`    | label, operation (SELECT, INSERT, UPDATE, DELETE) |
 
---
 
## Constraints
 
```cypher
CREATE CONSTRAINT node_id_unique IF NOT EXISTS FOR (n:Node) REQUIRE n.id IS UNIQUE;
```
 
---
 
## Dependency Traversal: How Job-to-Job Dependencies Work
 
Job dependencies are no longer stored as direct Job->Job edges. Instead, they flow through **Condition** nodes:
 
```
JobA -[:PRODUCES]-> Condition <-[:REQUIRES]- JobB
```
 
This means: **JobA produces a condition that JobB requires** (JobB depends on JobA).
 
### Example Cypher queries
 
**Find all jobs that a specific job depends on (upstream):**
 
```cypher
MATCH (j:ControlMJob {name: 'TRALCHKB'})-[:REQUIRES]->(c:Condition)<-[:PRODUCES]-(upstream:ControlMJob)
RETURN upstream.name, c.name
```
 
**Find all jobs that depend on a specific job (downstream):**
 
```cypher
MATCH (j:ControlMJob {name: 'TRALCLEA'})-[:PRODUCES]->(c:Condition)<-[:REQUIRES]-(downstream:ControlMJob)
RETURN downstream.name, c.name
```
 
**Full hierarchy traversal: all jobs in a folder:**
 
```cypher
MATCH (f:Folder {name: '_TRPROD_ALERT_SWITCH'})-[:CONTAINS*1..3]->(j:ControlMJob)
RETURN j.name
```
 
**Orphan conditions (no producer):**
 
```cypher
MATCH (c:Condition) WHERE NOT ()-[:PRODUCES]->(c) RETURN c.name
```
 
**Orphan conditions (no consumer):**
 
```cypher
MATCH (c:Condition) WHERE NOT ()-[:REQUIRES]->(c) RETURN c.name
```
 
**End-to-end impact: from a folder down to database tables:**
 
```cypher
MATCH (f:Folder {name: 'X'})-[:CONTAINS*]->(j:ControlMJob)-[:EXECUTES]->(p:PL1Program)-[:DB_ACCESS]->(t:DBTable)
**Count jobs per folder (top 10):**
 
```cypher
MATCH (f:Folder)-[:CONTAINS*1..3]->(j:ControlMJob)
RETURN f.name, count(j) AS job_count ORDER BY job_count DESC LIMIT 10
```
 
---
 
## Visual Summary
 
```
 
┌───────────────┐
│  Application  │
└────┬──────────┘
     │ CONTAINS
┌────▼──────────────┐
│  SubApplication   │
└────┬──────────────┘
     │ CONTAINS
┌────▼─────┐
│  Folder  │
└────┬─────┘
     │ CONTAINS
┌────▼──────────────┐
│   Job             │──── EXECUTES ────────────────▶┌────────────┐
└─┬─────────────┬───┘   (via DESCRIPTION:            │ PL1Program │
  │             │        PROGNAME = ...)             └─┬────┬───┬─┘
  │ PRODUCES    │ REQUIRES                             │    │   │
  ▼             ▼                               CALLS  │    │   │ DB_ACCESS
┌───────────────────┐                      ┌───────────┘    │   └──────┐
│    Condition      │                      ▼           INCLUDES        ▼
└───────────────────┘               ┌───────────┐    ┌──▼──────────┐ ┌─────────┐
                                    │PL1Program │    │IncludeFile  │ │ DBTable │
                                    └───────────┘    └─────────────┘ └─────────┘
```