from typing import Any, Literal
from pydantic import BaseModel, Field


class RiskSignal(BaseModel):
    factor: str
    points: int
    detail: str


class RtoAgentState(BaseModel):
    """Structured state for the D2C COD RTO & Pre-Dispatch Verification Agent."""

    thread_id: str
    order_id: str
    customer_query: str
    order_record: dict[str, Any] = Field(default_factory=dict)
    plan: list[str] = Field(default_factory=list)
    risk_score: int = 0
    risk_tier: Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"] = "UNKNOWN"
    signals: list[RiskSignal] = Field(default_factory=list)
    tool_logs: list[dict[str, Any]] = Field(default_factory=list)
    recommended_action: Literal[
        "AUTO_DISPATCH",
        "WHATSAPP_CONFIRM_&_PREPAID_NUDGE",
        "HOLD_&_AGENT_CALL_OR_PARTIAL_COD",
        "PENDING_ORDER_ID",
    ] = "PENDING_ORDER_ID"
    draft_message: str = ""
    review_passed: bool = False
    review_feedback: str = ""
    revision_count: int = 0
    max_revisions: int = 2
    final_output: str = ""
    status: Literal["planned", "executed", "revised", "approved", "escalated"] = "planned"


class ChatRequest(BaseModel):
    session_id: str
    message: str


class StepTrace(BaseModel):
    stage: Literal["Planner", "Tool", "Worker", "Reviewer", "Fallback"]
    summary: str
    detail: str = ""


class AgentResponse(BaseModel):
    session_id: str
    reply: str
    order_id: str
    risk_score: int
    risk_tier: str
    recommended_action: str
    status: str
    revision_count: int
    traces: list[StepTrace]
    state_snapshot: dict[str, Any]
