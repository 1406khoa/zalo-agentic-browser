"""Entrypoint: FastAPI (port 8080, required by AgentBase) + zlapi listener thread.

The listener connects OUTBOUND to Zalo. If Zalo credentials are absent, the
container still runs as a /chat test shim and stays healthy.
"""
import os
import signal
import sys
import json
import logging
import threading
import time

import uvicorn

from . import state
from .server import app

# Make the browser engine emit INFO step/goal lines (set before the worker lazily
# imports browser_use).
os.environ.setdefault("BROWSER_USE_LOGGING_LEVEL", "info")

# Route ALL logs to STDOUT. logging.basicConfig defaults to STDERR, and AgentBase's
# log Monitor surfaces the container's STDOUT (the API/uvicorn logs) — so engine
# logs on stderr were invisible there. stream=stdout + force=True (override any
# handler a dependency installed first) puts the whole journey where Monitor reads.
_LOG_FMT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=_LOG_FMT, stream=sys.stdout, force=True)

# Also fan logs into the in-memory ring buffer exposed at GET /logs (engine journey
# readable via the HTTP endpoint, not just whatever Monitor scrapes from stdout).
_ring = state.RingBufferHandler()
_ring.setFormatter(logging.Formatter(_LOG_FMT))
logging.getLogger().addHandler(_ring)

# NOTE: the /live polling-access-log mute lives in a FastAPI startup hook in server.py — NOT here.
# Adding it at import time doesn't work: uvicorn.run() applies its own logging config on startup
# that wipes any filter set earlier. The startup hook fires after that, so it sticks.

log = logging.getLogger("main")


# zlapi self-terminates the ENTIRE process — os.kill(os.getpid(), SIGTERM) — when Zalo reports
# "Another connection is opened" (another session on the same account). On AgentBase that kills the
# container → AgentBase restarts it → it reconnects → gets kicked again → SIGTERM → restart-LOOP.
# Neutralize ONLY that self-SIGTERM so the listener's own reconnect loop (_run_listener) handles it
# and the container (uvicorn / live view / browse tasks) stays alive. The platform's own SIGTERM is
# kernel-delivered (not via os.kill) so graceful stops are unaffected; child kills (browser-use
# terminating Chrome — a different pid) pass through untouched.
_real_os_kill = os.kill


def _guarded_os_kill(pid, sig, *args, **kwargs):
    try:
        if pid == os.getpid() and sig == signal.SIGTERM:
            log.warning("Neutralized zlapi self-SIGTERM ('Another connection is opened') — "
                        "listener will reconnect; container stays up.")
            return
    except Exception:
        pass
    return _real_os_kill(pid, sig, *args, **kwargs)


os.kill = _guarded_os_kill


def _load_cookies() -> dict:
    raw = os.getenv("ZALO_COOKIES", "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.error("ZALO_COOKIES is not valid JSON; ignoring.")
        return {}


def _run_listener():
    """Construct the bot and run its blocking listener, restarting on failure."""
    from .zalo_bot import ZaloAIBot  # imported lazily so server can boot without zlapi creds

    phone = os.getenv("ZALO_PHONE", "")
    password = os.getenv("ZALO_PASSWORD", "")
    imei = os.getenv("ZALO_IMEI", "")
    cookies = _load_cookies()

    backoff = 5
    while True:
        try:
            log.info("Connecting to Zalo...")
            bot = ZaloAIBot(phone, password, imei, cookies)
            state.mark_alive()  # connected
            log.info("Zalo listener connected; entering listen loop.")
            backoff = 5
            # Blocking. reconnect handles transient socket drops internally.
            bot.listen(thread=False, reconnect=5)
            log.warning("listen() returned; will reconnect.")
        except Exception:
            log.exception("Zalo listener crashed.")
        finally:
            state.mark_dead()
        log.info("Reconnecting in %ss...", backoff)
        time.sleep(backoff)
        backoff = min(backoff * 2, 60)  # exponential backoff, capped


def main():
    have_creds = bool(os.getenv("ZALO_IMEI") and os.getenv("ZALO_COOKIES"))
    if have_creds:
        state.zalo_enabled["value"] = True
        t = threading.Thread(target=_run_listener, name="zalo-listener", daemon=True)
        t.start()
        log.info("Zalo listener thread started.")
    else:
        log.warning(
            "ZALO_IMEI / ZALO_COOKIES not set — running in /chat shim mode "
            "(no Zalo listener). Container stays healthy."
        )

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
