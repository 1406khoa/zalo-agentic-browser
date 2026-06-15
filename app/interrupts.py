"""Mid-task INTERRUPT queue — "chen ngang".

Lets the user add a NEW request WHILE the agent is already running a task ("đang mua áo
thì chen 'mua thêm cái quần'"). The Zalo listener / `/live` PUSH interrupts here; the
running agent DRAINS them at each step boundary and injects them into its context so it
re-plans. This is the *reverse* direction of `ask_user` (agent→user): here it's user→agent,
unsolicited.

Keyed by thread_id (the conversation/task). Thread-safe: the Zalo listener thread pushes,
the browse worker thread drains — so all access is under a lock.
"""
import threading


class InterruptRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._q = {}  # str(key) -> [text, ...]   (FIFO per task)

    def push(self, key, text):
        """Queue a new user request for the task identified by `key` (thread_id)."""
        text = (text or "").strip()
        if not text or key is None:
            return False
        with self._lock:
            self._q.setdefault(str(key), []).append(text)
        return True

    def drain(self, key):
        """Return AND clear all pending interrupts for `key` (oldest first)."""
        if key is None:
            return []
        with self._lock:
            return self._q.pop(str(key), [])

    def has(self, key):
        if key is None:
            return False
        with self._lock:
            return bool(self._q.get(str(key)))

    def clear(self, key):
        with self._lock:
            self._q.pop(str(key), None)


# Module-level singleton: the Zalo listener / /live push, the worker drains.
INTERRUPTS = InterruptRegistry()
