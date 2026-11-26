from schemas import AgentResponse, RiskSignal, RtoAgentState, StepTrace
from tools import (
    MOCK_ORDERS,
    apply_warehouse_action,
    call_llm_with_cascade,
    deterministic_rto_backup,
    extract_order_id,
    fetch_cod_order,
    review_rto_decision,
    score_cod_rto_risk,
)

THREAD_CHECKPOINTS: dict[str, RtoAgentState] = {}

PLANNER_SYSTEM = (
    "You are the Planner node of an Indian D2C COD RTO Pre-Dispatch Verification Agent. "
    "Output 3 short numbered steps to inspect the order, evaluate RTO risk signals, and draft the warehouse + WhatsApp action."
)

WORKER_SYSTEM = (
    "You are the Operations & Customer Verification Worker for an Indian D2C brand. "
    "Produce two clear sections:\n"
    "1) Ops & Warehouse Decision (include exact Risk Score, Risk Tier, exact Order Value in ₹, and why this action prevents RTO loss)\n"
    "2) Ready-to-Send Customer WhatsApp Message (polite Indian English, include exact Order Value in ₹ and exact ₹ prepaid discount if MEDIUM/HIGH risk).\n"
    "If Reviewer feedback is provided, fix every listed point."
)

REVIEWER_SYSTEM = (
    "You are a strict D2C Operations Reviewer. Verify that the response includes exact ₹ order value, "
    "matches the risk tier policy (never auto-dispatch HIGH risk), and includes the ₹ prepaid incentive for MEDIUM/HIGH risk. "
    "Reply 'PASS' or 'FAIL: <short reason>'."
)


def run_rto_agent(session_id: str, message: str) -> AgentResponse:
    traces: list[StepTrace] = []
    text = message.strip()
    lower = text.lower()

    order_id = extract_order_id(text)
    if not order_id and any(w in lower for w in ("all", "queue", "pending", "list", "summary", "orders")):
        lines = ["Live D2C COD Verification Queue:"]
        for oid, o in MOCK_ORDERS.items():
            r = score_cod_rto_risk(o)
            lines.append(
                f"• {oid} | {o['customer_name']} ({o['city']} {o['pincode']}) | ₹{o['order_value_inr']:,} COD | "
                f"Risk: {r['risk_score']}/100 ({r['risk_tier']}) -> {r['recommended_action']}"
            )
        lines.append("\nTap any order chip below (e.g., ORD-901, ORD-902, ORD-903) to run full agentic verification.")
        reply_text = "\n".join(lines)
        traces.append(StepTrace(stage="Tool", summary="Fetched 3 pending COD orders from D2C OMS", detail="ORD-901, ORD-902, ORD-903"))
        state = RtoAgentState(thread_id=session_id, order_id="QUEUE", customer_query=text, final_output=reply_text, status="approved")
        THREAD_CHECKPOINTS[session_id] = state
        return AgentResponse(
            session_id=session_id,
            reply=reply_text,
            order_id="QUEUE",
            risk_score=0,
            risk_tier="UNKNOWN",
            recommended_action="PENDING_ORDER_ID",
            status="approved",
            revision_count=0,
            traces=traces,
            state_snapshot=state.model_dump(),
        )

    if not order_id:
        if "high" in lower or "risky" in lower or "sneaker" in lower:
            order_id = "ORD-902"
        elif "low" in lower or "safe" in lower or "repeat" in lower:
            order_id = "ORD-901"
        elif "medium" in lower or "first" in lower or "kurta" in lower:
            order_id = "ORD-903"
        else:
            order_id = "ORD-902"

    order = fetch_cod_order(order_id)
    if not order:
        reply_text = f"Order {order_id} was not found in the demo OMS. Available sample orders: ORD-901 (Low Risk), ORD-902 (High Risk), ORD-903 (Medium Risk)."
        state = RtoAgentState(thread_id=session_id, order_id=order_id, customer_query=text, final_output=reply_text, status="escalated")
        THREAD_CHECKPOINTS[session_id] = state
        return AgentResponse(
            session_id=session_id,
            reply=reply_text,
            order_id=order_id,
            risk_score=0,
            risk_tier="UNKNOWN",
            recommended_action="PENDING_ORDER_ID",
            status="escalated",
            revision_count=0,
            traces=[StepTrace(stage="Tool", summary=f"Looked up {order_id}", detail="Order not found")],
            state_snapshot=state.model_dump(),
        )

    state = RtoAgentState(thread_id=session_id, order_id=order_id, customer_query=text, order_record=order)

    # Step 1: Planner
    llm_plan, plan_meta = call_llm_with_cascade(
        f"Verify COD order {order_id} for {order['brand']} (₹{order['order_value_inr']:,}, {order['city']} {order['pincode']}). User note: {text}",
        PLANNER_SYSTEM,
        temperature=0.1,
    )
    if llm_plan:
        state.plan = [ln.strip(" -•\t") for ln in llm_plan.splitlines() if ln.strip()][:3]
        traces.append(StepTrace(stage="Planner", summary=f"Planned 3-step verification ({plan_meta})", detail=" | ".join(state.plan)))
    else:
        state.plan = [
            f"1. Fetch {order_id} buyer & pincode RTO telemetry",
            "2. Compute weighted COD RTO score & warehouse action",
            "3. Draft & audit WhatsApp verification / prepaid UPI nudge",
        ]
        traces.append(StepTrace(stage="Planner", summary="Built deterministic verification plan", detail=" | ".join(state.plan)))
    state.status = "planned"

    # Step 2: Domain Risk Tool
    risk_result = score_cod_rto_risk(order)
    state.risk_score = risk_result["risk_score"]
    state.risk_tier = risk_result["risk_tier"]
    state.recommended_action = risk_result["recommended_action"]
    state.signals = [RiskSignal(**s) for s in risk_result["signals"]]
    state.tool_logs.append({"tool": "score_cod_rto_risk", "output": risk_result})
    traces.append(
        StepTrace(
            stage="Tool",
            summary=f"Scored {order_id}: {state.risk_score}/100 ({state.risk_tier} RISK)",
            detail=f"Action -> {state.recommended_action}",
        )
    )

    # Step 3: Worker <-> Reviewer Loop (max 2 revisions)
    while True:
        worker_prompt = (
            f"Order Details: {order}\n"
            f"RTO Risk Engine Output: {risk_result}\n"
            f"User Request: {text}\n"
            + (f"Reviewer Feedback to Fix: {state.review_feedback}\n" if state.review_feedback else "")
        )
        draft, w_meta = call_llm_with_cascade(worker_prompt, WORKER_SYSTEM, temperature=0.25)
        if draft:
            traces.append(StepTrace(stage="Worker", summary=f"Drafted ops & WhatsApp action ({w_meta})", detail=f"{len(draft)} chars"))
        else:
            draft = deterministic_rto_backup(order, risk_result, feedback=state.review_feedback)
            traces.append(StepTrace(stage="Fallback", summary="Used zero-downtime Python RTO engine", detail=w_meta))

        state.draft_message = draft
        state.status = "revised" if state.revision_count > 0 else "executed"

        det_check = review_rto_decision(order, risk_result, draft)
        if not det_check["passed"]:
            reason = "; ".join(det_check["issues"])
            state.review_passed = False
            state.review_feedback = reason
            traces.append(StepTrace(stage="Reviewer", summary="Flagged policy/INR issue — requesting revision", detail=reason))
        else:
            verdict, r_meta = call_llm_with_cascade(
                f"Order: {order}\nRisk: {risk_result}\n\nDraft:\n{draft}",
                REVIEWER_SYSTEM,
                temperature=0.0,
            )
            if verdict and verdict.upper().startswith("FAIL"):
                reason = verdict.split(":", 1)[-1].strip() or "Refine message clarity"
                state.review_passed = False
                state.review_feedback = reason
                traces.append(StepTrace(stage="Reviewer", summary=f"Requested revision ({r_meta})", detail=reason))
            else:
                state.review_passed = True
                state.review_feedback = "Policy, INR math & WhatsApp tone verified"
                traces.append(StepTrace(stage="Reviewer", summary="Approved dispatch & WhatsApp policy", detail="Guardrails passed"))

        if state.review_passed:
            state.final_output = draft
            state.status = "approved"
            break

        if state.revision_count >= state.max_revisions:
            state.final_output = f"{draft}\n\nNote (Ops Supervisor Flag): {state.review_feedback}"
            state.status = "escalated"
            break

        state.revision_count += 1

    # Step 4: Apply warehouse state update
    wh_update = apply_warehouse_action(order_id, state.recommended_action)
    state.tool_logs.append({"tool": "apply_warehouse_action", "output": wh_update})
    THREAD_CHECKPOINTS[session_id] = state

    return AgentResponse(
        session_id=session_id,
        reply=state.final_output,
        order_id=order_id,
        risk_score=state.risk_score,
        risk_tier=state.risk_tier,
        recommended_action=state.recommended_action,
        status=state.status,
        revision_count=state.revision_count,
        traces=traces,
        state_snapshot=state.model_dump(),
    )
