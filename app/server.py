"""FastAPI app — AgentBase liveness probe + a test shim for the chat core.

The /health endpoint is tied to the zlapi listener's liveness: if the listener
thread dies, /health returns 503 so AgentBase's probe restarts the container
(advisor trap #3 — silent listener death while health stays green).
"""
import os
import threading
import time

from fastapi import FastAPI, WebSocket
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                               Response, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent_runner, llm, state

app = FastAPI(title="Zalo AI Bot")
_HERE = os.path.dirname(os.path.abspath(__file__))
_LIVE_HTML = os.path.join(_HERE, "live.html")
# Vendored noVNC client (ES modules) — served locally, NOT from a CDN (a demo's live view
# must not depend on the venue Wi-Fi reaching jsdelivr). live.html imports /novnc/core/rfb.js.
_NOVNC_DIR = os.path.join(_HERE, "web", "novnc")
if os.path.isdir(_NOVNC_DIR):
    app.mount("/novnc", StaticFiles(directory=_NOVNC_DIR), name="novnc")


@app.on_event("startup")
def _mute_polling_access_logs():
    """Drop the high-frequency /live polling access logs (/snapshot.jpg + /state + /health)
    that otherwise BURY the real engine logs. Done HERE — not at import — because uvicorn.run()
    applies its own logging dictConfig on startup that wipes any earlier filter; the startup
    hook fires AFTER that, so this one sticks. Meaningful requests (/chat, /interrupt, errors) still log."""
    import logging as _lg

    class _Mute(_lg.Filter):
        _NOISY = ("/snapshot.jpg", "/state", "/health")

        def filter(self, record):
            try:
                msg = record.getMessage()
            except Exception:
                return True
            return not any(p in msg for p in self._NOISY)

    _lg.getLogger("uvicorn.access").addFilter(_Mute())


# Live-feed snapshot tuning — on a small (2-core) container the /live screen-grabs
# contend with the browser engine for CPU. So: downscale (SNAPSHOT_MAX_W) + throttle to
# ONE shared frame grabbed at most every SNAPSHOT_MIN_MS — every viewer reuses it.
_SHOT = {"jpg": None, "ts": 0.0}
_SHOT_LOCK = threading.Lock()
_SHOT_MIN_S = max(0, int(os.getenv("SNAPSHOT_MIN_MS", "450"))) / 1000.0
_SHOT_MAX_W = int(os.getenv("SNAPSHOT_MAX_W", "1920"))     # native (display is 1920) → SHARP on PC; throttle still caps grab RATE
_SHOT_Q = int(os.getenv("SNAPSHOT_QUALITY", "72"))


def _grab_jpeg(quality: int = None, max_w: int = None):
    """One JPEG of the virtual display (DISPLAY=:99 under Xvfb) — the real Chrome window
    the engine drives, downscaled to max_w to cut encode CPU + payload. None if no display
    / mss missing (e.g. local headless dev). HTTP process inherits DISPLAY from entrypoint.sh."""
    try:
        import io
        import mss
        from PIL import Image
        with mss.mss() as sct:
            raw = sct.grab(sct.monitors[1])
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        mw = max_w or _SHOT_MAX_W
        if mw and img.width > mw:
            img = img.resize((mw, max(1, round(img.height * mw / img.width))))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality or _SHOT_Q)
        return buf.getvalue()
    except Exception:
        return None


def _cached_jpeg():
    """Shared, time-throttled frame so rapid/concurrent /live polls reuse one grab instead
    of each triggering a full screen-grab+encode (which steals CPU from Chrome on 2 cores).
    When a task has ended, serve the FROZEN final screenshot (the browser has closed → a live
    grab would be black) so the live link keeps showing where the agent stopped."""
    fin = state.get_final_frame()
    if fin is not None:
        return fin
    now = time.monotonic()
    if _SHOT["jpg"] is not None and (now - _SHOT["ts"]) < _SHOT_MIN_S:
        return _SHOT["jpg"]
    with _SHOT_LOCK:
        now = time.monotonic()
        if _SHOT["jpg"] is not None and (now - _SHOT["ts"]) < _SHOT_MIN_S:
            return _SHOT["jpg"]
        jpg = _grab_jpeg()
        if jpg is not None:
            _SHOT["jpg"], _SHOT["ts"] = jpg, now
        return jpg


@app.get("/snapshot.jpg")
def snapshot():
    """One frame of the agent's screen. The /live page polls this — plain short
    responses survive buffering reverse-proxies (AgentBase ingress) that would
    stall a long-lived MJPEG stream."""
    jpg = _cached_jpeg()
    if jpg is None:
        return PlainTextResponse("no display yet", status_code=503)
    return Response(content=jpg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/live.mjpeg")
def live_stream():
    """Smooth MJPEG stream (works when the proxy doesn't buffer)."""
    import time

    def gen(fps=4):
        while True:
            jpg = _cached_jpeg()
            if jpg is None:
                return
            yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                   + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
            time.sleep(1.0 / max(1, fps))

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"})


@app.get("/live")
def live_page():
    """The interactive ops-console live view (app/live.html): live screen +
    real-time reasoning stream + ask_user answer buttons. Send THIS link in Zalo —
    tap it on the Zalo app, watch in the phone browser (plain web link → no
    Zalo-session/cookie conflict)."""
    try:
        with open(_LIVE_HTML, encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except Exception:
        return HTMLResponse("<h1>live view unavailable</h1>", status_code=500)


@app.get("/state")
def live_state():
    """Live agent state for the /live page: status + reasoning thoughts + pending
    ask_user question. Polled ~1s by the page."""
    return JSONResponse(state.live_snapshot())


class AnswerRequest(BaseModel):
    value: str


@app.post("/answer")
def live_answer(req: AnswerRequest):
    """Answer the pending ask_user from the live page's buttons → same
    PendingRegistry the typed-reply / Zalo-poll paths feed."""
    return {"ok": bool(state.deliver_live_answer((req.value or "").strip()))}


class InterruptRequest(BaseModel):
    text: str


@app.post("/interrupt")
def live_interrupt(req: InterruptRequest):
    """Send a mid-task 'chen ngang' from the live page into the running task's
    interrupt queue (same path as Zalo '@ai /interrupt'). ok=False if nothing runs."""
    return {"ok": bool(state.deliver_live_interrupt((req.text or "").strip()))}


class TaskRequest(BaseModel):
    task: str
    mode: str = "interactive"


@app.post("/task")
def start_web_task_ep(req: TaskRequest):
    """Start a browser task from the /live page (anonymous web voter). ISOLATED from Zalo +
    demo_mode (no login, no ordering — enforced in agent_runner.start_web_task / build_tools).
    409 if the single shared browser is already busy; the page then polls /state for progress."""
    task = (req.task or "").strip()
    if not task:
        return JSONResponse({"ok": False, "error": "Nhập tác vụ cần làm nhé."}, status_code=400)
    task = task[:500]
    mode = req.mode if req.mode in ("interactive", "autonomous") else "interactive"
    ok = agent_runner.start_web_task(task, mode=mode, demo_mode=True)
    if not ok:
        return JSONResponse(
            {"ok": False, "busy": True,
             "error": "Agent đang bận chạy một tác vụ khác — chờ xong rồi thử lại nhé."},
            status_code=409)
    return {"ok": True}


@app.get("/logs")
def logs(tail: int = 300, q: str | None = None):
    """Recent in-process log lines (engine + API), so the browser agent's journey
    is visible via the endpoint regardless of the platform's stdout Monitor.
    `?tail=N` limits lines; `?q=agent_core` substring-filters (e.g. agent_core,
    browser_use, Agent Advisor, ASK_EXPERT)."""
    tail = max(1, min(int(tail), 2000))
    return PlainTextResponse("\n".join(state.recent_logs(tail, q)) + "\n")


@app.websocket("/ws-echo")
async def ws_echo(ws: WebSocket):
    """THROWAWAY ingress probe (delete after the noVNC decision). Confirms the AgentBase
    ingress (a) upgrades to WebSocket, (b) holds it open for minutes, (c) carries frames
    BOTH ways — none of which chunked-MJPEG streaming proves. The noVNC live-view bridge
    depends entirely on this. Connect wss://<endpoint>/ws-echo: expect a 'ping <ts>' every
    3s (server→client hold) + an 'echo:' reply to anything sent (client→server)."""
    import asyncio
    import time
    await ws.accept()
    async def heartbeat():
        try:
            while True:
                await asyncio.sleep(3)
                await ws.send_text(f"ping {time.time():.0f}")
        except Exception:
            pass
    hb = asyncio.create_task(heartbeat())
    try:
        while True:
            msg = await ws.receive_text()
            await ws.send_text(f"echo:{msg}")
    except Exception:
        pass
    finally:
        hb.cancel()


@app.websocket("/websockify")
async def vnc_bridge(ws: WebSocket):
    """noVNC live-view transport: bridge the browser's WebSocket ↔ the in-container x11vnc
    TCP socket (127.0.0.1:5900, the Xvfb display the agent's Chrome renders on). Everything
    rides port 8080 through Kong; x11vnc itself is localhost-only. This is the proper
    streaming path (VNC delta-encoding) that replaces the ~2fps snapshot poll. View-only is
    enforced CLIENT-side in live.html (noVNC viewOnly=true) — the bridge stays bidirectional
    because even a view-only RFB must send SetEncodings / FramebufferUpdateRequest upstream."""
    import asyncio
    subs = ws.scope.get("subprotocols") or []
    # echo the client's first requested subprotocol (noVNC may ask for 'binary'); else none
    await ws.accept(subprotocol=(subs[0] if subs else None))
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", 5900)
    except Exception:
        try:
            await ws.close(code=1011)
        except Exception:
            pass
        return

    async def ws_to_vnc():
        try:
            while True:
                writer.write(await ws.receive_bytes())
                await writer.drain()
        except Exception:
            pass

    async def vnc_to_ws():
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                await ws.send_bytes(data)
        except Exception:
            pass

    t1 = asyncio.create_task(ws_to_vnc())
    t2 = asyncio.create_task(vnc_to_ws())
    try:
        await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in (t1, t2):
            if not t.done():
                t.cancel()
        try:
            writer.close()
        except Exception:
            pass
        try:
            await ws.close()
        except Exception:
            pass


@app.get("/health")
def health():
    if state.is_healthy():
        return {
            "status": "ok",
            "zalo_enabled": state.zalo_enabled["value"],
            "listener_alive": state.listener_alive.is_set(),
            "seconds_since_seen": round(state.seconds_since_seen(), 1),
        }
    return JSONResponse(
        status_code=503,
        content={
            "status": "unhealthy",
            "reason": "zalo listener not alive",
            "listener_alive": state.listener_alive.is_set(),
            "seconds_since_seen": round(state.seconds_since_seen(), 1),
        },
    )


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


# Plain Q&A test shim (no group context). Sync endpoints run in FastAPI's
# threadpool, so blocking LLM calls are fine.
@app.post("/chat")
def chat(req: ChatRequest):
    reply = llm.simple_answer(req.message)
    return {"reply": reply, "session_id": req.session_id}
