# Project skills and architecture guide

This is a learning guide to the synthetic V1 Issue Triage Assistant. It describes the current implementation patterns; product boundaries and contributor rules remain in [`AGENTS.md`](AGENTS.md). Product behavior is specified in [`docs/product_spec.md`](docs/product_spec.md), and model-specific instructions live in [`docs/system_prompt.md`](docs/system_prompt.md).

## Auditor-facing application

- Build the review experience in Streamlit: single-issue intake, RAU scoping, source-linked results, run-scoped chat, human decisions, run history, and approved-draft details. See [`app.py`](app.py).
- Keep the human in the loop. Auditors approve, edit, or reject issue suggestions and decide each scoping cluster with a reason. Nothing auto-closes, auto-approves, creates, or files an issue.
- Show the complete issue record when an approved-draft title is opened: original input, accepted suggestion, citations, similar issues, retrieval snapshot, and reviewer decision.
- The continuous chat is tied to a run, uses only that run's retrieved sources, displays a scrollable interaction history, and cannot change the suggestion or decision.

## Ingestion and hybrid RAG

- Load fictional issue records from generated CSV data, controls from Word documents, and policies from PDFs. See [`src/issue_triage/ingestion/corpus.py`](src/issue_triage/ingestion/corpus.py).
- Split documents into retrievable chunks while retaining source IDs, chunk IDs, and metadata for citations.
- Embed and search semantic matches in Pinecone. See [`src/issue_triage/retrieval/pinecone_store.py`](src/issue_triage/retrieval/pinecone_store.py).
- Run BM25 keyword search against the local synthetic corpus and merge semantic/keyword ranks with Reciprocal Rank Fusion. See [`src/issue_triage/retrieval/hybrid.py`](src/issue_triage/retrieval/hybrid.py).
- Apply relevant client, audit, RAU, period, and lookback filters before ranking. The duplicate candidate set is exact-audit; similar precedent may come from other audits for the same client.
- Explain semantic similarity, BM25 score, term overlap, and RRF as retrieval diagnostics only, not confidence or probability.

## Stateful graph workflows

- Use structured LangChain output for the issue triage suggestion.
- Keep retrieval, drafting, citation checks/repair, insufficient-evidence routing, and the human decision interrupt explicit in the single-issue LangGraph workflow. See [`src/issue_triage/graph/workflow.py`](src/issue_triage/graph/workflow.py).
- Keep RAU-centered retrieval, clustering, and per-cluster auditor review in the scoping graph. See [`src/issue_triage/graph/scoping.py`](src/issue_triage/graph/scoping.py) and [`src/issue_triage/scoping.py`](src/issue_triage/scoping.py).
- Validate citation chunk membership, source identity/type where required, and exact quoted text. Exact quote validation does not establish semantic support; the auditor must inspect relevance.
- A weak retrieval result is not an evidence-sufficiency judgement. Do not send unsupported drafts to the approval interrupt.

## Audit records, decisions, and memory

- Store issue inputs, run snapshots, approvals, scoping packs/decisions, and audit events using SQLAlchemy. SQLite supports local learning; Postgres is scaffolded for hosted deployment. See [`src/issue_triage/audit_log/store.py`](src/issue_triage/audit_log/store.py).
- Preserve reviewer identity and decision reason. Keep audit events append-only and durable graph checkpoints configured for pending reviews.
- SQLite-approved/edited drafts are listed in the app and expose full details through the title link.
- Optional Mem0 is scoped to auditor and synthetic client. It may retain only concise patterns derived from an approved/corrected suggestion; memory is not evidence and must never contain raw issue data, source chunks, or unapproved drafts.

## Synthetic corpus and safe iteration

- Generate the fictional corpus deterministically with [`scripts/generate_synthetic_data.py`](scripts/generate_synthetic_data.py).
- Ingest generated source documents into Pinecone with [`src/issue_triage/ingestion/cli_ingest.py`](src/issue_triage/ingestion/cli_ingest.py).
- Keep all examples, prompts, and demo inputs synthetic. Markdown files in `data/synthetic/policies/` are source documents used for corpus generation and indexing, not product documentation.
- Never use this concept build with real client or audit data until the authorization, privacy, evaluation, and deployment gates in the product specification are met.

## Local learning workflow

1. Configure provider keys and database settings in `.env`, using `.env.example` as the template.
2. Generate the synthetic Word and PDF sources:

   ```bash
   python scripts/generate_synthetic_data.py
   ```

3. Upsert the synthetic corpus:

   ```bash
   python -m src.issue_triage.ingestion.cli_ingest
   ```

4. Start Streamlit:

   ```bash
   streamlit run app.py
   ```

See [`README.md`](README.md) for configuration, [`docs/product_spec.md`](docs/product_spec.md) for behavior and deployment gates, and [`docs/system_prompt.md`](docs/system_prompt.md) for the model's evidence and oversight rules.
