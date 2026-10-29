# Project skills

This file maps the main skills and concepts practiced in the Issue Triage Assistant. It is a learning guide for this synthetic V1 project; implementation boundaries and agent instructions remain in [`AGENTS.md`](AGENTS.md).

## Application and interaction design

- Build an auditor workflow in Streamlit with intake forms, source-linked results, chat, and human review controls. See [`app.py`](app.py).
- Keep the experience human-in-the-loop: auditors approve, edit, reject, or decide each scoping cluster. The application never auto-approves, closes, or files an issue.
- Present retrieval and recommendation evidence separately so reviewers can inspect source records and citations.

## Document ingestion and hybrid RAG

- Load structured synthetic issues from CSV, controls from Word documents, and policies from PDFs. See [`src/issue_triage/ingestion/corpus.py`](src/issue_triage/ingestion/corpus.py).
- Split policy documents into searchable chunks and preserve source IDs, chunk IDs, and metadata for citation resolution.
- Generate embeddings and retrieve semantic matches from Pinecone. See [`src/issue_triage/retrieval/pinecone_store.py`](src/issue_triage/retrieval/pinecone_store.py).
- Run BM25 lexical retrieval against the local synthetic corpus and combine semantic and keyword result ranks with Reciprocal Rank Fusion. See [`src/issue_triage/retrieval/hybrid.py`](src/issue_triage/retrieval/hybrid.py).
- Distinguish semantic similarity, BM25 score, keyword overlap, and RRF rank. These are retrieval signals, not confidence or probability scores.

## Stateful workflows and review

- Model retrieval, drafting, citation validation, repair, and the auditor approval pause as an explicit LangGraph workflow. See [`src/issue_triage/graph/workflow.py`](src/issue_triage/graph/workflow.py).
- Implement RAU-centered scoping with optional client/control filters, clustering, resumable review, and per-cluster decision reasons. See [`src/issue_triage/graph/scoping.py`](src/issue_triage/graph/scoping.py) and [`src/issue_triage/scoping.py`](src/issue_triage/scoping.py).
- Validate that citations resolve to retrieved chunks and contain exact source quotes. Exact quote validation does not establish that a quote semantically supports a conclusion; the auditor reviews that.

## Audit data and persistence

- Store issue runs, retrieval snapshots, approvals, scoping packs, and cluster decisions using SQLAlchemy. SQLite supports local learning; Postgres is available for hosted deployments. See [`src/issue_triage/audit_log/store.py`](src/issue_triage/audit_log/store.py).
- Persist workflow checkpoints so pending reviews can resume.
- Keep audit records append-only and preserve reviewer identity, decisions, and reasons.

## Synthetic data and safe iteration

- Generate the fictional project corpus deterministically with [`scripts/generate_synthetic_data.py`](scripts/generate_synthetic_data.py).
- Ingest the generated sources into the configured Pinecone namespaces with [`src/issue_triage/ingestion/cli_ingest.py`](src/issue_triage/ingestion/cli_ingest.py).
- Keep all examples, prompts, logs, and demo scenarios synthetic. Do not put real client or audit data in this concept build.

## Local learning workflow

1. Configure provider keys and local database settings in `.env` using `.env.example` as the template.
2. Generate the synthetic Word and PDF source files:

   ```bash
   python scripts/generate_synthetic_data.py
   ```

3. Upsert the sources into the Pinecone index:

   ```bash
   python -m src.issue_triage.ingestion.cli_ingest
   ```

4. Start the app:

   ```bash
   streamlit run app.py
   ```

See [`README.md`](README.md) for setup and configuration details, [`docs/product_spec.md`](docs/product_spec.md) for product behavior, and [`docs/system_prompt.md`](docs/system_prompt.md) for model instructions.
