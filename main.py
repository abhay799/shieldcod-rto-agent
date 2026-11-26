import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

load_dotenv()

from agent import THREAD_CHECKPOINTS, run_rto_agent  # noqa: E402
from schemas import ChatRequest  # noqa: E402
from tools import MOCK_ORDERS  # noqa: E402

app = FastAPI(title="ShieldCOD AI — D2C COD RTO & Pre-Dispatch Verification Agent")


@app.get("/health")
async def health():
    return {
        "status": "running",
        "agent": "ShieldCOD D2C RTO Verification Agent",
        "key_configured": bool(os.getenv("GEMINI_API_KEY")),
        "active_threads": len(THREAD_CHECKPOINTS),
    }


@app.get("/api/orders")
async def list_orders():
    return {"orders": list(MOCK_ORDERS.values())}


@app.get("/api/state/{session_id}")
async def get_state(session_id: str):
    state = THREAD_CHECKPOINTS.get(session_id)
    if not state:
        return JSONResponse(status_code=404, content={"error": "Session not found"})
    return state.model_dump()


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    if not req.message.strip():
        return JSONResponse(status_code=400, content={"error": "Message cannot be empty"})
    result = run_rto_agent(session_id=req.session_id, message=req.message)
    return result.model_dump()


@app.get("/", response_class=HTMLResponse)
async def index_ui():
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>ShieldCOD AI — D2C COD RTO Pre-Dispatch Agent</title>
  <style>
    :root { --bg:#090d16; --card:#111827; --border:#1f2937; --text:#f8fafc; --muted:#94a3b8; --accent:#2563eb; --ok:#10b981; --warn:#f59e0b; --bad:#ef4444; }
    * { box-sizing:border-box; margin:0; padding:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
    body { background:var(--bg); color:var(--text); display:flex; justify-content:center; height:100dvh; }
    .app { width:100%; max-width:620px; background:var(--card); display:flex; flex-direction:column; height:100dvh; border-left:1px solid var(--border); border-right:1px solid var(--border); }
    .hdr { padding:13px 16px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; gap:8px; }
    .hdr h1 { font-size:15px; font-weight:800; display:flex; align-items:center; gap:7px; }
    .pill { font-size:10px; background:rgba(16,185,129,0.16); color:#34d399; padding:2px 7px; border-radius:999px; border:1px solid rgba(16,185,129,0.35); }
    .hdr p { font-size:11px; color:var(--muted); margin-top:2px; }
    .hdr-btns { display:flex; gap:6px; }
    .btn-sm { background:#1e293b; color:#e2e8f0; border:1px solid #334155; border-radius:8px; padding:6px 9px; font-size:11.5px; cursor:pointer; }
    .msgs { flex:1; overflow-y:auto; padding:14px; display:flex; flex-direction:column; gap:12px; }
    .msg { max-width:94%; padding:12px 14px; border-radius:12px; font-size:13.5px; line-height:1.52; white-space:pre-wrap; }
    .msg.user { align-self:flex-end; background:var(--accent); color:#fff; }
    .msg.bot { align-self:flex-start; background:#0b1220; border:1px solid var(--border); }
    .risk-bar { display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin-bottom:8px; }
    .r-badge { font-size:11px; font-weight:800; padding:3px 8px; border-radius:6px; }
    .r-HIGH { background:rgba(239,68,68,0.18); color:#f87171; border:1px solid rgba(239,68,68,0.4); }
    .r-MEDIUM { background:rgba(245,158,11,0.18); color:#fbbf24; border:1px solid rgba(245,158,11,0.4); }
    .r-LOW { background:rgba(16,185,129,0.18); color:#34d399; border:1px solid rgba(16,185,129,0.4); }
    .r-UNKNOWN { background:#1e293b; color:#cbd5e1; }
    .trace-box { background:#131c31; border:1px solid #263554; border-radius:8px; padding:8px 10px; margin-bottom:8px; font-size:11.5px; color:#cbd5e1; }
    .trace-row { margin:3px 0; }
    .st-tag { display:inline-block; font-size:10px; font-weight:700; padding:1px 6px; border-radius:4px; margin-right:6px; background:rgba(59,130,246,0.22); color:#93c5fd; }
    .chips { display:flex; gap:6px; overflow-x:auto; padding:8px 12px; border-top:1px solid var(--border); background:#0b1220; scrollbar-width:none; }
    .chips::-webkit-scrollbar { display:none; }
    .chip { flex-shrink:0; background:#1e293b; color:#e2e8f0; border:1px solid #334155; border-radius:999px; padding:6px 11px; font-size:11.5px; cursor:pointer; }
    .bar { display:flex; gap:8px; padding:10px 12px; border-top:1px solid var(--border); background:#0b1220; }
    .bar input { flex:1; background:#111827; color:#fff; border:1px solid #334155; border-radius:10px; padding:10px 12px; font-size:14px; outline:none; }
    .bar button { background:var(--accent); color:#fff; border:none; border-radius:10px; padding:0 16px; font-weight:600; cursor:pointer; }
    .modal { position:fixed; inset:0; background:rgba(0,0,0,0.68); display:none; align-items:center; justify-content:center; padding:14px; z-index:50; }
    .modal-box { background:#0f172a; border:1px solid var(--border); border-radius:12px; padding:16px; width:100%; max-width:560px; max-height:82vh; overflow-y:auto; }
    pre { font-size:11.5px; color:#a7f3d0; white-space:pre-wrap; word-break:break-word; margin-top:8px; }
  </style>
</head>
<body>
  <div class="app">
    <div class="hdr">
      <div>
        <h1>ShieldCOD AI <span class="pill">Category 2 &bull; Agent #1</span></h1>
        <p>D2C COD RTO Risk &amp; Pre-Dispatch Verification Agent</p>
      </div>
      <div class="hdr-btns">
        <button class="btn-sm" onclick="openOrders()">OMS Orders</button>
        <button class="btn-sm" onclick="openState()">Agent State</button>
      </div>
    </div>

    <div class="msgs" id="msgs">
      <div class="msg bot"><b>ShieldCOD Pre-Dispatch Agent Ready.</b>
Indian D2C brands lose ₹120–₹180 per Return-to-Origin (RTO) shipment on unverified COD orders. Tap a sample COD order below to watch the <b>Planner &rarr; Risk Tool &rarr; Worker &rarr; Reviewer</b> loop score RTO risk, hold risky shipments, and draft a prepaid UPI discount nudge.</div>
    </div>

    <div class="chips">
      <button class="chip" onclick="sendPreset('Verify COD order ORD-902 before warehouse dispatch')">1. High-Risk COD (ORD-902 ₹3,499)</button>
      <button class="chip" onclick="sendPreset('Verify first-time COD order ORD-903 and draft prepaid UPI nudge')">2. Medium-Risk COD (ORD-903 ₹2,199)</button>
      <button class="chip" onclick="sendPreset('Verify repeat customer COD order ORD-901')">3. Low-Risk Repeat (ORD-901 ₹1,299)</button>
      <button class="chip" onclick="sendPreset('Show all pending COD orders in the dispatch queue')">4. Full COD Queue</button>
    </div>

    <form class="bar" onsubmit="onSubmit(event)">
      <input id="inp" type="text" placeholder="Type order ID (e.g., Verify ORD-902)..." autocomplete="off" required />
      <button type="submit">Verify</button>
    </form>
  </div>

  <div class="modal" id="modal" onclick="if(event.target===this)this.style.display='none'">
    <div class="modal-box">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <strong id="modalTitle">Inspector</strong>
        <button class="btn-sm" onclick="document.getElementById('modal').style.display='none'">Close</button>
      </div>
      <pre id="modalBody">Loading...</pre>
    </div>
  </div>

  <script>
    const sessionId = 'rto_' + Math.random().toString(36).slice(2, 9);
    const msgs = document.getElementById('msgs');
    const inp = document.getElementById('inp');

    function addBubble(role, text, data = null) {
      const wrap = document.createElement('div');
      wrap.className = 'msg ' + role;

      if (role === 'bot' && data) {
        if (data.order_id && data.order_id !== 'QUEUE') {
          const rBar = document.createElement('div');
          rBar.className = 'risk-bar';
          const badge = document.createElement('span');
          badge.className = 'r-badge r-' + (data.risk_tier || 'UNKNOWN');
          badge.textContent = `${data.order_id} • ${data.risk_tier} RISK (${data.risk_score}/100)`;
          const act = document.createElement('span');
          act.className = 'r-badge r-UNKNOWN';
          act.textContent = data.recommended_action;
          rBar.appendChild(badge);
          rBar.appendChild(act);
          wrap.appendChild(rBar);
        }

        if (data.traces && data.traces.length) {
          const tBox = document.createElement('div');
          tBox.className = 'trace-box';
          const head = document.createElement('div');
          head.style.fontWeight = '700';
          head.style.marginBottom = '4px';
          head.textContent = `Execution Trace (${data.status} | revisions: ${data.revision_count})`;
          tBox.appendChild(head);

          data.traces.forEach(t => {
            const row = document.createElement('div');
            row.className = 'trace-row';
            const tag = document.createElement('span');
            tag.className = 'st-tag';
            tag.textContent = t.stage;
            row.appendChild(tag);
            row.appendChild(document.createTextNode(t.summary + (t.detail ? ` — ${t.detail}` : '')));
            tBox.appendChild(row);
          });
          wrap.appendChild(tBox);
        }
      }

      const body = document.createElement('div');
      body.textContent = text;
      wrap.appendChild(body);
      msgs.appendChild(wrap);
      msgs.scrollTop = msgs.scrollHeight;
      return wrap;
    }

    function sendPreset(txt) {
      inp.value = txt;
      onSubmit(new Event('submit'));
    }

    async function onSubmit(e) {
      e.preventDefault();
      const text = inp.value.trim();
      if (!text) return;
      inp.value = '';
      addBubble('user', text);
      const loading = addBubble('bot', 'Running Planner -> RTO Risk Engine -> Worker -> Reviewer...');

      try {
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sessionId, message: text })
        });
        const data = await res.json();
        loading.remove();
        addBubble('bot', data.reply, data);
      } catch (err) {
        loading.textContent = 'Request failed. Check server logs.';
      }
    }

    async function openState() {
      document.getElementById('modalTitle').textContent = 'Checkpointed RtoAgentState';
      document.getElementById('modal').style.display = 'flex';
      const res = await fetch('/api/state/' + encodeURIComponent(sessionId));
      const data = await res.json();
      document.getElementById('modalBody').textContent = JSON.stringify(data, null, 2);
    }

    async function openOrders() {
      document.getElementById('modalTitle').textContent = 'Live D2C OMS COD Orders';
      document.getElementById('modal').style.display = 'flex';
      const res = await fetch('/api/orders');
      const data = await res.json();
      document.getElementById('modalBody').textContent = JSON.stringify(data, null, 2);
    }
  </script>
</body>
</html>"""
