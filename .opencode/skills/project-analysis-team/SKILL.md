---
name: project-analysis-team
description: Analyze an entire software repository through a structured multi-agent workflow and produce evidence-backed technical, architecture, business, development-history, client-sales, interview, and literature documentation.
compatibility: opencode
metadata:
  workflow: repository-analysis
  audience: developers-architects-analysts
---

# Project Analysis Team

## Purpose

Use this skill when the user asks to deeply analyze an existing software project and produce professional technical, business, client, interview, or research documentation.

The goal is to accurately explain:
- what the project is
- why it exists
- how it works
- how it was built
- why its technologies are suitable
- what business problem it solves
- how it differs from traditional approaches
- what risks and limitations exist
- what evidence supports each conclusion

## Core principle

**Understand the repository first. Document second.**

The repository is the primary source of truth.

Never invent:
- features
- modules
- technologies
- metrics
- business outcomes
- development history
- architecture decisions
- research findings
- client requirements

When evidence is missing, write `Unknown` or `Could not be verified from the available project artifacts`.

## Evidence model

Classify important claims:

- **E1 — Direct evidence:** directly visible in source code, configuration, schema, tests, documentation, or Git history.
- **E2 — Strong inference:** not explicitly stated but strongly supported by implementation.
- **E3 — Engineering interpretation:** reasonable professional interpretation or recommendation.
- **E4 — Unknown:** insufficient evidence.

Never present E2, E3, or E4 as E1.

Also distinguish:
- **Implemented capability**
- **Measured/observed result**
- **Potential capability**
- **Business assumption**

## Security

Never expose:
- API keys
- passwords
- access tokens
- private keys
- connection secrets
- secret environment values

If configuration contains secrets, identify only the variable/configuration name and redact the value.

## Workflow

### Phase 1 — Repository reconnaissance

Inspect the complete repository.

Identify:
- directory structure
- source files
- entry points
- frontend
- backend
- APIs/routes
- controllers
- services
- models/entities
- repositories/data-access
- database/schema/migrations
- configuration
- dependencies
- tests
- deployment
- documentation
- integrations
- Git history

Trace important workflows across files. Do not rely on filenames alone.

### Phase 2 — Parallel specialist analysis

If subagents are available, delegate independent work in parallel.

Recommended specialist roles:

1. **Repository Explorer** — repository map, modules, dependencies, entry points, workflows.
2. **Architecture Reviewer** — architecture, module relationships, data flow, API flow, security, performance, scalability, maintainability.
3. **Technology Analyst** — languages, frameworks, libraries, database, deployment, alternatives, technology justification.
4. **Business Analyst** — business problem, users, business need, implemented value, potential value, limitations.
5. **Operations Analyst** — daily operations, management, reporting, workflow improvement, growth opportunities, traditional-process comparison.
6. **Development History Analyst** — Git history, commits, releases, development sequence, verified challenges.
7. **Sales & Interview Analyst** — client discovery, sales objections, technical interview questions, viva questions, scenarios.
8. **Literature Reviewer** — academic papers, existing software, open-source projects, industry solutions, architectures, research gaps.

### Phase 3 — Evidence audit

Cross-check specialist findings.

Look for:
- unsupported features
- fake metrics
- fabricated timelines
- unsupported technology decisions
- contradictory architecture descriptions
- unsupported security claims
- unsupported business benefits
- duplicate or conflicting findings
- weak literature claims

Resolve conflicts using repository evidence.

### Phase 4 — Documentation

Create final documentation under:

`docs/project-analysis/`

Recommended files:
- `PROJECT_ANALYSIS.txt`
- `EXECUTIVE_SUMMARY.txt`
- `BUSINESS_GUIDE.txt`
- `TECHNICAL_ARCHITECTURE.txt`
- `INTERVIEW_QA.txt`
- `LITERATURE_REVIEW.txt`
- `EVIDENCE_REGISTER.txt`

### Phase 5 — Final QA

Verify:
- all major modules were inspected
- implementation and potential features are separated
- historical claims are evidence-backed
- literature claims have sources
- business metrics are not invented
- architecture matches implementation
- technology choices do not pretend to know undocumented developer intent
- secrets are not exposed
- limitations are included
- contradictions are resolved or explicitly reported

## Required documentation content

The main analysis should cover:

1. Executive Summary
2. Project Overview
3. Business Problem
4. Business Need
5. Objectives
6. Target Users
7. Target Organizations
8. Project Scope
9. Features
10. Advanced Features
11. Technology Stack
12. Project Structure
13. Architecture
14. Module-by-Module Explanation
15. Application Workflow
16. Data Flow
17. Database Architecture
18. API Architecture
19. Technology Selection Justification
20. Alternative Technology Comparison
21. Development Approach
22. Verified Development Timeline
23. Development Challenges
24. Traditional vs Current Solution
25. Business Benefits
26. Operational Benefits
27. Management Benefits
28. Growth Opportunities
29. Security Analysis
30. Performance Analysis
31. Scalability Analysis
32. Limitations
33. Future Enhancements
34. Client/Sales Questions and Answers
35. Technical Interview Questions and Answers
36. Business Interview Questions and Answers
37. Literature Review
38. Existing/Similar Solutions
39. Research Gap
40. Technical/Business Differentiation
41. Final Assessment

## Development history rule

Only call a timeline historical when supported by Git commits, releases, changelogs, dated task records, issue history, or other reliable project artifacts.

If unavailable, explicitly state:

> Actual day-by-day development progress could not be verified from the available project artifacts.

You may provide a separate **Suggested Development Timeline**, clearly labelled as inference/recommendation.

## Technology-choice rule

For every major technology answer:
1. What is it?
2. Where is it used?
3. What problem does it solve?
4. Why is it suitable?
5. Advantages
6. Limitations
7. Realistic alternatives
8. Why an alternative might be less suitable

Do not say an alternative was rejected by the original developer unless evidence proves it.

## Business-analysis rule

Separate:
- **Implemented value**
- **Measured value**
- **Potential value**
- **Unknown**

Never invent ROI, revenue, savings, productivity percentages, customer counts, or adoption figures.

## Literature-review rule

For external research, record:
- title
- author/organization
- year
- source/URL
- problem
- approach
- technology
- findings
- limitations
- relevance

Never fabricate papers, authors, URLs, statistics, or research conclusions.

## Output style

Use:
- simple professional English
- clear headings
- tables where comparisons help
- bullets for long explanations
- Mermaid diagrams for architecture/workflows where useful
- concise but technically precise explanations

Avoid:
- marketing exaggeration
- generic filler
- repeated content
- unsupported claims
- unnecessary jargon

## Final maturity assessment

Assess the project as:
- Prototype
- Proof of Concept
- MVP
- Production-ready
- Enterprise-ready

Explain the rating using completeness, testing, security, error handling, deployment, scalability, maintainability, and operational readiness.

## Final summary

End with:
- What the project does
- Problem solved
- Target users
- Key features
- Technology stack
- Architecture
- Business value
- Technical strengths
- Technical weaknesses
- Security risks
- Scalability risks
- Current limitations
- Competitive differentiation
- Recommended improvements
- Evidence gaps
- Overall maturity
