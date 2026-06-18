"""Bridge between the browser engine and Zalo.

- PendingRegistry: tracks the open ask_user question per thread. Only the task
  INITIATOR's next message (captured BEFORE the @ai trigger gate in onMessage)
  is accepted as the answer — this is the fix for the "reply has no @ai → bot
  drops it → ask_user hangs 900s" bug.
- ZaloAskChannel: sends the numbered form to the thread and blocks until the
  initiator replies (routed by the registry) or a timeout.
- start_task: runs a browser task in a background thread so the Zalo listener
  stays responsive. The engine (agent_core, browser-use, needs 3.11+) is
  imported LAZILY inside the thread, so this module loads fine on Python 3.10.
"""
import asyncio
import logging
import os
import queue
import threading

from . import state
from .ask_channel import AskChannel, render_form, resolve_answer

log = logging.getLogger("agent_runner")
ASK_TIMEOUT = int(os.getenv("ASK_TIMEOUT", "300"))
MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "40"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "3"))  # secs between native-poll vote checks
WEB_THREAD_ID = "web"   # synthetic thread for browser-initiated (/task) runs — no Zalo group → can't leak to Zalo
WEB_ASK_TIMEOUT = int(os.getenv("WEB_ASK_TIMEOUT", "90"))  # short (vs Zalo 300s): an abandoned voter mustn't freeze the shared browser

# The tool the CHAT model (gpt-4o-mini, the front door) calls to hand a real web
# ACTION off to the qwen browser engine. The description is the router: it must
# fire only for "do it" intents, never for questions / advice / "dự định".
BROWSER_TASK_SPEC = {
    "type": "function",
    "function": {
        "name": "do_browser_task",
        "description": (
            "Mở trình duyệt và TỰ THỰC HIỆN một tác vụ trên web cho người dùng: "
            "đặt vé máy bay, mua hàng (Shopee/Tiki/Lazada), đặt bàn nhà hàng, "
            "lên kế hoạch du lịch, tra cứu rồi thao tác, điền form... "
            "CHỈ gọi khi người dùng muốn bạn THỰC SỰ LÀM hành động đó. TUYỆT ĐỐI "
            "KHÔNG gọi cho câu hỏi / tư vấn / ý định (vd 'dự định mua', 'nên mua "
            "gì', 'giá bao nhiêu', 'có nên...' → cứ trả lời bình thường). Tác vụ "
            "chạy nền vài phút và sẽ tự nhắn lại kết quả + hỏi thêm khi cần."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Mô tả tác vụ web cần làm, càng rõ càng tốt, "
                                   "GỒM mọi thông tin người dùng đã cung cấp (điểm đi/đến, ngày, sản phẩm, ngân sách...).",
                },
                "mode": {
                    "type": "string",
                    "enum": ["interactive", "autonomous"],
                    "description": "interactive = hỏi lại các quyết định quan trọng (MẶC ĐỊNH). "
                                   "autonomous = tự quyết hết, chỉ hỏi khi bế tắc — dùng khi người "
                                   "dùng nói 'tự lo' / 'tự làm hết' / 'mình bận'.",
                },
            },
            "required": ["task"],
        },
    },
}


LIST_TOOLS_SPEC = {
    "type": "function",
    "function": {
        "name": "list_tools",
        "description": (
            "Trả về danh sách CHÍNH XÁC các công cụ / khả năng bạn đang có (tên + "
            "mô tả). Gọi tool này khi người dùng hỏi 'bạn có tool gì', 'làm được "
            "gì', 'có bao nhiêu công cụ', hoặc khi cần tự kiểm tra năng lực của "
            "mình — ĐỪNG tự liệt kê từ trí nhớ, hãy gọi tool này để biết chính xác."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}


class PendingRegistry:
    """Per-thread open ask_user question, answerable only by the initiator."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending = {}  # thread_id -> {"initiator", "q", "options"}

    def open(self, thread_id, initiator, options):
        q = queue.Queue(maxsize=1)
        with self._lock:
            self._pending[str(thread_id)] = {
                "initiator": str(initiator), "q": q, "options": list(options or []),
            }
        return q

    def close(self, thread_id):
        with self._lock:
            self._pending.pop(str(thread_id), None)

    def cancel_pending(self, thread_id):
        """Unblock a worker that's parked inside ask_user (used by /huỷ): push a
        sentinel so its blocking wait returns at once; the engine's stop flag then
        halts it on the next check, instead of hanging until ASK_TIMEOUT."""
        with self._lock:
            p = self._pending.get(str(thread_id))
            q = p["q"] if p else None
        if q is not None:
            try:
                q.put_nowait("(tác vụ đã bị huỷ)")
            except queue.Full:
                pass

    def has_pending(self, thread_id):
        with self._lock:
            return str(thread_id) in self._pending

    def deliver(self, thread_id, author_id, text):
        """Route `text` as the answer iff a question is pending for this thread
        AND author_id is the initiator. Returns True if it was consumed."""
        with self._lock:
            p = self._pending.get(str(thread_id))
            if not p or str(author_id) != p["initiator"]:
                return False
            options, q = p["options"], p["q"]
        ans = resolve_answer(text, options)
        try:
            q.put_nowait(ans)
        except queue.Full:
            return False
        return True


class ZaloAskChannel(AskChannel):
    """ask_user over Zalo. Preferred path = a NATIVE Zalo poll (interactive UI right
    in the chat bubble): single-choice, members may add a custom option. We read the
    INITIATOR's vote back to unblock. A typed reply is always accepted too (the
    fallback that works even if poll create/parse misbehaves). First to arrive wins.

    poll_api (or None) = {"create"(question, options)->poll_id, "read"(poll_id)->
    chosen option text or None, "lock"(poll_id)->None}. None → numbered text form."""

    def __init__(self, thread_id, initiator, registry, send_func, poll_api=None, timeout=ASK_TIMEOUT):
        self.thread_id = thread_id
        self.initiator = initiator
        self.registry = registry
        self._send = send_func          # callable(text) -> sends to the thread
        self.poll_api = poll_api
        self.timeout = timeout

    async def ask(self, question, options):
        options = list(options or [])
        q = self.registry.open(self.thread_id, self.initiator, options)  # typed-reply path
        state.live_pending(question, options, self.thread_id, self.initiator)  # /live buttons
        poll_id = None
        if self.poll_api:
            try:
                poll_id = await asyncio.to_thread(self.poll_api["create"], question, options)
            except Exception:
                log.warning("createPoll failed; using text form", exc_info=True)
        if poll_id:
            self._send(f"🗳️ {question}\n👉 Bấm chọn trong BÌNH CHỌN ở trên (chọn '+ Thêm lựa chọn' để "
                       "tự nhập), hoặc gõ trả lời tại đây.")
        else:
            self._send(render_form(question, options))   # no poll → numbered text form
        log.info("ASK_USER (thread=%s poll=%s): %s", self.thread_id, poll_id, str(question)[:80])

        def _wait():
            waited = 0
            while waited < self.timeout:
                try:
                    return q.get(timeout=POLL_INTERVAL)   # a typed reply resolves immediately
                except queue.Empty:
                    pass
                if poll_id:                               # else check the poll for the initiator's vote
                    try:
                        choice = self.poll_api["read"](poll_id)
                    except Exception:
                        choice = None
                    if choice:
                        return choice
                waited += POLL_INTERVAL
            return options[0] if options else "(người dùng không trả lời, tự quyết hợp lý)"

        try:
            return await asyncio.to_thread(_wait)
        finally:
            self.registry.close(self.thread_id)
            state.live_clear_pending()
            if poll_id:
                try:
                    await asyncio.to_thread(self.poll_api["lock"], poll_id)
                except Exception:
                    pass


class WebAskChannel(AskChannel):
    """ask_user for a browser-initiated (web /task) run. The question + options surface on /live
    via state.live_pending and are answered by the page's buttons (POST /answer → the SAME
    PendingRegistry the Zalo path uses). NO Zalo send. Shorter timeout so an abandoned voter
    doesn't freeze the single shared browser; on timeout it falls back to options[0]."""

    def __init__(self, thread_id, initiator, registry, timeout=WEB_ASK_TIMEOUT):
        self.thread_id = thread_id
        self.initiator = initiator
        self.registry = registry
        self.timeout = timeout

    async def ask(self, question, options):
        options = list(options or [])
        q = self.registry.open(self.thread_id, self.initiator, options)
        state.live_pending(question, options, self.thread_id, self.initiator)
        log.info("ASK_USER (web thread=%s): %s", self.thread_id, str(question)[:80])

        def _wait():
            try:
                return q.get(timeout=self.timeout)
            except queue.Empty:
                return options[0] if options else "(không có trả lời, tự quyết hợp lý)"

        try:
            return await asyncio.to_thread(_wait)
        finally:
            self.registry.close(self.thread_id)
            state.live_clear_pending()


_WEB_REGISTRY = None


def _web_registry():
    """Reuse the registry registered with state (the Zalo bot's, in prod) so POST /answer resolves
    against the SAME instance WebAskChannel opens. In shim mode (no Zalo bot) lazily create one
    module-level registry and register it. NEVER per-call (that would split /answer routing)."""
    global _WEB_REGISTRY
    reg = state.get_answer_registry()
    if reg is not None:
        return reg
    if _WEB_REGISTRY is None:
        _WEB_REGISTRY = PendingRegistry()
        state.register_answer_registry(_WEB_REGISTRY)
    return _WEB_REGISTRY


_active_lock = threading.Lock()
_active = {}  # thread_id -> threading.Event (cancel signal for its running task)


def is_running(thread_id):
    with _active_lock:
        return str(thread_id) in _active


def cancel(thread_id):
    """Signal the running task (if any) to STOP. The engine wires this Event to
    browser-use's register_should_stop_callback, which is checked several times
    per step → the agent actually halts mid-task (stops browsing + streaming)
    rather than running to its own timeout. Returns True if a task was running."""
    with _active_lock:
        ev = _active.get(str(thread_id))
    if ev is None:
        return False
    ev.set()
    return True


def start_task(task, *, mode, thread_id, initiator, registry, send_func,
               send_image=None, send_gif=None, live_url=None, poll_api=None):
    """Run a browser task in a background thread. Returns False if one is already
    running for this thread (one task per thread at a time). live_url, if given, is
    sent ONCE at the start so the user watches the browser live in a phone browser
    (replaces the per-step screenshot stream, which flooded the chat). send_image/
    send_gif still work if a caller wants the old per-step preview."""
    tid = str(thread_id)
    cancel_event = threading.Event()
    with _active_lock:
        if tid in _active or WEB_THREAD_ID in _active:   # one browse task at a time (shared Chrome + global /live)
            return False
        _active[tid] = cancel_event

    def _run():
        # Lazy import: agent_core pulls browser-use (3.11+), only available in
        # the container. Keeping it here lets this module import on 3.10.
        try:
            from .agent_core import run_task, container_session
            channel = ZaloAskChannel(thread_id, initiator, registry, send_func, poll_api=poll_api)
            if live_url:
                send_func(f"🤖 Mình bắt đầu rồi! Xem mình thao tác TRỰC TIẾP tại:\n{live_url}\n"
                          "Xong mình nhắn kết quả; cần quyết định gì mình hỏi lại ngay nhé.")
            else:
                send_func("🤖 Mình bắt đầu xử lý nhé — sẽ nhắn kết quả khi xong, hỏi lại nếu cần.")
            history = asyncio.run(run_task(
                task, channel, mode=mode,
                browser_session=container_session(), max_steps=MAX_STEPS,
                cancel_event=cancel_event, interrupt_key=tid,   # "/interrupt" pushes here
            ))   # NOTE: no per-step send_image stream (it flooded chat) — ONE final screenshot below
            if cancel_event.is_set():
                return  # user ran /huỷ — that handler already replied; stay quiet
            # ── FINAL HANDOFF: always a short SUMMARY + the real STOP-PAGE URL + a SCREENSHOT.
            result = (history.final_result() or "").strip()
            snap = {}
            try:
                snap = state.live_snapshot()
            except Exception:
                snap = {}
            if not result:
                result = (snap.get("result") or "").strip()
            if not result:
                # Agent didn't done() cleanly (e.g. terminated on repeated failures) → SYNTHESIZE
                # a short summary from the last reasoning step so the user is never left with
                # "không có tóm tắt".
                ths = snap.get("thoughts") or []
                last = next((t for t in reversed(ths) if t.get("memory") or t.get("goal")), {})
                bits = [b for b in (last.get("memory"), last.get("goal")) if b]
                result = ("Mình đã làm tới đây: " + " — ".join(bits) + "."
                          if bits else "Mình đã dừng lại (chưa hoàn tất tác vụ).")
            tail = []
            final_url = (snap.get("url") or "").strip()   # real URL (about:blank filtered out in state)
            if final_url:
                tail.append(f"🔗 Trang mình dừng lại (mở để xem / mua tiếp trên máy bạn):\n{final_url}")
            if live_url:
                tail.append(f"🖥️ Xem lại màn hình: {live_url}")
            caption = result + (("\n\n" + "\n".join(tail)) if tail else "")
            # Send the FINAL SCREENSHOT carrying the summary+links as its caption (ONE rich message,
            # not the old per-step flood). Fall back to plain text if there's no frame / image-sender.
            sent = False
            if send_image:
                try:
                    frame = state.get_final_frame()
                    if frame:
                        shot = os.path.join(os.getenv("PREVIEW_DIR", "/tmp/agent_preview"), "handoff.jpg")
                        os.makedirs(os.path.dirname(shot), exist_ok=True)
                        with open(shot, "wb") as _f:
                            _f.write(frame)
                        send_image(shot, caption)
                        sent = True
                except Exception:
                    log.warning("final screenshot send failed", exc_info=True)
            if not sent:
                send_func(caption)
        except Exception as e:
            if cancel_event.is_set():
                return  # our stop signal surfaced as InterruptedError — stay quiet
            log.exception("task failed")
            send_func(f"😢 Mình gặp lỗi khi xử lý ({type(e).__name__}).")
        finally:
            registry.close(thread_id)
            with _active_lock:
                _active.pop(tid, None)

    threading.Thread(target=_run, daemon=True).start()
    return True


def start_web_task(task, *, mode="interactive", demo_mode=True):
    """Run a browser task initiated from the /live page (anonymous web voter), ISOLATED from Zalo:
    a synthetic 'web' thread (no Zalo group → its result/ask_user can't leak to a Zalo chat), ask_user
    on the live page, NO Zalo send, and demo_mode guardrails (no login, no ordering). Returns False if
    ANY browse task is already running (single shared Chrome). Result surfaces on /state (page polls)."""
    reg = _web_registry()
    cancel_event = threading.Event()
    with _active_lock:
        if _active:                       # global: only one browse task at a time
            return False
        _active[WEB_THREAD_ID] = cancel_event

    def _run():
        try:
            from .agent_core import run_task, container_session
            channel = WebAskChannel(WEB_THREAD_ID, WEB_THREAD_ID, reg)
            asyncio.run(run_task(
                task, channel, mode=mode, demo_mode=demo_mode,
                browser_session=container_session(), max_steps=MAX_STEPS,
                cancel_event=cancel_event, interrupt_key=WEB_THREAD_ID,
            ))   # result published to state.live_* → /live reads it via /state (no Zalo send)
        except Exception:
            if cancel_event.is_set():
                return
            log.exception("web task failed")
        finally:
            reg.close(WEB_THREAD_ID)
            with _active_lock:
                _active.pop(WEB_THREAD_ID, None)

    threading.Thread(target=_run, daemon=True).start()
    return True
