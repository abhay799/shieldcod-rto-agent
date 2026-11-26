import os
import re
import time
from typing import Any
from google import genai
from google.genai import types

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PRIMARY_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
FALLBACK_MODELS = list(dict.fromkeys([PRIMARY_MODEL, "gemini-3.8-flash-lite"]))

_client: genai.Client | None = None

# Realistic Indian D2C COD Order Database (Mutable in-memory ledger for live demo actions)
MOCK_ORDERS: dict[str, dict[str, Any]] = {
    "ORD-901": {
        "order_id": "ORD-901",
        "brand": "KayaVeda Essentials",
        "customer_name": "Rohan Sharma",
        "phone": "+91-98765-41210",
        "city": "Bengaluru",
        "pincode": "560102",
        "pincode_rto_rate_pct": 11,
        "item": "Ayurvedic Hair & Beard Care Combo",
        "order_value_inr": 1299,
        "payment_mode": "COD",
        "prior_orders": 4,
        "prior_rto_count": 0,
        "address_quality": "COMPLETE_LANDMARK",
        "order_hour_ist": 14,
        "dispatch_status": "PENDING_VERIFICATION",
        "prepaid_discount_inr": 100,
    },
    "ORD-902": {
        "order_id": "ORD-902",
        "brand": "UrbanStride Sneakers",
        "customer_name": "Aman Verma",
        "phone": "+91-91234-88901",
        "city": "Kanpur",
        "pincode": "208001",
        "pincode_rto_rate_pct": 34,
        "item": "Chunky Street Sneakers (Size 9)",
        "order_value_inr": 3499,
        "payment_mode": "COD",
        "prior_orders": 2,
        "prior_rto_count": 1,
        "address_quality": "MISSING_HOUSE_NO",
        "order_hour_ist": 2,
        "dispatch_status": "PENDING_VERIFICATION",
        "prepaid_discount_inr": 200,
    },
    "ORD-903": {
        "order_id": "ORD-903",
        "brand": "LoomCraft Ethnic",
        "customer_name": "Priya Nair",
        "phone": "+91-99001-22345",
        "city": "Jaipur",
        "pincode": "302017",
        "pincode_rto_rate_pct": 26,
        "item": "Festive Chanderi Kurta Set",
        "order_value_inr": 2199,
        "payment_mode": "COD",
        "prior_orders": 0,
        "prior_rto_count": 0,
        "address_quality": "COMPLETE_LANDMARK",
        "order_hour_ist": 21,
        "dispatch_status": "PENDING_VERIFICATION",
        "prepaid_discount_inr": 150,
    },
}


def get_genai_client() -> genai.Client | None:
    global _client
    if not GEMINI_API_KEY:
        return None
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def extract_order_id(text: str) -> str | None:
    match = re.search(r"\bORD[-_ ]?(\d{3,5})\b", text, re.IGNORECASE)
    if match:
        return f"ORD-{match.group(1)}"
    return None


def fetch_cod_order(order_id: str) -> dict[str, Any] | None:
    return MOCK_ORDERS.get(order_id.upper())


def score_cod_rto_risk(order: dict[str, Any]) -> dict[str, Any]:
    """Deterministic Indian D2C COD RTO risk engine (0-100 scale)."""
    score = 10
    signals: list[dict[str, Any]] = []

    rto_pct = int(order.get("pincode_rto_rate_pct", 18))
    if rto_pct >= 30:
        score += 28
        signals.append({"factor": "High-RTO Pincode Zone", "points": 28, "detail": f"Pincode {order['pincode']} ({order['city']}) historical RTO is {rto_pct}%."})
    elif rto_pct >= 22:
        score += 15
        signals.append({"factor": "Moderate-RTO Pincode", "points": 15, "detail": f"Pincode {order['pincode']} historical RTO is {rto_pct}%."})

    prior_rto = int(order.get("prior_rto_count", 0))
    prior_orders = int(order.get("prior_orders", 0))
    if prior_rto > 0:
        pts = min(35, prior_rto * 25)
        score += pts
        signals.append({"factor": "Repeat COD Return History", "points": pts, "detail": f"{prior_rto} past RTO out of {prior_orders} total orders."})
    elif prior_orders == 0:
        score += 12
        signals.append({"factor": "First-Time COD Buyer", "points": 12, "detail": "No prior delivered order history on phone number."})
    else:
        score = max(5, score - 8)
        signals.append({"factor": "Trusted Repeat Buyer", "points": -8, "detail": f"{prior_orders} delivered orders with 0 RTO."})

    if order.get("address_quality") != "COMPLETE_LANDMARK":
        score += 20
        signals.append({"factor": "Incomplete Address", "points": 20, "detail": f"Address flag: {order.get('address_quality')} (high courier NDR risk)."})

    val = int(order.get("order_value_inr", 0))
    if val >= 3000:
        score += 15
        signals.append({"factor": "High-Ticket COD Exposure", "points": 15, "detail": f"Order value ₹{val:,} carries ~₹140 forward+reverse shipping loss."})

    hr = int(order.get("order_hour_ist", 12))
    if 0 <= hr <= 4:
        score += 10
        signals.append({"factor": "Late-Night Impulse Order", "points": 10, "detail": f"Placed at {hr:02d}:00 IST (higher morning cancellation rate)."})

    score = max(0, min(100, score))

    if score >= 65:
        tier = "HIGH"
        action = "HOLD_&_AGENT_CALL_OR_PARTIAL_COD"
    elif score >= 35:
        tier = "MEDIUM"
        action = "WHATSAPP_CONFIRM_&_PREPAID_NUDGE"
    else:
        tier = "LOW"
        action = "AUTO_DISPATCH"

    return {
        "risk_score": score,
        "risk_tier": tier,
        "recommended_action": action,
        "signals": signals,
    }


def apply_warehouse_action(order_id: str, action: str) -> dict[str, Any]:
    """Mutate order dispatch status in the live demo ledger."""
    order = MOCK_ORDERS.get(order_id)
    if not order:
        return {"updated": False}
    status_map = {
        "AUTO_DISPATCH": "APPROVED_FOR_MANIFEST",
        "WHATSAPP_CONFIRM_&_PREPAID_NUDGE": "WHATSAPP_VERIFICATION_SENT",
        "HOLD_&_AGENT_CALL_OR_PARTIAL_COD": "HELD_FOR_IVR_&_UPI_DEPOSIT",
    }
    order["dispatch_status"] = status_map.get(action, "REVIEWED")
    return {"updated": True, "order_id": order_id, "dispatch_status": order["dispatch_status"]}


def review_rto_decision(order: dict[str, Any], risk_result: dict[str, Any], draft: str) -> dict[str, Any]:
    """Deterministic Reviewer guardrail checking policy alignment and INR numbers."""
    issues: list[str] = []
    tier = risk_result["risk_tier"]
    val = int(order.get("order_value_inr", 0))
    disc = int(order.get("prepaid_discount_inr", 100))

    if f"₹{val:,}" not in draft and str(val) not in draft:
        issues.append(f"Include exact order value ₹{val:,} in the response.")

    if tier == "HIGH" and any(w in draft.lower() for w in ("auto-dispatch immediately", "ship right away without")):
        issues.append("Policy violation: HIGH risk COD order cannot be auto-dispatched without call/partial UPI confirmation.")

    if tier in ("MEDIUM", "HIGH") and str(disc) not in draft:
        issues.append(f"Mention the ₹{disc} prepaid UPI incentive to convert COD to prepaid.")

    if len(draft.strip()) < 90:
        issues.append("Draft is too brief; include both Ops Recommendation and ready-to-send Customer WhatsApp message.")

    return {"passed": len(issues) == 0, "issues": issues}


def call_llm_with_cascade(prompt: str, system_instruction: str, temperature: float = 0.2) -> tuple[str | None, str]:
    client = get_genai_client()
    if client is None:
        return None, "GEMINI_API_KEY missing"

    last_err = ""
    for model_name in FALLBACK_MODELS:
        for attempt in range(2):
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=temperature,
                    ),
                )
                text = (resp.text or "").strip()
                if text:
                    return text, model_name
            except Exception as exc:
                last_err = str(exc)
                if any(k in last_err for k in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED")) and attempt == 0:
                    time.sleep(1.2)
                    continue
                break
    return None, last_err or "LLM unavailable"


def deterministic_rto_backup(order: dict[str, Any], risk_result: dict[str, Any], feedback: str = "") -> str:
    """Zero-downtime fallback response if Gemini API has transient 503/429 spikes."""
    val = int(order["order_value_inr"])
    disc = int(order["prepaid_discount_inr"])
    net_prepaid = val - disc
    tier = risk_result["risk_tier"]
    score = risk_result["risk_score"]
    action = risk_result["recommended_action"]
    reasons = "; ".join(s["detail"] for s in risk_result["signals"])

    if tier == "LOW":
        wa_msg = (
            f"Hi {order['customer_name']}, thank you for ordering {order['item']} (₹{val:,}) from {order['brand']}! "
            f"Your COD order {order['order_id']} is verified and being packed for dispatch to {order['city']} ({order['pincode']})."
        )
    elif tier == "MEDIUM":
        wa_msg = (
            f"Hi {order['customer_name']}, please reply YES to confirm your COD order {order['order_id']} for {order['item']} (₹{val:,}) "
            f"to {order['city']} ({order['pincode']}). Or pay via UPI now to get ₹{disc} instant discount (pay only ₹{net_prepaid:,}) + priority dispatch!"
        )
    else:
        wa_msg = (
            f"Hi {order['customer_name']}, your COD order {order['order_id']} ({order['item']}, ₹{val:,}) is on pre-dispatch hold due to incomplete address details. "
            f"Please share your full house/flat number & landmark, or pay ₹{disc} token / full UPI to get ₹{disc} OFF (₹{net_prepaid:,}) for immediate dispatch."
        )

    rev_line = f"\n• Reviewer Revision Applied: {feedback}" if feedback else ""
    return (
        f"COD RTO Risk Assessment — {order['order_id']} ({order['brand']})\n"
        f"• Risk Score: {score}/100 ({tier} RISK) | Order Value: ₹{val:,}\n"
        f"• Warehouse Action: {action}\n"
        f"• Key Signals: {reasons}{rev_line}\n\n"
        f"Ready-to-Send Customer WhatsApp Message:\n\"{wa_msg}\""
    )
