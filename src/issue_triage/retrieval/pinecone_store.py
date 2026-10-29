"""Pinecone access wrapper. All knowledge access passes through this module."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore

from ..config import Settings
from ..ingestion.corpus import build_documents
from .hybrid import fuse_rankings, keyword_search

logger = logging.getLogger(__name__)


class PineconeRetriever:
    SOURCE_NAMESPACES = {"past_issues": "past_issues", "controls": "controls", "policies": "policies"}

    def __init__(self, settings: Settings):
        if not settings.pinecone_api_key or not settings.openai_api_key:
            raise RuntimeError("PINECONE_API_KEY and OPENAI_API_KEY must be set in the environment.")
        self.settings = settings
        self.embeddings = OpenAIEmbeddings(
            model=settings.embedding_model, api_key=settings.openai_api_key,
            dimensions=settings.embedding_dimensions,
        )
        # BM25 corpus is loaded from the same generated synthetic fixtures used for ingestion.
        self.local_corpus = build_documents()

    def _search(self, source_type: str, query: str, k: int, metadata_filter: dict[str, Any]) -> list[dict[str, Any]]:
        store = PineconeVectorStore(index_name=self.settings.pinecone_index, embedding=self.embeddings, namespace=source_type)
        last_error = None
        for attempt in range(2):
            try:
                hits = store.similarity_search_with_score(query, k=max(k * 2, k), filter=metadata_filter)
                result = []
                for doc, score in hits:
                    meta = doc.metadata
                    result.append({
                        "source_type": source_type, "source_id": meta.get("doc_id", "unknown"),
                        "chunk_id": meta.get("chunk_id", "unknown"), "title": meta.get("title", "Untitled source"),
                        "section": meta.get("section", ""), "text": doc.page_content,
                        "audit_id": meta.get("audit_id", ""),
                        "score": float(score), "semantic_score": float(score), "outcome": meta.get("outcome", ""),
                        "severity": meta.get("final_severity", meta.get("severity", "")), "root_cause": meta.get("root_cause", ""),
                        "control_id": meta.get("control_id", ""), "status": meta.get("status", ""),
                        "issue_date": meta.get("issue_date", ""), "closure_date": meta.get("closure_date", ""),
                        "rau_id": meta.get("rau_id", ""), "attribute": meta.get("attribute", ""),
                        "control_version": meta.get("control_version", ""), "source": meta.get("source", source_type),
                    })
                lexical = keyword_search(self.local_corpus.get(source_type, []), query, max(k * 2, k), metadata_filter)
                return fuse_rankings(result, lexical, query, k)
            except Exception as exc:
                last_error = exc
                # Pinecone namespaces are created by the first upsert. A newly created
                # index therefore returns 404 for each not-yet-ingested source namespace.
                # Treat that condition as an empty corpus so the graph can produce its
                # explicit insufficient-evidence state; continue surfacing other failures.
                if "namespace not found" in str(exc).casefold():
                    logger.warning(
                        "Pinecone namespace %s is not initialized; run synthetic ingestion for index %s",
                        source_type, self.settings.pinecone_index,
                    )
                    lexical = keyword_search(self.local_corpus.get(source_type, []), query, k, metadata_filter)
                    return fuse_rankings([], lexical, query, k)
                if attempt == 0:
                    time.sleep(.4)
        raise RuntimeError(f"Pinecone {source_type} retrieval failed: {last_error}") from last_error

    def retrieve(self, *, query: str, client_id: str, audit_id: str, control_hint: str = "") -> dict[str, list[dict[str, Any]]]:
        # Drafting precedents come from other audits for the same client.
        # Duplicate candidates remain restricted to the exact audit being reviewed.
        client_filter = {"client_id": {"$eq": client_id}}
        duplicate_filter = {**client_filter, "audit_id": {"$eq": audit_id}}
        precedent_filter = {**client_filter, "audit_id": {"$ne": audit_id}}
        client_library_filter = client_filter
        control_query = f"{query}\nAuditor control hint: {control_hint}" if control_hint else query
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                "past_issues": pool.submit(self._search, "past_issues", query, 8, precedent_filter),
                "duplicate_issues": pool.submit(self._search, "past_issues", query, 8, duplicate_filter),
                "controls": pool.submit(self._search, "controls", control_query, 3, client_library_filter),
                "policies": pool.submit(self._search, "policies", query, 3, client_library_filter),
            }
            return {name: future.result() for name, future in futures.items()}

    def retrieve_scoping(self, *, query: str, client_id: str = "", audit_id: str = "", rau_id: str, control_ids: list[str] | None = None, since: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        # RAU is the required primary filter. Client and control narrow the
        # search when supplied; audit is context only so other audits remain usable.
        since_ordinal = int(since.replace("-", ""))
        controls = list(dict.fromkeys(control_ids or []))
        base_filters: dict[str, Any] = {"rau_id": {"$eq": rau_id}}
        if client_id:
            base_filters["client_id"] = {"$eq": client_id}
        control_filters = [
            {**base_filters, "control_id": {"$eq": control_id}} for control_id in controls
        ] or [base_filters]
        issues = []
        excluded = []
        for filters in control_filters:
            recent_filter = {**filters, "issue_date_ordinal": {"$gte": since_ordinal}}
            older_filter = {**filters, "issue_date_ordinal": {"$lt": since_ordinal}}
            issues.extend(self._search("past_issues", query, 20, recent_filter))
            excluded.extend(self._search("past_issues", query, 100, older_filter))
        return issues, excluded

    def retrieve_scope_controls(self, *, query: str, client_id: str = "", audit_id: str = "", rau_id: str, control_ids: list[str] | None = None) -> list[dict[str, Any]]:
        results = []
        filters: dict[str, Any] = {"rau_id": {"$eq": rau_id}}
        if client_id:
            filters["client_id"] = {"$eq": client_id}
        controls = list(dict.fromkeys(control_ids or []))
        if controls:
            for control_id in controls:
                results.extend(self._search("controls", f"{query} {control_id}", 3, {**filters, "control_id": {"$eq": control_id}}))
        else:
            results.extend(self._search("controls", query, 30, filters))
        return list({item["chunk_id"]: item for item in results}.values())

    def retrieve_scope_policies(self, *, query: str, client_id: str = "") -> list[dict[str, Any]]:
        """Include the policy library, optionally limited to one synthetic client."""
        filters = {"client_id": {"$eq": client_id}} if client_id else {}
        results = self._search("policies", query, 20, filters)
        # Older fixture builds used lower-case policy chunk IDs. Collapse those
        # stale IDs with the current IDs so the chat lists each policy once.
        unique: dict[str, dict[str, Any]] = {}
        for item in results:
            key = item.get("source_id", item["chunk_id"]).casefold()
            if key not in unique or item.get("hybrid_score", 0) > unique[key].get("hybrid_score", 0):
                unique[key] = item
        return list(unique.values())
