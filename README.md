# Issue Triage Assistant — V1

An evidence-grounded audit decision-support module built from the attached project plan. V1 includes single-issue triage and RAU Scoping Mode. The same LangGraph workflow owns retrieval, recommendation, citation validation, and the human approval pause. This build uses synthetic clients, issues, controls, and policies only.

## Included in V1

- 60 labelled synthetic past issues, 36 synthetic control Word documents, and 5 synthetic policy PDFs. `scripts/generate_synthetic_data.py` deterministically generates these from the synthetic CSV/Markdown source definitions.
- Three Pinecone namespaces: `past_issues`, `controls`, and `policies`. Retrieval applies client/audit metadata filters before ranking and combines Pinecone semantic results with local BM25 keyword results using Reciprocal Rank Fusion (RRF).
- Controls are extracted from `.docx`; policies are extracted from `.pdf` and section-chunked with overlap; past issues remain in CSV. The PDF/Word text is the actual indexed and cited source text.
- Retrieval cards show semantic score, BM25 keyword score, and RRF score separately. RRF scores express ranking only, not confidence or probability. Weak retrieval screening uses calibrated semantic and keyword-overlap thresholds.
- The triage form pairs `synthetic-client-a` with `synthetic-audit-iam-2026` and `synthetic-client-b` with `synthetic-audit-finance-2026` so tenant/audit filters address an existing corpus partition.
- Structured LangChain output, a versioned severity rubric/root-cause taxonomy, and deterministic citation checks for retrieved chunk IDs and verbatim quotes. One repair attempt is allowed; failed validation routes to Insufficient evidence.
- Durable LangGraph approval interrupt. Pending reviews can be loaded after an app restart. Rejection requires a reason; an edited recommendation is validated again before it is recorded.
- SQL audit tables for issues, triage runs, approvals, scoping packs, and per-cluster decisions. SQLite blocks update/delete of the append-only audit tables; Postgres is supported for hosted deployments.
- Optional Mem0 recall scoped to auditor + client. Only a compact pattern derived from an approved or edited suggestion can be written; raw issues, source chunks, and unapproved drafts are never sent to Mem0.
- Scoping Mode requires a RAU ID and uses it as the primary retrieval filter. Client and control narrow retrieval when supplied; audit is optional context so precedent can come from other audits. It groups issues by control + attribute + root cause, shows an explicit two-year lookback and older excluded issues, and requires a reason for each auditor decision.
- OIDC sign-in in production mode. The local demo selector is disabled when `APP_ENV=production`.

Product and agent guidance live in [`docs/product_spec.md`](docs/product_spec.md), [`docs/system_prompt.md`](docs/system_prompt.md), and [`AGENTS.md`](AGENTS.md). The triage graph loads its system prompt from the prompt document, inserting the current severity rubric and root-cause taxonomy at runtime.

## Local setup

Requires Python 3.11–3.13.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set `OPENAI_API_KEY` and `PINECONE_API_KEY` in `.env`. `MEM0_API_KEY` is optional; without it, the graph logs that memory was unavailable and continues. Then create the Pinecone index and load the synthetic corpus:

```bash
python scripts/generate_synthetic_data.py
python -m src.issue_triage.ingestion.cli_ingest
streamlit run app.py
```

The index contract is cosine similarity, `text-embedding-3-small`, 1,536 dimensions, AWS `us-east-1` by default. The ingestion command checks an existing index dimension and stops on a mismatch. A regular ingestion upserts the current synthetic source chunks; `--rebuild` deletes all three configured namespaces and should only be used for the dedicated concept index.

## Hosted deployment scaffold

The Docker Compose configuration starts a private Postgres service and binds Streamlit only to loopback (`127.0.0.1:8501`) for a trusted reverse proxy. Provide `.env` values from a secret manager, including an URL-safe `DB_PASSWORD`, provider keys, and a real OIDC configuration mounted at `.streamlit/secrets.toml`. The example template is `.streamlit/secrets.example.toml`. Configure HTTPS, the OIDC redirect URI, network egress to approved model/vector services, backups, monitoring, and managed database encryption at rest in the host environment.

```bash
docker compose up --build
```

`pyproject.toml` and `requirements.txt` pin the direct application dependencies. Generate and commit a complete platform-specific transitive lock (for example `uv.lock`) before release; this workspace does not include a resolved lock yet.

## Configuration

See `.env.example`. Important settings:

| Setting | Purpose |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy URL; SQLite locally, Postgres when hosted |
| `CHECKPOINT_BACKEND` | `sqlite` locally or `postgres` when hosted |
| `CHECKPOINT_DATABASE_URL` | Durable graph checkpoint connection |
| `PINECONE_INDEX` | One index for the selected embedding model/dimension |
| `RETRIEVAL_THRESHOLD` | Semantic weak-retrieval screening threshold (initial concept calibration) |
| `KEYWORD_OVERLAP_THRESHOLD` | Minimum fraction of distinct query terms matched for a keyword-only retrieval signal (default `0.12`) |
| `PROMPT_VERSION` | Prompt identifier recorded in each run |
| `LANGGRAPH_STRICT_MSGPACK` | Restricts checkpoint deserialization to safe types |

Secrets are environment/deployment-secret values. They are not accepted in Streamlit widgets and are never written into graph state, prompts, or application logs.

## Product boundaries

- The assistant suggests; the auditor decides. No automatic approval, closure, Jira draft, or filing exists in V1.
- Semantic and keyword thresholds measure retrieval signals only. They are not an evidence sufficiency judgement. RRF is used to order results and is not a probability.
- BM25 keyword retrieval reads the generated local synthetic corpus and is intended for this small concept build. A real deployment needs a tenant-filtered, synchronized lexical index alongside vector retrieval.
- Scoping decisions are per cluster and remain auditor-owned. Older records and control-version conflicts are surfaced for review rather than silently carried forward.
- This build has no production identity-to-tenant authorization policy or client data. OIDC authenticates hosted users, but client/audit authorization and organization-specific access rules must be configured before real tenant data is introduced.
- Exact-quote validation proves a citation resolves to a retrieved chunk. It does not prove the quote semantically supports the conclusion; that still requires auditor review.
- V2 MCP servers and Jira drafts, live evidence/control systems, and V3 evaluation framework are intentionally not included. V1 carries no external side effects.

## Project layout

```text
app.py
src/issue_triage/
  audit_log/      SQL audit records
  graph/          Single LangGraph workflow
  ingestion/      DOCX/PDF/CSV loaders, chunker, and upsert CLI
  memory/         Approval-gated Mem0 adapter
  retrieval/      Tenant-filtered Pinecone + BM25 hybrid search
  triage/         Structured output schema and locked taxonomy
  scoping.py      RAU retrieval, clustering, and action proposal
data/synthetic/   Fictional CSV/Markdown definitions and generated DOCX/PDF sources
data/golden/      Reserved for human-confirmed V3 evaluation labels
```
