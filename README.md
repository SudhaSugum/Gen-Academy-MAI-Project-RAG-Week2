# Issue Triage Assistant - V1 concept

An evidence-grounded decision-support app for internal auditors. An auditor enters a newly observed issue; the app retrieves similar synthetic past issues, relevant controls, and policy passages; then drafts source-linked suggestions for review. The auditor owns severity and disposition. **This concept build uses synthetic data only.**

## Product idea

Today the same condition can be recorded in different words, severity and control mapping can vary, useful remediation precedent is hard to locate, and reviewers may not be able to check the basis of a recommendation. The assistant uses hybrid retrieval to surface precedent, shows duplicate candidates before an issue is created, and ties each supported suggestion to its source text.

The assistant suggests; the auditor decides. It does not auto-approve, close, create, file, or update issues in an external system. Retrieval weakness is not an evidence-sufficiency judgement.

## Current user experience

- **Single-issue triage:** Enter a title and description, choose a synthetic client and audit, and optionally provide audit context or a control hint. Duplicate screening uses the selected client and exact audit. Similar precedent can come from other audits for that client. A control hint is a search hint, not proof.
- **Draft output:** Suggested severity (Critical, High, Medium, Low), root-cause category, mapped control, duplicate warning, up to five similar past issues and outcomes, remediation steps with generic owner roles and supported due-date suggestions, confidence, retrieval state, and citations.
- **Human decision:** Approve, edit, or reject a grounded draft. Rejection requires a reason; edits are citation-validated again. Decision and reviewer details are saved to the local SQL audit store. No external issue is filed or closed.
- **Approved draft history:** Approved and edited drafts are listed by issue title. Opening a title shows the original issue input, final suggestion, citations, similar issues, retrieval context, and decision details.
- **Run chat:** A continuous, scrollable, per-run chat answers questions using only the sources retrieved for that triage or scoping run. It cites factual claims and cannot change the suggestion or record an auditor decision.
- **RAU scoping:** Requires a synthetic client and RAU ID. Optional audit, control, period, RAU name, and attributes refine the search. Retrieval groups precedent by control, attribute, and root cause across audits, applies a two-year issue lookback, and shows older excluded records. A recognized year in the audit period limits issue, control, and policy retrieval to matching client audit IDs. Each cluster waits for an auditor decision and reason.

## Architecture

- **Streamlit** provides the intake, scoping, source review, chat, decision, and approved-draft interfaces.
- **LangChain** formats prompts and parses structured model output.
- **LangGraph** coordinates retrieval, drafting, citation validation/repair, and the durable human review pause. Scoping uses an explicit graph as well; there is no multi-agent swarm.
- **Pinecone** stores three namespaces: `past_issues`, `controls`, and `policies`.
- **Hybrid retrieval** combines Pinecone semantic search with BM25 keyword search over the small local synthetic corpus using Reciprocal Rank Fusion (RRF). Metadata filters are applied before ranking. UI semantic, BM25, overlap, and RRF values are retrieval diagnostics, not confidence probabilities.
- **SQLAlchemy** stores triage and scoping records, review decisions, retrieved snapshots, and audit events. SQLite is for local learning; Postgres is available in the hosted deployment scaffold.
- **Optional Mem0** recalls and stores only concise, approved/corrected patterns scoped to auditor and synthetic client. Memory is not a citation and never receives raw issues, evidence chunks, or unapproved drafts.

## Data and citations

The deterministic generator creates 60 synthetic past issues, 36 synthetic control Word documents, and five synthetic policy PDFs from source definitions. CSV/Markdown source definitions are generation inputs; the extracted Word/PDF text is indexed and cited. The ingestion command creates/upserts chunks in the Pinecone namespaces.

Every supported suggestion claim must reference a retrieved source ID, chunk ID, and verbatim quote. The validator checks retrieval membership, source identity/type where required, and exact quote matching, with one repair attempt. A failed citation check or weak retrieval produces an explicit **Insufficient evidence** state and does not route a grounded recommendation for review. Exact-quote matching confirms the text exists in the cited chunk; it does not prove semantic support, which the auditor must judge.

## Local setup

Requires Python 3.11-3.13.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set `OPENAI_API_KEY` and `PINECONE_API_KEY` in `.env`. `MEM0_API_KEY` is optional. Configure the Pinecone index according to `.env.example`, then generate and ingest the synthetic corpus:

```bash
python scripts/generate_synthetic_data.py
python -m src.issue_triage.ingestion.cli_ingest
streamlit run app.py
```

The default embedding contract is cosine similarity with `text-embedding-3-small` at 1,536 dimensions. The index has separate namespaces for issues, controls, and policies. A regular ingest upserts the synthetic chunks. `--rebuild` deletes the configured namespaces and should only be used with the dedicated concept index.

## Hosted scaffold and readiness limits

Docker Compose provides a private Postgres service and binds Streamlit to loopback for a trusted reverse proxy. Hosted configuration requires deployment-managed secrets, HTTPS, OIDC, provider network access, backups, monitoring, and database encryption. Direct dependencies are pinned, but the repository does not contain a fully resolved platform-specific transitive lock.

This is **not ready for real client information**. Before that, implement and verify identity-to-client/audit authorization on every query and record read/write path; complete privacy, retention, security, backup, and operational reviews; create a resolved dependency lock; and independently evaluate retrieval thresholds, severity calibration, prompt behavior, and citation relevance using approved labeled data. OIDC sign-in alone does not provide tenant authorization.

## Configuration

See `.env.example`. Common settings include:

| Setting | Purpose |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy database URL; SQLite locally, Postgres when hosted |
| `CHECKPOINT_BACKEND` | Durable workflow checkpoint backend |
| `CHECKPOINT_DATABASE_URL` | Checkpoint database connection |
| `PINECONE_INDEX` | Vector index for the selected embedding model and dimension |
| `RETRIEVAL_THRESHOLD` | Initial concept semantic retrieval threshold |
| `KEYWORD_OVERLAP_THRESHOLD` | Minimum query-term overlap for a keyword-only signal |
| `PROMPT_VERSION` | Prompt version recorded with a run |

Keep credentials in environment/deployment secret storage. Do not put secrets in prompts, widgets, graph state, source files, or logs.

## Project documentation

- [`docs/product_spec.md`](docs/product_spec.md): current workflows, requirements, scope, and deployment gates.
- [`docs/system_prompt.md`](docs/system_prompt.md): model behavior, citation contract, and human-oversight instructions.
- [`AGENTS.md`](AGENTS.md): durable implementation constraints and evidence rules for contributors.
- [`SKILLS.md`](SKILLS.md): project architecture and learning workflow.

## Project layout

```text
app.py
src/issue_triage/
  audit_log/      SQL audit records
  graph/          Single-issue and scoping LangGraph workflows
  ingestion/      CSV/DOCX/PDF loaders, chunking, and upsert CLI
  memory/         Approval-gated Mem0 adapter
  retrieval/      Pinecone + BM25 hybrid search
  triage/         Structured output schema and taxonomy
  scoping.py      RAU retrieval, clustering, and action proposal
data/synthetic/   Fictional CSV/Markdown definitions and generated DOCX/PDF sources
data/golden/      Reserved for human-confirmed evaluation labels
```
