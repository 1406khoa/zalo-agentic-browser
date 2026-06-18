"""Shared runtime state between the FastAPI server and the zlapi listener."""
import collections
import logging
import threading
import time

# In-memory ring buffer of recent log lines, exposed via GET /logs. Lets the
# browser engine's full journey be read through the (already-exposed) HTTP
# endpoint — independent of whatever the platform's log Monitor scrapes from
# stdout. deque.append is atomic in CPython, so it's safe from the worker thread.
_LOG_BUF = collections.deque(maxlen=2000)


class RingBufferHandler(logging.Handler):
    """Logging handler that retains the last N formatted records in memory."""

    def emit(self, record):
        try:
            _LOG_BUF.append(self.format(record))
        except Exception:
            pass


def recent_logs(tail=200, contains=None):
    """Most recent buffered log lines (optionally substring-filtered)."""
    lines = list(_LOG_BUF)
    if contains:
        c = contains.lower()
        lines = [ln for ln in lines if c in ln.lower()]
    return lines[-tail:]


# ── Live-view state: shared between the browser-engine worker thread and the
#    FastAPI /state + /answer endpoints that power the interactive live page. ──
_live = {"running": False, "done": False, "task": "", "model": "", "mode": "",
         "step": 0, "max_steps": 0, "started_ts": 0.0, "result": None, "interrupt_key": "", "url": ""}
_thoughts = collections.deque(maxlen=200)   # structured reasoning steps for the UI
_pending = {"v": None}                       # current ask_user question or None
_final = {"jpg": None}                       # final screenshot bytes (set at task end → /live freezes on it)
_answer_reg = {"reg": None}                  # the bot's PendingRegistry (POST /answer)
_live_lock = threading.Lock()


def live_begin(task="", model="", mode="", max_steps=0, interrupt_key=""):
    with _live_lock:
        _live.update(running=True, done=False, task=task, model=model, mode=mode,
                     max_steps=max_steps, step=0, started_ts=time.time(), result=None,
                     interrupt_key=str(interrupt_key or ""), url="")
        _thoughts.clear()
        _pending["v"] = None
        _final["jpg"] = None


def live_thought(d):
    """Push one reasoning step dict {n, kind, eval, memory, goal, actions} to the UI."""
    _thoughts.append(d)
    if isinstance(d.get("n"), int):
        _live["step"] = d["n"]


def live_pending(question, options, thread_id, initiator):
    _pending["v"] = {"question": question, "options": list(options or []),
                     "thread_id": str(thread_id), "initiator": str(initiator)}


def live_clear_pending():
    _pending["v"] = None


def live_end(result=None, url=""):
    url = (url or "").strip()
    if url.startswith(("about:", "chrome://", "data:")):
        url = ""   # not a real page → fall back to the last real URL captured during the run
    with _live_lock:
        _live.update(running=False, done=True, result=result, url=url or _live.get("url", ""))
        _pending["v"] = None


def set_final_frame(jpg_bytes):
    """Final screenshot captured at task end (while the browser is still alive). /snapshot.jpg
    serves THIS after the browser closes, so the live feed freezes on the stop screen instead
    of going black. Cleared on the next live_begin."""
    _final["jpg"] = jpg_bytes


def get_final_frame():
    return _final["jpg"]


def set_live_url(url):
    """Remember the latest REAL page URL seen during the run (ignore about:blank / empty /
    new-tab). The final handoff uses this so the link is never 'about:blank' even when the
    browser session is torn down before the end-of-run capture (e.g. abnormal termination)."""
    url = (url or "").strip()
    if url and not url.startswith(("about:", "chrome://", "data:")):
        with _live_lock:
            _live["url"] = url


def live_snapshot():
    with _live_lock:
        s = dict(_live)
    p = _pending["v"]
    s["thoughts"] = list(_thoughts)
    s["pending"] = {"question": p["question"], "options": p["options"]} if p else None
    return s


def register_answer_registry(reg):
    _answer_reg["reg"] = reg


def get_answer_registry():
    """The PendingRegistry currently wired to POST /answer (the Zalo bot's, in prod). The web
    /task path reuses this SAME instance so its ask_user resolves via the live-page buttons."""
    return _answer_reg["reg"]


def deliver_live_answer(value):
    """Route an answer from the live page's buttons into the pending ask_user
    (same PendingRegistry the typed-reply / poll paths feed)."""
    p, reg = _pending["v"], _answer_reg["reg"]
    if not p or not reg:
        return False
    return reg.deliver(p["thread_id"], p["initiator"], value)


def deliver_live_interrupt(text):
    """Route a mid-task 'chen ngang' from the live page into the RUNNING task's
    interrupt queue — the same queue the Zalo '@ai /interrupt' path feeds. Scoped to
    the active task's interrupt_key (its thread_id). No-op if nothing is running."""
    from . import interrupts                       # lazy: interrupts.py is pure (3.10-safe)
    text = (text or "").strip()
    key = _live.get("interrupt_key")
    if not text or not _live.get("running") or not key:
        return False
    interrupts.INTERRUPTS.push(key, text)
    return True


# Set while the listener is connected and in its listen loop.
listener_alive = threading.Event()

# Last time the listener was connected (updated on connect + on each message).
_last_seen = {"ts": 0.0}
_lock = threading.Lock()

# True only when Zalo creds are present and the listener is meant to run.
zalo_enabled = {"value": False}

# How long the listener may be disconnected (reconnect backoff) before /health
# reports unhealthy. Keeps transient reconnects from flapping the probe, while
# still surfacing a permanently-dead listener so AgentBase restarts it.
GRACE_SECONDS = 60.0

# Startup grace: the listener takes a moment to connect on boot. Until it has connected ONCE,
# report HEALTHY for this window so the platform's liveness probe doesn't kill the just-booted
# container during the connect gap (a 503 in that ~0.4s gap → restart → restart-LOOP).
STARTUP_GRACE = 60.0
_proc_start = time.time()


def mark_alive() -> None:
    listener_alive.set()
    with _lock:
        _last_seen["ts"] = time.time()


def mark_dead() -> None:
    # Clear the connected flag but KEEP _last_seen so the grace window applies.
    listener_alive.clear()


def seconds_since_seen() -> float:
    with _lock:
        if _last_seen["ts"] == 0.0:
            return -1.0
        return time.time() - _last_seen["ts"]


def is_healthy() -> bool:
    """Healthy if Zalo is disabled (shim mode), OR the listener is connected,
    OR it disconnected only recently (within the reconnect grace window).

    Liveness is keyed on connection state, NOT message recency — a chat group
    can be silent for hours and that is perfectly healthy.
    """
    if not zalo_enabled["value"]:
        return True
    if listener_alive.is_set():
        return True
    since = seconds_since_seen()
    if since < 0:                        # listener has NEVER connected yet → still booting
        return (time.time() - _proc_start) < STARTUP_GRACE
    return since < GRACE_SECONDS
