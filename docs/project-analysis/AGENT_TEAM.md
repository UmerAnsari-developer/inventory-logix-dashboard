# Documentation Agent Team

This team is designed for OpenCode or another agent runner. It is evidence-first and must inspect the repository before writing project-specific claims. Agents may work in parallel when their scopes are independent. The final writer runs only after evidence review.

## Shared Rules

1. Read the complete relevant implementation, not filenames alone.
2. Treat the repository as the primary source of truth.
3. Never invent features, technologies, metrics, history, research, or business results.
4. Label claims as E1 direct evidence, E2 strong inference, E3 engineering interpretation, or E4 unknown.
5. Distinguish implemented capability, measured outcome, potential capability, business assumption, and unknown information.
6. Never expose secrets, passwords, tokens, connection strings, or private user data.
7. Do not modify application source code while producing documentation.
8. Cite file paths, functions, routes, database objects, tests, commits, or external references for major claims.
9. Preserve the distinction between a documentation plan and completed evidence.
10. If development history is insufficient, write a clearly labeled suggested timeline instead of fabricating one.

## Agent Roster

| Agent | Responsibility | Primary output |
|---|---|---|
| Repository Explorer | Map files, modules, routes, dependencies, data, tests, deployment, and documentation | Repository map and evidence inventory |
| Architecture Analyst | Trace request flow, module relationships, data flow, persistence, security, performance, and scalability | Technical architecture analysis |
| Technology Analyst | Identify technologies actually used and compare alternatives | Technology-stack and decision matrix |
| Requirements Analyst | Extract functional, non-functional, security, data, and operational requirements | Requirements specification and traceability |
| Business Analyst | Analyze the business problem, need, value, users, and limitations | Business and operational analysis |
| Data Analyst | Inspect schema, stored procedures, triggers, ETL, warehouse, and data quality | Database and data-flow analysis |
| UI and Report Analyst | Inspect templates, routes, charts, inputs, outputs, filters, exports, and accessibility | UI catalogue and report-page documentation |
| Security Analyst | Inspect authentication, authorization, validation, CSP, headers, secrets, SQL safety, and audit logs | Security chapter and risk register |
| Testing Analyst | Inspect tests, test plans, results, coverage gaps, and evidence quality | Testing and validation chapter |
| History Analyst | Inspect Git history, commits, dates, releases, and change evidence | Verified timeline and development challenges |
| Literature Analyst | Research academic foundations, official documentation, standards, and similar systems | Literature review with references and research gap |
| Interview and Sales Analyst | Prepare realistic client, technical, business, and viva questions | Interview and client Q&A |
| Evidence Auditor | Cross-check claims, contradictions, unsupported statements, duplication, and missing limitations | Audit report and corrections |
| Documentation Writer | Synthesize validated findings into the final academic report | Final report and chapter files |

## Execution Phases

### Phase 1 — Discovery

Run the Repository Explorer, Requirements Analyst, Data Analyst, Technology Analyst, Testing Analyst, and History Analyst in parallel. They should produce structured findings and file-level evidence.

### Phase 2 — Independent Analysis

After discovery, run the Architecture, Business, UI/Report, Security, Literature, and Interview/Sales agents in parallel. Each agent receives the discovery evidence but remains responsible for verifying claims against the repository or authoritative external sources.

### Phase 3 — Evidence Audit

The Evidence Auditor compares all outputs, verifies major claims, removes unsupported statements, identifies contradictions, and records E1–E4 evidence levels. The auditor must explicitly review the index, report pages, literature review, Chapter 5, and Chapter 7.

### Phase 4 — Synthesis

The Documentation Writer uses only the audited findings. The writer produces or updates the files listed in `ACADEMIC_DOCUMENTATION_INDEX.md`, preserves source references, and maintains the distinction between implemented and potential capabilities.

## Required Agent Output

Each agent should return:

```text
AGENT:
TASK:
FILES/AREAS ANALYZED:
KEY FINDINGS:
EVIDENCE:
ASSUMPTIONS:
UNKNOWN INFORMATION:
RISKS:
RECOMMENDATIONS:
CONFIDENCE:
OUTPUT FILE:
```

## Recommended Output Files

- `ACADEMIC_DOCUMENTATION_INDEX.md`
- `CHAPTER_5_TECHNOLOGY_STACK.md`
- `CHAPTER_7_SYSTEM_ARCHITECTURE.md`
- `REPORT_PAGES.md`
- `PROJECT_ANALYSIS.md`
- `TECHNICAL_ARCHITECTURE.md`
- `BUSINESS_GUIDE.md`
- `INTERVIEW_QA.md`
- `LITERATURE_REVIEW.md`
- `EVIDENCE_REGISTER.md`
- `Testing.md`

## Certificate-Page Policy

The certificate page is intentionally excluded from the preliminary-page sequence. It must not be added to the index, route map, template list, or final report. Institutional certificates and attestations should be supplied separately by the institution rather than generated as software-project documentation.
