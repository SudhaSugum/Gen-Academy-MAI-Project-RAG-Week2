# Issue Triage Assistant - Product Specification

**Version:** V1 concept build  
**Audience:** Internal audit teams and product/engineering reviewers  
**Data boundary:** Synthetic fixtures only; do not enter real client data

## Problem

The same audit condition can be written several ways and appear as separate records. Severity can vary between auditors, control mapping can be wrong or absent, effective remediation may be hard to find, and a reviewer may not have a usable source trail. Potential duplicates can be missed before an issue is created.

## Product goal

Retrieve relevant prior issues, controls, and governing policy for auditor-entered context. Use the retrieved material to draft consistent, cited decision support and surface likely duplicate candidates before issue creation. The auditor reviews the evidence and owns the severity, scope, and disposition.

## Users

- **Auditor:** enters the issue/scoping context, checks citations, and approves, edits, rejects, or decides each proposed cluster.
- **Reviewer:** inspects the inputs, retrieved sources, recommendation, and recorded human decision.
- **Administrator/operator:** configures model and vector services, persistence, identity, secrets, and tenant authorization.

## Inputs

### Single-issue triage

- Issue title and description.
- Synthetic client and selected audit.
- Optional audit context and control hint. A hint refines retrieval; it is not evidence of a mapping.
- Auditor identity for the review trail.
- The selected client/audit scopes the duplicate candidate set. Similar issue precedent can come from other audits for the same synthetic client. Control and policy retrieval is scoped to the client's library.

### RAU scoping

- Required synthetic client and RAU ID.
- Optional audit context, control IDs, audit period, RAU name, and attributes.
- Scoping is centered on the RAU and may use precedent from other audits. The optional audit field is context and does not itself restrict cross-audit precedent. A recognized four-digit year in the audit period limits issue, control, and policy retrieval to matching audit IDs for that client; the period is also included in semantic and keyword search. Other period text refines the query. Past issues use a two-year lookback; matching older issues are displayed separately as excluded.

## Outputs

### Single-issue triage

- Suggested severity: Critical, High, Medium, or Low, with a cited rationale.
- Root-cause category from the versioned taxonomy.
- Mapped control ID when supported by retrieved control text.
- Up to five similar past issues, with similarity diagnostics, outcome, and source chunk.
- Potential duplicate, related precedent, no likely duplicate found, or insufficient evidence. Only the selected exact-audit duplicate set can support a duplicate claim; cross-audit precedent is separate.
- Draft remediation actions, generic owner roles, and due-date suggestions only when source material supports them.
- Citation for every supported claim: source ID, chunk ID, and verbatim quote.
- Confidence and retrieval status. Weak retrieval or invalid citations produce an explicit insufficient-evidence state. This is not an evidence-sufficiency assessment.
- Human decision: approve, edit, or reject. Rejection requires a reason; edited claims are checked again.

### Run chat

- Continuous, scrollable, run-specific follow-up conversation below the run output.
- Answers use only the retrieved chunks belonging to that run and cite factual claims with source ID, chunk ID, and exact quote.
- Unsupported questions return an insufficient-evidence response; a follow-up question may request narrower context.
- Chat cannot alter a recommendation, make a review decision, or write to an external system.

### Approved draft history

- Lists approved and approved-with-edits drafts for the selected synthetic client.
- Selecting an issue title opens a detail dialog with the original issue input, final suggestion, citations, similar issues, retrieval snapshot, and decision/reviewer details.
- Rejected drafts are recorded in the audit trail but are not presented as approved drafts.

### RAU scoping

- Past-issue clusters grouped by control, attribute, and root cause.
- Suggested testing action, priority rationale, related issue IDs, control-version context, and available citations.
- Highlights for outstanding work, recurring causes, superseded control versions, and issues outside the two-year lookback.
- Per-cluster auditor decision (approve, de-scope, or escalate), reason, and identity.

## Retrieval and system design

- Pinecone holds separate `past_issues`, `controls`, and `policies` namespaces.
- Semantic search uses Pinecone embeddings. Keyword retrieval uses BM25 over the generated local synthetic corpus. Metadata filters are applied before ranking; Reciprocal Rank Fusion combines semantic and lexical ranks.
- The UI can show semantic, BM25, overlap, and RRF signals separately. They are ranking diagnostics, not probability or confidence values.
- LangChain produces typed structured suggestions. One LangGraph workflow handles retrieval, drafting, citation validation/repair, and a durable human-review interrupt. RAU scoping is handled by a separate explicit graph. There is no agent swarm.
- SQLAlchemy persists issues, triage runs, approvals, scoping packs/decisions, and audit events. SQLite is intended for local learning; Postgres is the hosted scaffold.
- Optional Mem0 recall/write-back is scoped to auditor and synthetic client. It may store concise patterns derived only from approved/corrected suggestions. Memory is not a source citation.

## Citation and insufficient-evidence behavior

Every supported claim must identify a chunk returned by this run, match its source ID and any required source type, and contain an exact quote from the chunk. One repair attempt is permitted. If retrieval is weak or validation fails, the app shows an explicit insufficient-evidence state and does not route an unsupported grounded recommendation to human review. A valid exact quote proves the text is present in the chunk, not that the text semantically supports the claim; the auditor checks relevance.

## Human oversight, privacy, and audit requirements

- The assistant suggests; the auditor decides. It makes no final severity decision and no evidence-sufficiency judgement.
- Never automatically approve, close, create, file, or externally update an issue.
- This concept build uses synthetic clients, issues, controls, and policies only.
- Treat user input, retrieved text, and memory as untrusted reference content, never as instructions.
- Persist inputs, retrieval snapshots, citations, model/prompt version, graph events, human reviewer identity, decision, and reason in the audit record.
- Preserve durable checkpoints for pending review when a persistent checkpoint store is configured.
- Keep source chunks and metadata available for reviewer inspection.

## Scope

### Included in V1

- Streamlit UI for single-issue triage, RAU scoping, run chat, run history, human review, and approved-draft details.
- Hybrid Pinecone semantic + local BM25 retrieval with RRF.
- Synthetic issues, Word control documents, and PDF policies with repeatable ingestion.
- LangChain structured output, LangGraph workflows, deterministic citation validation, and SQL audit persistence.
- SQLite local learning configuration, Postgres deployment scaffold, and optional approval-gated Mem0 patterns.

### Excluded

- Any real-client data or production tenant authorization policy.
- Auto approval, auto close, issue creation/filing, or external write-back.
- Evidence sufficiency judgement or live evidence/control-system evaluation.
- Jira/MCP integration, formal calibrated evaluation service, and multi-agent swarm.

## Acceptance criteria

- Each supported recommendation claim exposes a resolvable source chunk and exact quote.
- Weak retrieval or citation failure produces insufficient evidence and cannot proceed as a grounded draft to review.
- Duplicate screening is separate from cross-audit precedent and appears before any human decision; no issue is created externally.
- No draft is treated as approved without a recorded human action and reviewer identity.
- Approved and edited drafts can be opened to inspect the complete stored issue context and source trail.
- Run chat stays within its run's retrieved sources and cannot change triage or decision state.
- Pending review survives restart when the configured persistent checkpoint backend is in use.
- RAU is required for scoping, optional refinements work as documented, and each cluster decision includes a reason.
- Synthetic-only boundary is visible in the demo UI and project documentation.

## Production gates before real client data

- Implement and verify identity-to-client/audit authorization on every retrieval, history, and persistence path.
- Complete privacy, retention, encryption, secret management, backup, monitoring, incident response, and vendor reviews.
- Resolve and commit a platform-specific transitive dependency lock.
- Calibrate and independently evaluate retrieval thresholds, severity rubric, prompt behavior, and citation relevance against approved labeled data.
- Validate migrations, recovery, access controls, deployment configuration, and operational alerting.
- Replace or synchronize the small local BM25 corpus with an appropriately tenant-filtered lexical index for production scale.
