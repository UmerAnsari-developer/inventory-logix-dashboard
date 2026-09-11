# Chapter 7 — System Architecture

## 7.1 Purpose of This Chapter

This chapter explains how the system is structured, how its components communicate, where data is stored, and how security, deployment, and operational concerns are handled. It must describe the architecture visible in the implementation. Do not infer a microservice, event-driven, real-time, cloud-native, or scalable architecture unless the repository and deployment artifacts support that description.

## 7.2 Architecture Overview

State the architectural style or styles that are directly supported by the code, such as monolith, modular monolith, client-server, layered architecture, MVC, microservices, event-driven, serverless, or hybrid.

Include a high-level diagram showing:

- Users and external actors
- Client or frontend
- Application entry point
- Business services
- Persistence layer
- External integrations
- Background workers or scheduled jobs
- Monitoring and deployment infrastructure

## 7.3 Architectural Drivers

Document the requirements that shaped the architecture:

| Driver | Required behavior | Architectural response | Evidence |
|---|---|---|---|
| Security | `[requirement]` | `[control or component]` | `[file/test]` |
| Performance | `[requirement]` | `[cache/index/async path]` | `[file/test]` |
| Maintainability | `[requirement]` | `[module boundary/pattern]` | `[file]` |
| Availability | `[requirement]` | `[health check/recovery]` | `[deployment]` |
| Scalability | `[requirement]` | `[worker/database strategy]` | `[config]` |

## 7.4 System Context

Describe who uses the system, what systems interact with it, what information crosses each boundary, and what remains outside the system scope. Include a context diagram and identify trust boundaries.

## 7.5 Deployment Architecture

Document the environments and runtime topology:

- Local development
- Test or quality-assurance environment
- Staging environment, if present
- Production environment
- Web server and process model
- Database hosting
- Object storage or file storage
- DNS, TLS, CDN, and network boundaries
- Environment-variable and secret injection

Distinguish deployment configuration from evidence that the deployment is currently active.

## 7.6 Frontend or Client Architecture

Describe pages, screens, components, state management, browser storage, routing, rendering strategy, form handling, API clients, visualization, accessibility, and error states. Explain whether the client is server-rendered, single-page, native, mobile, desktop, or hybrid.

## 7.7 Backend or Application Architecture

Describe the request lifecycle:

1. Request enters the server.
2. Middleware and security controls execute.
3. Route or controller validates the request.
4. Service layer applies business rules.
5. Repository or data-access layer reads or writes data.
6. Response is rendered or serialized.
7. Logging, caching, and cleanup execute.

Map each step to actual modules and functions.

## 7.8 Data and Database Architecture

Document:

- Operational entities
- Relationships and constraints
- Indexes
- Transactions
- Stored procedures and triggers
- ORM or raw SQL
- Caching
- Reporting tables
- Data warehouse or analytical stores
- ETL and synchronization
- Data retention and deletion
- Backup and recovery

Include an ERD and, where relevant, a warehouse star-schema diagram.

## 7.9 API and Integration Architecture

For each API, document:

| Interface | Method or event | Input | Output | Authentication | Error behavior | Evidence |
|---|---|---|---|---|---|---|
| `[endpoint/service]` | `[GET/POST/event]` | `[schema]` | `[schema]` | `[control]` | `[behavior]` | `[route/test]` |

Include versioning, pagination, filtering, idempotency, timeouts, retries, webhooks, external dependencies, and data contracts where applicable.

## 7.10 Authentication and Authorization Boundaries

Explain identity establishment, session or token handling, route protection, role or permission checks, service-to-service authentication, secret boundaries, and data-level authorization. Identify which components are trusted and which are user-controlled.

## 7.11 Asynchronous, Event, or Real-Time Components

Document queues, workers, scheduled tasks, WebSockets, server-sent events, polling, background threads, event brokers, and retry mechanisms. If the project has no such component, say so explicitly rather than adding a WebSocket section as if it were implemented.

## 7.12 Caching and Performance Architecture

Describe cache keys, TTLs, invalidation, storage scope, query batching, indexes, lazy loading, pagination, concurrency, and expensive operations. Record whether cache state is process-local or shared across instances.

## 7.13 Error Handling and Observability

Document structured errors, user-safe error pages, logging, metrics, traces, health checks, alerting, audit events, correlation IDs, and operational dashboards. Identify failures that are retried, degraded, surfaced, or silently logged.

## 7.14 Security Architecture

Map security controls to boundaries:

| Boundary | Threat | Control | Evidence | Remaining risk |
|---|---|---|---|---|
| Browser | `[threat]` | `[CSP/header/validation]` | `[file/test]` | `[risk]` |
| API | `[threat]` | `[auth/rate limit/schema]` | `[file/test]` | `[risk]` |
| Database | `[threat]` | `[parameterization/RLS/roles]` | `[file]` | `[risk]` |
| Deployment | `[threat]` | `[TLS/secret/worker config]` | `[deployment]` | `[risk]` |

## 7.15 Scalability, Resilience, and Recovery

Explain how the architecture behaves as users, records, requests, or integrations grow. Discuss horizontal scaling, worker count, database capacity, connection pools, distributed state, failure isolation, graceful degradation, backups, recovery objectives, and single points of failure.

## 7.16 Architecture Decisions and Alternatives

| Decision | Problem addressed | Benefit | Cost or limitation | Alternative | Evidence level |
|---|---|---|---|---|---|
| `[decision]` | `[problem]` | `[benefit]` | `[limitation]` | `[alternative]` | E1 / E2 / E3 / E4 |

Use the following evidence levels:

- **E1 — Direct evidence:** visible in code, configuration, database, tests, or history.
- **E2 — Strong inference:** strongly supported by implementation but not explicitly stated.
- **E3 — Engineering interpretation:** reasonable technical analysis.
- **E4 — Unknown:** insufficient evidence.

## 7.17 Architecture Diagrams

Where useful, include:

- System context diagram
- Container or component diagram
- Deployment diagram
- Request-flow sequence diagram
- Data-flow diagram
- ERD
- Data warehouse star schema
- Authentication and trust-boundary diagram
- Background-job or integration sequence

Every diagram must match the current implementation and identify external systems as external.

## 7.18 Chapter Conclusion

Conclude with the architecture’s maturity level, strengths, weaknesses, scalability limits, security posture, operational risks, and highest-priority improvements. Do not call the architecture enterprise-ready without evidence for availability, observability, recovery, performance, and security requirements.
