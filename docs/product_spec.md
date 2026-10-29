# Issue Triage Assistant — Product Specification

**Version:** V1 concept build  
**Audience:** Internal audit teams and product/engineering reviewers  
**Data boundary:** Synthetic fixtures only

## Problem

Auditors may record the same underlying issue in different words, assign inconsistent severities, miss the right control, or fail to find useful remediation precedent. Reviewers then have to reconstruct the basis for a recommendation without a reliable citation trail.

## Product goal

Help an auditor assess a newly logged issue by retrieving relevant precedent, controls, and policy, then presenting a cited draft for human review. The assistant reduces search and drafting effort while preserving auditor ownership of the decision.

## Users

- **Auditor:** provides issue and audit context, reviews cited recommendations, and approves, edits, or rejects the draft.
- **Reviewer:** inspects the audit trail, supporting source chunks, and the recorded human decision.
- **Administrator/operator:** configures models, vector index, persistence, secrets, identity, and tenant authorization.

## Inputs

### Single-issue triage

- New issue title and description.
- Synthetic client and audit context.
- The selected audit anchors the current triage. Duplicate candidates are filtered to that exact client and audit; similar issue precedents are retrieved from the same client's other audits. Controls and policies are retrieved from the same client's library. The synthetic fixture includes two audit years per client to exercise these boundaries.
- Optional control hint. It is a retrieval hint, not proof of a control mapping.
- Auditor identity for the review trail.

### RAU Scoping Mode

- Synthetic client and audit, risk assessable unit (RAU), audit period, in-scope control IDs, and attributes to test.
- A two-year lookback is applied to past issues across audits tied to the required RAU. Client and control are optional filters; older matching issues are shown separately as excluded from the current lookback. Audit is optional run context and does not restrict cross-audit precedent.

## Outputs

### Single-issue triage

- Suggested severity: Critical, High, Medium, or Low, with rationale.
- Root-cause category from the versioned taxonomy.
- Mapped control ID, when supported.
- Up to five similar past issues, with similarity, recorded outcome, and resolvable source chunk.
- Draft remediation steps with action, generic owner role, and due-date suggestion.
- Duplicate warning: Potential duplicate, Related precedent, No likely duplicate found, or Insufficient evidence.
- Claim-level citations containing source ID, chunk ID, and exact quote.
- Confidence and retrieval status. Weak retrieval returns an explicit insufficient-evidence state; this is not an evidence-sufficiency judgement.
- Human decision: approve, edit, or reject. Rejection requires a reason; edited claims are citation-validated again.
- Run chat: answers questions from the active run's retrieved chunks, cites each factual claim with a source ID, chunk ID, and exact quote, and asks a follow-up when useful issue context is missing. Unsupported questions receive an explicit response. Chat cannot change suggestions or record auditor decisions.

### Scoping Mode

- Clusters past issues by control, attribute, and root cause.
- Displays a suggested testing action, priority rationale, source issue IDs, control-version context, and citations.
- Highlights superseded control versions, outstanding issues, recurring causes, and older excluded issues.
- Pauses for an auditor to approve, de-scope, or escalate each cluster with a reason and approver identity.

## Core workflow

1. Validate required input and bind it to a synthetic client/audit context. Retrieve exact-audit duplicate candidates separately from same-client, cross-audit precedent.
2. Recall only approved, client/auditor-scoped memory patterns when configured.
3. Retrieve exact-audit duplicate candidates, same-client past-issue precedents, controls, and policies from separate Pinecone namespaces. Apply client and audit filters to duplicate candidates; scoping requires RAU and optionally applies client and control filters before ranking, with audit intentionally omitted there. Fuse Pinecone semantic results with BM25 keyword results using Reciprocal Rank Fusion (RRF), applying the same metadata filters to the local keyword corpus before lexical scoring.
4. Generate a structured suggestion from retrieved evidence using the configured LangChain model.
5. Validate each citation against retrieved chunk ID, source ID, source type where required, and exact quote. Allow one repair attempt; otherwise show insufficient evidence.
6. Pause the LangGraph workflow for human review. Persist the decision and reviewer identity in the SQL audit trail.
7. Write only a concise approved/corrected pattern to optional memory. Never write raw issue text, evidence chunks, or unapproved drafts.

## Safety, privacy, and audit requirements

- No automatic approval, closure, filing, issue creation in an external tracker, or other write-back to systems of record.
- No final severity decision and no evidence-sufficiency judgement.
- No real client data in this concept build.
- Retrieved text and memory are untrusted inputs, not instructions.
- Record inputs, retrieval results, model/prompt version, graph events, citations, latency/token metadata when available, and human decisions in the audit log.
- Preserve a durable checkpoint for pending human reviews.
- Keep source chunks and tenant metadata available to the reviewer; do not treat a valid exact quote as proof of semantic support.

## V1 scope

### Included

- Streamlit review UI.
- Pinecone retrieval across past issues, controls, and policies.
- Hybrid retrieval: Pinecone semantic search + BM25 keyword search, fused with RRF. Controls are loaded from Word `.docx` and policies from PDF `.pdf`; citations resolve to the extracted source chunks. Synthetic CSV/Markdown files remain generation inputs.
- LangChain structured generation and LangGraph retrieval, validation, and review workflow.
- Synthetic issue/control/policy corpus and repeatable ingestion CLI.
- SQL audit store, resumable approval state, and optional Mem0 approved-pattern recall/write-back.
- Single-issue triage and RAU Scoping Mode.

### Excluded

- Jira/MCP integration, automatic issue filing, or issue closure.
- Live control/evidence systems and evidence sufficiency decisions.
- Multi-agent swarm.
- Production tenant authorization policy, real client data, formal evaluation suite, and organization-specific severity calibration.

## Acceptance criteria

- Every supported displayed recommendation field can be opened to its exact retrieved source chunk and quote.
- Weak retrieval or failed citation validation produces an explicit insufficient-evidence result and does not reach human approval as a grounded draft.
- The duplicate warning is displayed before a reviewer takes a decision; the application does not create an external issue.
- No decision is treated as approved without a human action and approver identity.
- Pending review survives application restart when using the configured persistent checkpoint store.
- Scoping requires RAU and applies optional client, control, and lookback filters before similarity ranking across audits; each cluster requires a reasoned human decision.
- The demo UI and fixture data are explicitly identified as synthetic.

## Deployment gates before real client data

- Implement and verify identity-to-client/audit authorization on every query and record read/write path.
- Complete privacy, retention, encryption, secrets, backup, monitoring, incident response, and vendor review.
- Resolve and commit a platform-appropriate transitive dependency lock.
- Calibrate and independently evaluate retrieval thresholds, severity rubric, prompt behavior, and citation relevance against approved labeled data.
- Validate deployment configuration, database migrations, recovery, access controls, and operational alerting.
