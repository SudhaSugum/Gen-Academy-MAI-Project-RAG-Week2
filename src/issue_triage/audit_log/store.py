"""Portable SQL audit store. Application write APIs are append-only for runs, events, and decisions."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text


class AuditStore:
    def __init__(self, database_url: str):
        if database_url.startswith("sqlite:///"):
            db_path = database_url.removeprefix("sqlite:///")
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(database_url, connect_args={"check_same_thread": False}, pool_pre_ping=True)
        else:
            self.engine = create_engine(database_url, pool_pre_ping=True)

    def initialize(self) -> None:
        ddl = [
            "CREATE TABLE IF NOT EXISTS issues (issue_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, client_id TEXT NOT NULL, audit_id TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL, submitted_by TEXT NOT NULL, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS triage_runs (run_id TEXT PRIMARY KEY, issue_id TEXT NOT NULL, client_id TEXT NOT NULL, audit_id TEXT NOT NULL, model TEXT NOT NULL, prompt_version TEXT NOT NULL, status TEXT NOT NULL, input_json TEXT NOT NULL, retrieved_json TEXT NOT NULL, suggestion_json TEXT, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS approvals (approval_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, decision TEXT NOT NULL, edited_fields_json TEXT, final_suggestion_json TEXT, reason TEXT NOT NULL, approver TEXT NOT NULL, decided_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS scoping_runs (scope_run_id TEXT PRIMARY KEY, client_id TEXT NOT NULL, audit_id TEXT NOT NULL, rau_id TEXT NOT NULL, audit_period TEXT NOT NULL, input_json TEXT NOT NULL, pack_json TEXT NOT NULL, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS scoping_decisions (decision_id TEXT PRIMARY KEY, scope_run_id TEXT NOT NULL, cluster_id TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL, approver TEXT NOT NULL, decided_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS audit_events (event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL)",
            "CREATE INDEX IF NOT EXISTS idx_issues_tenant ON issues(client_id, audit_id)",
            "CREATE INDEX IF NOT EXISTS idx_runs_tenant_time ON triage_runs(client_id, audit_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_events_run ON audit_events(run_id, created_at)",
        ]
        with self.engine.begin() as conn:
            for statement in ddl:
                conn.execute(text(statement))
            approval_columns = {column["name"] for column in inspect(conn).get_columns("approvals")}
            if "final_suggestion_json" not in approval_columns:
                conn.execute(text("ALTER TABLE approvals ADD COLUMN final_suggestion_json TEXT"))
            if self.engine.dialect.name == "sqlite":
                for table in ("issues", "triage_runs", "scoping_runs"):
                    conn.execute(text(f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'append-only table'); END"))
                    conn.execute(text(f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'append-only table'); END"))
                conn.execute(text("CREATE TRIGGER IF NOT EXISTS approvals_no_update BEFORE UPDATE ON approvals BEGIN SELECT RAISE(ABORT, 'append-only table'); END"))
                conn.execute(text("CREATE TRIGGER IF NOT EXISTS approvals_no_delete BEFORE DELETE ON approvals BEGIN SELECT RAISE(ABORT, 'append-only table'); END"))
                conn.execute(text("CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT, 'append-only table'); END"))
                conn.execute(text("CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'append-only table'); END"))
                conn.execute(text("CREATE TRIGGER IF NOT EXISTS decisions_no_update BEFORE UPDATE ON scoping_decisions BEGIN SELECT RAISE(ABORT, 'append-only table'); END"))
                conn.execute(text("CREATE TRIGGER IF NOT EXISTS decisions_no_delete BEFORE DELETE ON scoping_decisions BEGIN SELECT RAISE(ABORT, 'append-only table'); END"))

    @staticmethod
    def _json(value: Any) -> str:
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        elif hasattr(value, "model_dump_json"):
            value = json.loads(value.model_dump_json())
        return json.dumps(value, default=str, ensure_ascii=False)

    def append_event(self, run_id: str, event_type: str, payload: Any) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("INSERT INTO audit_events VALUES (:id,:run,:type,:payload,:created)"), {
                "id": str(uuid.uuid4()), "run": run_id, "type": event_type,
                "payload": self._json(payload), "created": datetime.now(timezone.utc).isoformat(),
            })

    def save_run(self, state: dict[str, Any], model: str, prompt_version: str) -> None:
        issue = {key: state.get(key, "") for key in ("issue_title", "issue_description", "client_id", "audit_id", "audit_context", "control_hint", "auditor_id")}
        created = datetime.now(timezone.utc).isoformat()
        status = "review_pending" if state.get("review_pending") else "insufficient_evidence"
        with self.engine.begin() as conn:
            conn.execute(text("INSERT INTO issues VALUES (:id,:run,:client,:audit,:title,:description,:submitter,:created)"), {
                "id": state["issue_id"], "run": state["run_id"], "client": state["client_id"], "audit": state["audit_id"],
                "title": state["issue_title"], "description": state["issue_description"], "submitter": state["auditor_id"], "created": created,
            })
            conn.execute(text("INSERT INTO triage_runs VALUES (:run,:issue,:client,:audit,:model,:prompt,:status,:input,:retrieved,:suggestion,:created)"), {
                "run": state["run_id"], "issue": state["issue_id"], "client": state["client_id"], "audit": state["audit_id"],
                "model": model, "prompt": prompt_version, "status": status, "input": self._json(issue),
                "retrieved": self._json(state.get("retrieved", {})), "suggestion": self._json(state.get("suggestion")) if state.get("suggestion") else None, "created": created,
            })
            for event in state.get("log", []):
                conn.execute(text("INSERT INTO audit_events VALUES (:id,:run,:type,:payload,:created)"), {
                    "id": str(uuid.uuid4()), "run": state["run_id"], "type": event.get("event", "graph_event"),
                    "payload": self._json(event.get("details", {})), "created": created,
                })
            conn.execute(text("INSERT INTO audit_events VALUES (:id,:run,:type,:payload,:created)"), {
                "id": str(uuid.uuid4()), "run": state["run_id"], "type": "triage_completed",
                "payload": self._json({"model": model, "prompt_version": prompt_version, "status": status, "retrieved": state.get("retrieved", {}), "suggestion": state.get("suggestion"), "error": state.get("error"), "retrieval_latency_ms": state.get("retrieval_latency_ms"), "triage_latency_ms": state.get("triage_latency_ms"), "token_usage": state.get("token_usage", {})}), "created": created,
            })

    def record_approval(self, run_id: str, payload: dict[str, Any], suggestion: Any) -> None:
        decision = payload["decision"]
        suggestion_json = self._json(suggestion)
        with self.engine.begin() as conn:
            conn.execute(text("""INSERT INTO approvals
                (approval_id, run_id, decision, edited_fields_json, final_suggestion_json, reason, approver, decided_at)
                VALUES (:id,:run,:decision,:edited,:suggestion,:reason,:approver,:created)"""), {
                "id": str(uuid.uuid4()), "run": run_id, "decision": decision,
                "edited": suggestion_json if decision == "edit" else None,
                "suggestion": suggestion_json if decision in {"approve", "edit"} else None,
                "reason": payload.get("reason", ""), "approver": payload["approver"],
                "created": datetime.now(timezone.utc).isoformat(),
            })

    def recent_runs(self, client_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("SELECT r.run_id, r.audit_id, r.model, COALESCE((SELECT a.decision FROM approvals a WHERE a.run_id=r.run_id ORDER BY a.decided_at DESC LIMIT 1), r.status) AS status, r.created_at FROM triage_runs r WHERE r.client_id=:client ORDER BY r.created_at DESC LIMIT :limit"), {"client": client_id, "limit": limit}).mappings().all()
            return [dict(row) for row in rows]

    def approved_drafts(self, client_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Return approved or edited suggestions with their stored evidence for review."""
        statement = text("""SELECT a.approval_id, a.run_id, a.decision, a.reason,
                    a.approver, a.decided_at, i.issue_id, i.title, i.description,
                    i.submitted_by, r.client_id, r.audit_id, r.input_json,
                    COALESCE(a.final_suggestion_json, a.edited_fields_json, r.suggestion_json) AS suggestion_json,
                    r.retrieved_json
                FROM approvals a
                JOIN triage_runs r ON r.run_id=a.run_id
                JOIN issues i ON i.issue_id=r.issue_id
                WHERE r.client_id=:client
                    AND a.decision IN ('approve', 'edit')
                    AND COALESCE(a.final_suggestion_json, a.edited_fields_json, r.suggestion_json) IS NOT NULL
                ORDER BY a.decided_at DESC
                LIMIT :limit""")
        with self.engine.connect() as conn:
            rows = conn.execute(statement, {"client": client_id, "limit": limit}).mappings().all()
        result = []
        for row in rows:
            item = dict(row)
            item["input"] = json.loads(item.pop("input_json") or "{}")
            item["suggestion"] = json.loads(item.pop("suggestion_json"))
            item["retrieved"] = json.loads(item.pop("retrieved_json") or "{}")
            result.append(item)
        return result

    def recent_scoping_runs(self, client_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            if client_id:
                statement = "SELECT scope_run_id, client_id, audit_id, rau_id, audit_period, created_at FROM scoping_runs WHERE client_id=:client ORDER BY created_at DESC LIMIT :limit"
                params = {"client": client_id, "limit": limit}
            else:
                statement = "SELECT scope_run_id, client_id, audit_id, rau_id, audit_period, created_at FROM scoping_runs ORDER BY created_at DESC LIMIT :limit"
                params = {"limit": limit}
            rows = conn.execute(text(statement), params).mappings().all()
            return [dict(row) for row in rows]

    def scoping_details(self, scope_run_id: str, client_id: str | None = None, audit_id: str | None = None) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            filters = ["scope_run_id=:run"]
            params: dict[str, Any] = {"run": scope_run_id}
            if client_id:
                filters.append("client_id=:client")
                params["client"] = client_id
            if audit_id:
                filters.append("audit_id=:audit")
                params["audit"] = audit_id
            row = conn.execute(text(f"SELECT * FROM scoping_runs WHERE {' AND '.join(filters)}"), params).mappings().first()
            if not row:
                return None
            result = dict(row)
            result["decisions"] = [dict(item) for item in conn.execute(text("SELECT cluster_id,decision,reason,approver,decided_at FROM scoping_decisions WHERE scope_run_id=:run ORDER BY decided_at"), {"run": scope_run_id}).mappings().all()]
            return result

    def run_details(self, run_id: str, client_id: str, audit_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM triage_runs WHERE run_id=:run AND client_id=:client AND audit_id=:audit"), {"run": run_id, "client": client_id, "audit": audit_id}).mappings().first()
            if not row:
                return None
            details = dict(row)
            details["events"] = [dict(item) for item in conn.execute(text("SELECT event_type,payload_json,created_at FROM audit_events WHERE run_id=:run ORDER BY created_at"), {"run": run_id}).mappings().all()]
            details["approvals"] = [dict(item) for item in conn.execute(text("SELECT decision,edited_fields_json,final_suggestion_json,reason,approver,decided_at FROM approvals WHERE run_id=:run"), {"run": run_id}).mappings().all()]
            return details

    def save_scoping_run(self, scope_run_id: str, client_id: str, audit_id: str, rau_id: str, period: str, inputs: Any, pack: Any) -> None:
        created = datetime.now(timezone.utc).isoformat()
        with self.engine.begin() as conn:
            conn.execute(text("INSERT INTO scoping_runs VALUES (:id,:client,:audit,:rau,:period,:inputs,:pack,:created)"), {
                "id": scope_run_id, "client": client_id, "audit": audit_id, "rau": rau_id, "period": period,
                "inputs": self._json(inputs), "pack": self._json(pack), "created": created,
            })
        self.append_event(scope_run_id, "scoping_pack_created", {"client_id": client_id, "audit_id": audit_id, "rau_id": rau_id, "pack": pack})

    def record_scoping_decision(self, scope_run_id: str, cluster_id: str, decision: str, reason: str, approver: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("INSERT INTO scoping_decisions VALUES (:id,:run,:cluster,:decision,:reason,:approver,:created)"), {
                "id": str(uuid.uuid4()), "run": scope_run_id, "cluster": cluster_id, "decision": decision,
                "reason": reason, "approver": approver, "created": datetime.now(timezone.utc).isoformat(),
            })
        self.append_event(scope_run_id, "scoping_cluster_decision", {"cluster_id": cluster_id, "decision": decision, "reason": reason, "approver": approver})
