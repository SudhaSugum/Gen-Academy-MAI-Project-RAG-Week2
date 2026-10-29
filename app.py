"""Streamlit review surface for the Issue Triage Assistant V1 workflow."""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

import streamlit as st
from langgraph.types import Command

from src.issue_triage.audit_log.store import AuditStore
from src.issue_triage.chatbot import answer_from_run_sources
from src.issue_triage.chat_window import render_chat_window_controls
from src.issue_triage.config import get_settings
from src.issue_triage.graph.scoping import build_scoping_graph
from src.issue_triage.graph.workflow import build_graph, citation_errors
from src.issue_triage.triage.schema import TriageSuggestion

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
st.set_page_config(page_title="Issue Triage Assistant", page_icon="🧭", layout="wide")

settings = get_settings()
store = AuditStore(settings.database_url)
store.initialize()


def current_auditor() -> str:
    auth_mode = os.getenv("AUTH_MODE", "demo").lower()
    app_env = os.getenv("APP_ENV", "development").lower()
    if auth_mode == "oidc":
        try:
            if not st.user.is_logged_in:
                st.login()
                st.stop()
            identity = st.user.get("email") or st.user.get("sub")
            if not identity:
                st.error("The identity provider did not return an email or subject claim.")
                st.stop()
            st.sidebar.write(f"Signed in: {identity}")
            if st.sidebar.button("Sign out"):
                st.logout()
                st.stop()
            return str(identity)
        except Exception as exc:
            st.error(f"OIDC sign-in is not configured. Add Streamlit [auth] settings through the deployment secret store. Details: {exc}")
            st.stop()
    if app_env == "production":
        st.error("Demo auditor selection is disabled in production. Set AUTH_MODE=oidc and configure Streamlit OIDC secrets.")
        st.stop()
    st.sidebar.caption("Development identity selector; this is not authentication.")
    return st.sidebar.text_input("Auditor ID", value="synthetic-auditor-01")


def render_claim(label: str, claim: dict, retrieved: dict[str, dict]) -> None:
    st.markdown(f"**{label}:** {claim.get('value', 'Insufficient evidence')}")
    if claim.get("rationale"):
        st.write(claim["rationale"])
    for citation in claim.get("citations", []):
        source = retrieved.get(citation.get("chunk_id"))
        if not source:
            st.error("Citation could not be resolved to a retrieved source chunk.")
            continue
        with st.expander(f"{source['ref']} · {source['title']} · {source['source_id']}"):
            st.caption(f"Chunk: {citation['chunk_id']} · Section: {source.get('section') or 'Not specified'}")
            st.markdown(f"> {citation['quote']}")


def render_source_card(item: dict) -> None:
    with st.container(border=True):
        st.caption(
            f"{item.get('ref', 'Source')} · {item.get('source_type', 'source')} · "
            f"audit {item.get('audit_id') or 'not recorded'} · "
            f"semantic similarity {item.get('semantic_score', item.get('score', 0)):.3f} · "
            f"BM25 keyword {item.get('keyword_score', 0):.3f} · "
            f"term overlap {item.get('keyword_overlap', 0):.0%} · "
            f"RRF rank {item.get('hybrid_score', 0):.5f} · {item.get('source_id', 'Unknown')}"
        )
        st.markdown(f"**{item.get('title', 'Untitled source')}**")
        st.write(item.get("text", ""))


def render_retrieval_legend() -> None:
    with st.expander("How to read retrieval signals"):
        st.markdown(
            "- **Semantic similarity:** vector match based on meaning; higher values indicate closer matches.\n"
            "- **BM25 keyword:** lexical match score from shared terms; its raw scale varies by query.\n"
            "- **Term overlap:** share of query terms found in the source.\n"
            "- **RRF rank:** Reciprocal Rank Fusion score combining the semantic and keyword result orders; higher means ranked nearer the top.\n\n"
            "These are retrieval signals, not confidence or severity scores."
        )


def render_grounded_chat_reply(payload: dict, sources: dict[str, dict]) -> None:
    if payload.get("error"):
        st.error(payload["error"])
        return
    if payload.get("insufficient_evidence") and not payload.get("claims"):
        st.info("I couldn't support an answer from this run's retrieved sources. Try asking about a specific issue, control, policy, or scoping cluster.")
    for claim in payload.get("claims", []):
        st.markdown(claim["text"])
        for citation in claim.get("citations", []):
            source = sources.get(citation.get("chunk_id"))
            if not source:
                continue
            with st.expander(f"Source · {source.get('source_id', 'Unknown')} · {source.get('title', 'Untitled')}"):
                st.caption(f"Chunk {citation['chunk_id']} · audit {source.get('audit_id') or 'not recorded'}")
                st.markdown(f"> {citation['quote']}")
    if payload.get("follow_up_question"):
        st.caption(f"To narrow this down: {payload['follow_up_question']}")


def render_run_chat(mode: str, run_id: str, sources: dict[str, Any] | list[dict[str, Any]], run_context: dict[str, Any]) -> None:
    if not st.session_state.get("chat_panel_visible", True):
        return
    panel_key = f"chat_panel_{mode}"
    body_key = f"{panel_key}_body"
    side = st.session_state.get("chat_panel_side", "Right")
    panel_container = st.container(border=True, key=panel_key)
    dock_css = {
        "Right": "top: 5.25rem; right: 1rem; bottom: 1rem; left: auto; width: min(410px, 36vw); height: calc(100vh - 6.25rem); max-height: calc(100vh - 6.25rem);",
        "Left": "top: 5.25rem; left: 1rem; bottom: 1rem; right: auto; width: min(410px, 36vw); height: calc(100vh - 6.25rem); max-height: calc(100vh - 6.25rem);",
        "Top": "top: 5.25rem; left: 1rem; right: 1rem; bottom: auto; width: auto; height: min(42vh, 430px); max-height: calc(100vh - 6.25rem);",
        "Bottom": "top: auto; left: 1rem; right: 1rem; bottom: 1rem; width: auto; height: min(42vh, 430px); max-height: calc(100vh - 6.25rem);",
    }
    position_css = f"position: fixed; {dock_css.get(side, dock_css['Right'])}"
    st.html(f"""
    <style>
      .st-key-{panel_key} {{
        {position_css}
        display: flex;
        flex-direction: column;
        overflow: hidden;
        z-index: 10000;
        padding: .75rem;
        background: rgba(255,255,255,.98);
        border: 1px solid rgba(80,95,88,.25);
        border-radius: 14px;
        box-shadow: 0 10px 36px rgba(20,35,28,.2);
      }}
      .st-key-{panel_key} > [data-testid="stVerticalBlock"] {{
        display: flex;
        flex-direction: column;
        flex: 1 1 auto;
        min-height: 0;
        overflow: hidden;
      }}
      .st-key-{panel_key} .st-key-{body_key} {{
        display: flex;
        flex: 1 1 auto;
        flex-direction: column;
        min-height: 0;
        overflow: hidden;
      }}
      .st-key-{panel_key} .st-key-{panel_key}_history {{
        flex: 1 1 auto;
        min-height: 0;
        overflow-y: auto;
        overscroll-behavior: contain;
      }}
      .st-key-{panel_key} .st-key-{panel_key}_composer {{
        flex: 0 0 auto;
        position: sticky;
        bottom: 0;
        z-index: 1;
        padding-top: .5rem;
        background: rgba(255,255,255,.98);
      }}
      @media (max-width: 760px) {{
        .st-key-{panel_key} {{
          left: 1rem;
          right: 1rem;
          width: auto;
          max-width: none;
          {'height: min(42vh, 430px);' if side in ('Top', 'Bottom') else ''}
        }}
      }}
    </style>
    """)
    with panel_container:
        render_chat_window_controls(
            panel_key=panel_key,
            body_key=body_key,
            run_key=f"{mode}_{run_id}",
            title="Issue triage chat" if mode == "triage" else "RAU scoping chat",
            side=side,
        )
        with st.container(key=body_key):
            st.markdown("### Ask about this run")
            st.caption("Ask follow-up questions in the same conversation. Answers use this run's retrieved sources and cite factual claims; chat does not change suggestions or record decisions.")
            conversations = st.session_state.setdefault("chat_conversations_by_run", {})
            messages = conversations.setdefault(run_id, [])
            if isinstance(sources, dict) and sources and all(isinstance(value, dict) and "chunk_id" in value for value in sources.values()):
                source_rows = list(sources.values())
            else:
                source_rows = [item for group in sources.values() for item in group] if isinstance(sources, dict) else sources
            source_map = {item["chunk_id"]: item for item in source_rows if item.get("chunk_id")}

            history_slot = st.container(height=360, key=f"{panel_key}_history")
            with st.container(key=f"{panel_key}_composer"):
                question = st.chat_input(
                    "Ask a follow-up about this run",
                    key=f"chat_{mode}_{run_id}",
                    submit_mode="disable",
                )
            if question:
                prior_history = list(messages)
                messages.append({"role": "user", "content": question})
                try:
                    with st.spinner("Checking this run's sources…"):
                        reply, _ = answer_from_run_sources(
                            settings,
                            question=question,
                            history=prior_history,
                            sources=sources,
                            run_context=run_context,
                        )
                    payload = reply.model_dump(mode="json")
                except Exception as exc:
                    payload = {"error": f"Chat is unavailable ({type(exc).__name__}). Your triage and review state are unchanged."}
                messages.append({"role": "assistant", "payload": payload})
                conversations[run_id] = messages[-50:]

            with history_slot:
                for message in conversations[run_id]:
                    with st.chat_message(message["role"]):
                        if message["role"] == "user":
                            st.write(message["content"])
                        else:
                            render_grounded_chat_reply(message["payload"], source_map)


auditor_id = current_auditor()
st.sidebar.subheader("Chat panel", icon=":material/chat:")
st.sidebar.toggle("Show chat panel", value=True, key="chat_panel_visible")
st.sidebar.caption("Choose a screen edge to dock the chat. You can still drag it to another position.")
st.sidebar.selectbox("Dock chat panel", ["Right", "Left", "Top", "Bottom"], key="chat_panel_side")
st.sidebar.divider()
st.sidebar.subheader("Run history", icon=":material/history:")
history_client = st.sidebar.selectbox("Synthetic client", ["synthetic-client-a", "synthetic-client-b"], key="triage_history_client")
run_rows = store.recent_runs(client_id=history_client, limit=20)
if run_rows:
    selected_run_id = st.sidebar.selectbox(
        "Audit run", [row["run_id"] for row in run_rows],
        format_func=lambda run: f"{run[:8]} · {next(row['status'] for row in run_rows if row['run_id'] == run)}",
    )
    selected_row = next(row for row in run_rows if row["run_id"] == selected_run_id)
    detail = store.run_details(selected_run_id, history_client, selected_row["audit_id"])
    if detail:
        with st.sidebar.expander("Open audit record"):
            st.json({
                "input": json.loads(detail["input_json"]),
                "retrieved_chunks": json.loads(detail["retrieved_json"]),
                "suggestion": json.loads(detail["suggestion_json"]) if detail["suggestion_json"] else None,
                "approvals": detail["approvals"],
                "events": [{"event_type": e["event_type"], "payload": json.loads(e["payload_json"]), "created_at": e["created_at"]} for e in detail["events"]],
            })
        if st.sidebar.button("Resume pending review", disabled=selected_row["status"] != "review_pending"):
            config = {"configurable": {"thread_id": selected_run_id}}
            state = build_graph(settings).get_state(config).values
            if state and state.get("review_pending"):
                st.session_state["active_review"] = {"run_id": selected_run_id, "config": config, "state": state}
                st.rerun()

st.html("""
<style>
.st-key-app_header {
  padding: 1.15rem 1.5rem .9rem;
  margin: .25rem 0 1rem;
  border: 1px solid #2d7058;
  border-radius: 1rem;
  background: linear-gradient(115deg, #173f32 0%, #236b52 62%, #387d62 100%);
  box-shadow: 0 8px 24px rgba(23, 63, 50, .12);
}
.st-key-app_header [data-testid="stCaptionContainer"] p {
  color: #d6e9df;
  font-size: .75rem;
  font-weight: 700;
  letter-spacing: .14em;
}
.st-key-app_header h1,
.st-key-app_header [data-testid="stMarkdownContainer"] p {
  color: #fff;
}
.st-key-app_header h1 { margin: .2rem 0 .35rem; }
.st-key-app_header [data-testid="stMarkdownContainer"] p { margin: 0; opacity: .9; }
</style>
""")
with st.container(key="app_header"):
    st.caption("AUDIT · V1")
    st.title("Issue triage assistant", icon=":material/assignment_turned_in:")
    st.markdown("Retrieve precedent, controls, and policy to prepare a source-linked suggestion for auditor review.")
st.warning(
    "Use synthetic data only. Do not enter real client names, issue details, or audit evidence. The development identity selector is not authentication.",
    title="Concept environment",
    icon=":material/science:",
)

pain, outcome = st.columns(2, gap="large")
with pain:
    with st.container(border=True):
        st.subheader("Today’s challenge", icon=":material/search_off:")
        st.markdown("- Similar issues get logged more than once\n- Severity and control mapping vary\n- Useful remediation is hard to find\n- Reviewers cannot see the basis")
with outcome:
    with st.container(border=True):
        st.subheader("How the assistant helps", icon=":material/manage_search:")
        st.markdown("- Finds related issues, controls, and policy\n- Drafts severity, root cause, and control suggestions\n- Links claims to exact source chunks\n- Flags likely duplicates for review")

tab_issue, tab_scope = st.tabs(["Single-issue triage", "RAU scoping"])

with tab_issue:
    with st.container(border=True):
        st.subheader("Start a new issue review", icon=":material/note_add:")
        st.caption("Duplicate screening checks this audit. Precedent comes from other audits for the same synthetic client.")
        with st.form("triage_intake"):
            issue_title = st.text_input("Issue title", placeholder="Quarterly privileged access review was missed")
            issue_description = st.text_area("Issue description", height=130, placeholder="Describe the condition, scope, period, and known impact.")
            col_a, col_b = st.columns(2)
            client_id = col_a.selectbox("Synthetic client", ["synthetic-client-a", "synthetic-client-b"], key="triage_client")
            audit_by_client = {
                "synthetic-client-a": ["synthetic-audit-iam-2026", "synthetic-audit-iam-2025"],
                "synthetic-client-b": ["synthetic-audit-finance-2026", "synthetic-audit-finance-2025"],
            }
            audit_id = col_b.selectbox("Synthetic audit", audit_by_client[client_id], key=f"triage_audit_{client_id}")
            col_c, col_d = st.columns(2)
            audit_context = col_c.text_input("Audit context", placeholder="FY2026 identity and access review")
            control_hint = col_d.text_input("Optional control hint", placeholder="AC-04 (search hint only)")
            submit = st.form_submit_button("Retrieve and draft for review", type="primary", width="stretch")

    if submit:
        if len(issue_title.strip()) < 3 or len(issue_description.strip()) < 20:
            st.warning("Provide an issue title and a fuller description.")
        elif not auditor_id.strip():
            st.warning("Auditor identity is required for the review trail.")
        else:
            run_id, issue_id = str(uuid.uuid4()), str(uuid.uuid4())
            graph = build_graph(settings)
            config = {"configurable": {"thread_id": run_id}}
            initial = {
                "run_id": run_id, "issue_id": issue_id, "issue_title": issue_title.strip(),
                "issue_description": issue_description.strip(), "client_id": client_id, "audit_id": audit_id,
                "audit_context": audit_context.strip(), "control_hint": control_hint.strip(),
                "auditor_id": auditor_id.strip(), "retrieved": {}, "memories": [], "citation_attempts": 0,
            }
            with st.status("Running the V1 triage graph…", expanded=True):
                result = graph.invoke(initial, config=config)
            current = graph.get_state(config).values or result
            store.save_run(current, model=settings.chat_model, prompt_version=settings.prompt_version)
            st.session_state["active_review"] = {"run_id": run_id, "config": config, "state": current}

    active_review = st.session_state.get("active_review")
    if active_review:
        current = active_review["state"]
        suggestion_data = current.get("suggestion")
        suggestion = TriageSuggestion.model_validate(suggestion_data) if suggestion_data else None
        retrieved_rows = current.get("retrieved", {})
        chunks = {item["chunk_id"]: item for group in retrieved_rows.values() for item in group}
        st.divider()
        left, right = st.columns([1.1, .9], gap="large")
        with left:
            st.subheader("Draft suggestion", icon=":material/assignment:")
            st.caption(f"Run {active_review['run_id']} · Model {settings.chat_model} · Prompt {settings.prompt_version}")
            if current.get("error"):
                st.warning(current["error"])
            if suggestion and current.get("review_pending"):
                render_claim("Duplicate warning", suggestion.duplicate_warning.model_dump(), chunks)
                render_claim("Suggested severity", suggestion.severity.model_dump(), chunks)
                render_claim("Root-cause category", suggestion.root_cause.model_dump(), chunks)
                render_claim("Mapped control ID", suggestion.control_mapping.model_dump(), chunks)
                render_claim("Confidence", suggestion.confidence.model_dump(), chunks)
                st.markdown("**Draft remediation steps**")
                for i, step in enumerate(suggestion.remediation_steps, 1):
                    with st.container(border=True):
                        st.markdown(f"**Step {i}**")
                        render_claim("Action", step.action.model_dump(), chunks)
                        render_claim("Owner role", step.owner_role.model_dump(), chunks)
                        render_claim("Due-date suggestion", step.due_date_suggestion.model_dump(), chunks)
                st.markdown("#### Similar past issues")
                for item in suggestion.similar_issues:
                    source = chunks.get(item.chunk_id)
                    if source:
                        relevance = source.get("hybrid_score", 0.0)
                        with st.container(border=True):
                            st.markdown(f"**{source['title']}**")
                            st.caption(f"{source.get('source_id', 'Unknown')} · audit {source.get('audit_id') or 'not recorded'} · semantic {item.similarity:.3f} · hybrid {relevance:.5f} · {item.chunk_id}")
                            st.write(f"Outcome: {item.outcome or 'Not recorded'}")
                st.markdown("#### Auditor decision")
                edited = st.text_area("Edit suggestion (JSON)", value=suggestion.model_dump_json(indent=2), height=300, key=f"approval_edit_{active_review['run_id']}")
                decision = st.radio("Decision", ["approve", "edit", "reject"], horizontal=True, key=f"approval_decision_{active_review['run_id']}")
                reason = st.text_area("Decision reason (required for rejection)", key=f"approval_reason_{active_review['run_id']}")
                if st.button("Submit human decision", type="primary", key=f"approval_submit_{active_review['run_id']}", width="stretch"):
                    if decision == "reject" and not reason.strip():
                        st.error("A rejection reason is required.")
                    else:
                        try:
                            if decision == "edit":
                                edited_suggestion = TriageSuggestion.model_validate_json(edited)
                                problems = citation_errors(edited_suggestion, retrieved_rows)
                                if problems:
                                    raise ValueError("; ".join(problems))
                            payload = {"decision": decision, "edited_json": edited, "reason": reason.strip(), "approver": auditor_id.strip()}
                            build_graph(settings).invoke(Command(resume=payload), config=active_review["config"])
                            st.session_state.pop("active_review", None)
                            st.success(f"Human decision recorded: {decision}. No issue was closed or filed.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Review could not be recorded: {exc}")
            elif current.get("insufficient_evidence"):
                retrieval_error = current.get("error", "")
                if retrieval_error.startswith("Retrieval unavailable:"):
                    st.error(retrieval_error)
                else:
                    reason = retrieval_error or "Retrieval did not produce a strong enough basis for a suggestion."
                    st.error(f"Insufficient evidence — {reason} This is not an evidence sufficiency assessment.")
            elif suggestion and current.get("review_complete"):
                st.info("This run already has a recorded human decision. Open its audit record from Run history to inspect the decision.")
        with right:
            st.subheader("Retrieved sources", icon=":material/library_books:")
            render_retrieval_legend()
            for source_type, label in (("duplicate_issues", "Exact-audit duplicate candidates"), ("past_issues", "Similar issues from other audits"), ("controls", "Controls"), ("policies", "Policies")):
                st.markdown(f"**{label}**")
                for item in retrieved_rows.get(source_type, []):
                    render_source_card(item)
        render_run_chat(
            "triage", active_review["run_id"], retrieved_rows,
            {
                "mode": "single-issue triage",
                "issue_title": current.get("issue_title", ""),
                "issue_description": current.get("issue_description", ""),
                "client_id": current.get("client_id", ""),
                "audit_id": current.get("audit_id", ""),
                "audit_context": current.get("audit_context", ""),
                "control_hint": current.get("control_hint", ""),
            },
        )
    st.subheader("Recent audit trail", icon=":material/history:")
    st.dataframe(store.recent_runs(client_id=client_id, limit=30), width="stretch", hide_index=True)

with tab_scope:
    with st.container(border=True):
        st.subheader("Plan RAU testing", icon=":material/account_tree:")
        st.caption("Scoping is centered on the RAU and can use precedent from other audits. Client, audit, control, period, RAU name, and attributes are optional refinements.")
        with st.form("scope_intake"):
            scope_client_choice = st.selectbox("Synthetic client (optional)", ["Any synthetic client", "synthetic-client-a", "synthetic-client-b"], key="scope_client")
            scope_audit_choice = st.selectbox("Audit context (optional)", ["Not specified", "synthetic-audit-iam-2026", "synthetic-audit-finance-2026"], key="scope_audit")
            rau_id = st.text_input("RAU ID", value="RAU-AC-01")
            rau_name = st.text_input("Risk assessable unit name (optional)", value="")
            period = st.text_input("Audit period (optional)", value="")
            controls_in_scope = st.text_input("Control IDs in scope (optional, comma separated)", value="")
            attributes = st.text_input("Attributes to test (optional, comma separated)", value="")
            scope_submit = st.form_submit_button("Build cited scoping pack", type="primary", width="stretch")

    if scope_submit:
        scope_client = "" if scope_client_choice == "Any synthetic client" else scope_client_choice
        scope_audit = "" if scope_audit_choice == "Not specified" else scope_audit_choice
        control_ids = list(dict.fromkeys(item.strip() for item in controls_in_scope.split(",") if item.strip()))
        scope_attributes = list(dict.fromkeys(item.strip() for item in attributes.split(",") if item.strip()))
        if not rau_id.strip():
            st.warning("Enter a RAU ID to build the scoping pack.")
        else:
            scope_run_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": scope_run_id}}
            query_parts = [f"RAU {rau_id.strip()}"]
            if rau_name.strip():
                query_parts.append(rau_name.strip())
            if period.strip():
                query_parts.append(period.strip())
            if control_ids:
                query_parts.append(f"controls: {', '.join(control_ids)}")
            if scope_attributes:
                query_parts.append(f"attributes: {', '.join(scope_attributes)}")
            scope_input = {
                "run_id": scope_run_id, "client_id": scope_client, "audit_id": scope_audit,
                "rau_id": rau_id.strip(), "rau_name": rau_name.strip(), "audit_period": period.strip(),
                "control_ids": control_ids, "attributes": scope_attributes,
                "query": "; ".join(query_parts), "auditor_id": auditor_id.strip(),
            }
            try:
                graph = build_scoping_graph(settings)
                with st.status("Retrieving and clustering RAU precedent…", expanded=True):
                    result = graph.invoke(scope_input, config=config)
                current = graph.get_state(config).values or result
                st.session_state["active_scope"] = {"run_id": scope_run_id, "config": config, "state": current}
            except Exception as exc:
                st.error(f"Scoping retrieval failed: {exc}")

    active_scope = st.session_state.get("active_scope")
    if active_scope:
        scope_state = active_scope["state"]
        pack = scope_state["pack"]
        rows = pack["rows"]
        decisions = scope_state.get("decisions", [])
        decisions_by_id = {item["cluster_id"]: item for item in decisions}
        st.divider()
        st.caption(f"RAU {pack['rau_id']} · {pack['audit_period'] or 'Period not specified'} · lookback since {pack['lookback_since']} · run {active_scope['run_id']}")
        render_retrieval_legend()
        for i, row in enumerate(rows):
            with st.container(border=True):
                st.subheader(f"{row['control_id']} · {row['attribute']}", icon=":material/verified_user:")
                priority_color = "orange" if row["priority"] == "High" else "blue" if row["priority"] == "Medium" else "gray"
                st.badge(f"{row['priority']} priority", color=priority_color)
                st.caption(f"Root cause: {row['root_cause']}")
                st.markdown(f"**Suggested action:** {row['action']}")
                st.write(row["procedure"])
                st.caption(row["priority_rationale"])
                st.write("Linked past issues: " + (", ".join(row["issue_ids"]) if row["issue_ids"] else "None retrieved — test based on inherent risk"))
                for chunk_id in row["citations"]:
                    cited = pack["citation_sources"].get(chunk_id)
                    if cited:
                        with st.expander(f"Citation · {cited['source_id']} · {cited['title']}"):
                            st.caption(
                                f"Chunk {cited['chunk_id']} · semantic similarity {cited.get('semantic_score', cited.get('score', 0)):.3f} · "
                                f"BM25 keyword {cited.get('keyword_score', 0):.3f} · term overlap {cited.get('keyword_overlap', 0):.0%} · "
                                f"RRF rank {cited.get('hybrid_score', 0):.5f}"
                            )
                            st.write(cited["text"])
                if row["cluster_id"] in decisions_by_id:
                    saved = decisions_by_id[row["cluster_id"]]
                    st.success(f"{saved['decision']} — {saved['reason']} · {saved['approver']}")
        if scope_state.get("review_pending"):
            index = scope_state["current_index"]
            row = rows[index]
            with st.container(border=True):
                st.subheader(f"Auditor decision · cluster {index + 1} of {len(rows)}", icon=":material/fact_check:")
                choice = st.radio("Decision", ["approved", "de_scoped", "escalated"], horizontal=True, key=f"scope_choice_{active_scope['run_id']}_{index}")
                why = st.text_area("Decision reason (required)", key=f"scope_reason_{active_scope['run_id']}_{index}")
                if st.button("Record decision and continue", type="primary", key=f"scope_submit_{active_scope['run_id']}_{index}", width="stretch"):
                    if not why.strip():
                        st.error("A reason is required for each cluster decision.")
                    else:
                        payload = {"cluster_id": row["cluster_id"], "decision": choice, "reason": why.strip(), "approver": auditor_id.strip()}
                        try:
                            graph = build_scoping_graph(settings)
                            result = graph.invoke(Command(resume=payload), config=active_scope["config"])
                            current = graph.get_state(active_scope["config"]).values or result
                            st.session_state["active_scope"]["state"] = current
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Cluster decision could not be recorded: {exc}")
        elif scope_state.get("review_complete"):
            st.success("All scoping rows have a recorded human decision.")
        if pack["excluded_older_issues"]:
            with st.expander(f"Excluded issues older than lookback ({len(pack['excluded_older_issues'])})"):
                for item in pack["excluded_older_issues"]:
                    st.write(f"{item['source_id']} · {item['issue_date']} · {item['title']}")
        render_run_chat(
            "scoping", active_scope["run_id"], pack["citation_sources"],
            {
                "mode": "RAU scoping",
                "client_id": scope_state.get("client_id", ""),
                "audit_id": scope_state.get("audit_id", ""),
                "rau_id": pack.get("rau_id", ""),
                "audit_period": pack.get("audit_period", ""),
                "lookback_since": pack.get("lookback_since", ""),
                "clusters": [
                    {"control_id": row["control_id"], "attribute": row["attribute"], "root_cause": row["root_cause"]}
                    for row in rows
                ],
            },
        )

    st.subheader("Saved scoping runs", icon=":material/folder_open:")
    scope_history_choice = st.selectbox("History client", ["All synthetic clients", "synthetic-client-a", "synthetic-client-b"], key="scope_history_client")
    scope_history_client = None if scope_history_choice == "All synthetic clients" else scope_history_choice
    scope_history = store.recent_scoping_runs(scope_history_client, limit=10)
    if scope_history:
        selected_scope = st.selectbox("Scoping run", [item["scope_run_id"] for item in scope_history], format_func=lambda run: f"{run[:8]} · {next(item['rau_id'] for item in scope_history if item['scope_run_id'] == run)}")
        selected_scope_meta = next(item for item in scope_history if item["scope_run_id"] == selected_scope)
        if st.button("Load or resume selected scoping run", width="stretch"):
            config = {"configurable": {"thread_id": selected_scope}}
            state = build_scoping_graph(settings).get_state(config).values
            if state:
                st.session_state["active_scope"] = {"run_id": selected_scope, "config": config, "state": state}
                st.rerun()
        details = store.scoping_details(selected_scope, scope_history_client, selected_scope_meta["audit_id"] or None)
        if details:
            with st.expander("Open saved pack and decisions"):
                st.json({"inputs": json.loads(details["input_json"]), "decisions": details["decisions"]})

st.info(
    "The assistant suggests; the auditor decides. It does not judge evidence sufficiency, approve, close, or file issues. Real client use requires SSO, tenant authorization, approved secret storage, and production database governance.",
    title="Human decision required",
    icon=":material/gavel:",
)
