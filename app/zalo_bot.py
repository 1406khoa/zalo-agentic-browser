"""Zalo group bot built on zlapi (unofficial, personal-account based).

Connects OUTBOUND to Zalo over websocket (no inbound webhook needed).

Replies only in GROUP threads, when @mentioned or when a message contains the
text trigger (default "@ai"). DM/1-1 threads are ignored.

Front door = gpt-4o-mini (fast chat + 8 read-tools). It ROUTES: answers
directly, or calls do_browser_task -> hands a real web ACTION to the qwen
browser engine (async worker, see agent_runner). ask_user replies from a running
task are captured BEFORE the trigger gate, scoped to the task initiator.
"""
import inspect
import logging
import os
import re
from collections import deque

from zlapi import ZaloAPI
from zlapi.models import Message, ThreadType

from . import agent_runner, interrupts, llm, state, tools

log = logging.getLogger("zalo_bot")

# zlapi renamed the cookies kwarg between versions (1.0.2 session_cookies / 1.0.3 cookies).
_COOKIE_KW = (
    "cookies"
    if "cookies" in inspect.signature(ZaloAPI.__init__).parameters
    else "session_cookies"
)

TRIGGER = os.getenv("BOT_TRIGGER", "@ai").lower()
RESPOND_TO_SELF = os.getenv("RESPOND_TO_SELF", "true").lower() == "true"
# Public URL of THIS container's endpoint (AgentBase). Used to build the live-watch
# link (<base>/live) sent in chat. Unset → no live link (start message omits it).
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip()
_AUTONOMOUS_KW = ("tự lo", "tu lo", "/auto", "tự làm hết", "tu lam het")
_BROWSE_CMDS = ("/browse", "/làm", "/lam")


def _is_mentioned(message_object, bot_uid: str, text_lower: str) -> bool:
    """Dual detection: text trigger, or an explicit @mention of the bot."""
    if TRIGGER and TRIGGER in text_lower:
        return True
    if message_object is not None and bot_uid:
        try:
            mentions = message_object.get("mentions")
        except Exception:
            mentions = None
        for m in mentions or []:
            uid = m.get("uid") if isinstance(m, dict) else getattr(m, "uid", None)
            if uid and str(uid) == str(bot_uid):
                return True
    return False


def _strip_trigger(text: str) -> str:
    low = text.lower()
    idx = low.find(TRIGGER)
    if idx != -1:
        text = text[:idx] + text[idx + len(TRIGGER):]
    return text.strip(" :,@\t\n")


def _tools_inventory(specs) -> str:
    """Live, COMPLETE tool list built from the specs the model actually has
    (read-tools + do_browser_task) — not a hardcoded string."""
    lines = []
    for s in specs:
        fn = s.get("function", {})
        name = fn.get("name", "")
        if not name or name == "list_tools":  # don't list the meta-tool itself
            continue
        desc = (fn.get("description") or "").strip().split(". ")[0].rstrip(".")
        lines.append(f"- {name}: {desc}")
    return f"Mình hiện có {len(lines)} công cụ:\n" + "\n".join(lines)


def _as_dict(obj):
    """zlapi Group/model (or dict) → plain dict, best-effort, for parsing poll data."""
    if isinstance(obj, dict):
        return obj
    for m in ("toDict", "to_dict", "_to_dict"):
        f = getattr(obj, m, None)
        if callable(f):
            try:
                d = f()
                if isinstance(d, dict):
                    return d
            except Exception:
                pass
    d = getattr(obj, "__dict__", None)
    return d if isinstance(d, dict) else {}


def _extract_poll_id(resp):
    d = _as_dict(resp)
    for k in ("poll_id", "pollId", "pollID", "id"):
        if d.get(k):
            return d[k]
    return None


def _extract_poll_choice(detail, initiator):
    """Which option TEXT did `initiator` vote for? None if not yet. Defensive across
    unknown Zalo key names — the raw detail is logged once so keys can be tuned."""
    d = _as_dict(detail)
    init = str(initiator)
    opts = (d.get("options") or d.get("poll_options") or d.get("voteOptions")
            or d.get("topic_options") or [])
    for opt in opts:
        o = _as_dict(opt)
        voters = (o.get("voted_member_ids") or o.get("votedMemberIds") or o.get("voters")
                  or o.get("member_ids") or o.get("voted") or o.get("votes") or [])
        ids = [str(v.get("id") or v.get("userId") or v.get("uid") or "") if isinstance(v, dict)
               else str(v) for v in voters]
        if init in ids:
            return (o.get("content") or o.get("text") or o.get("name") or o.get("option")
                    or o.get("title") or "").strip() or None
    return None


class ZaloAIBot(ZaloAPI):
    def __init__(self, phone, password, imei, cookies):
        super().__init__(phone, password, imei, **{_COOKIE_KW: cookies})
        self.bot_uid = None
        try:
            info = self.fetchAccountInfo() or {}
            prof = info.get("profile") if isinstance(info, dict) else None
            self.bot_uid = str((prof or {}).get("userId") or "") or None
        except Exception as e:
            log.warning("Could not fetch bot account info: %s", e)
        self.registry = agent_runner.PendingRegistry()
        state.register_answer_registry(self.registry)  # lets POST /answer (live page) resolve ask_user
        # Bot account == owner account (RESPOND_TO_SELF) → our own sends echo back
        # through onMessage. Track recent sends to suppress those echoes.
        self._recent_sent = deque(maxlen=60)
        log.info("Bot uid: %s | trigger: %r", self.bot_uid, TRIGGER)

    def say(self, thread_id, thread_type, text):
        """Send to a thread: format for Zalo (bold/plain) + loop-guard + echo-track."""
        body, parse_mode = llm.format_for_zalo(text or "")
        if not body:
            return
        if TRIGGER:  # loop-guard: our own message must not carry the trigger
            body = re.sub(re.escape(TRIGGER), TRIGGER.lstrip("@"), body, flags=re.IGNORECASE)
        self._recent_sent.append(body.strip())
        try:
            self.send(Message(text=body, parse_mode=parse_mode),
                      thread_id=thread_id, thread_type=thread_type)
        except Exception:
            log.exception("Failed to send")

    def _send_image(self, thread_id, thread_type, path, caption):
        """Send a LOCAL image with a text caption (used for the final handoff: stop-screen
        screenshot + summary + link). zlapi wants the caption as a Message OBJECT, not a str."""
        body, parse_mode = llm.format_for_zalo(caption or "")
        if TRIGGER and body:  # loop-guard: our own caption must not carry the trigger
            body = re.sub(re.escape(TRIGGER), TRIGGER.lstrip("@"), body, flags=re.IGNORECASE)
        if body:
            self._recent_sent.append(body.strip())  # echo-suppress the caption text
        try:
            msg = Message(text=body, parse_mode=parse_mode) if body else None
            self.sendLocalImage(path, thread_id=thread_id, thread_type=thread_type, message=msg)
        except Exception:
            log.exception("Failed to send image; falling back to text")
            if caption:
                self.say(thread_id, thread_type, caption)

    def onMessage(self, mid=None, author_id=None, message=None,
                  message_object=None, thread_id=None, thread_type=ThreadType.USER):
        state.mark_alive()

        if thread_type != ThreadType.GROUP:
            return
        if not isinstance(message, str) or not message.strip():
            return
        msg = message.strip()
        is_self = self.bot_uid and str(author_id) == str(self.bot_uid)

        # 0) Suppress our OWN echoes (form/result we just sent comes back here).
        if is_self and msg in self._recent_sent:
            return

        # 1) ask_user reply capture — a PLAIN (non-@ai) message from the task
        #    initiator, BEFORE the trigger gate (the reply has no @ai → would
        #    otherwise be dropped and the agent would hang).
        if TRIGGER not in msg.lower() and self.registry.deliver(thread_id, author_id, msg):
            return

        if is_self and not RESPOND_TO_SELF:
            return
        if not _is_mentioned(message_object, self.bot_uid, msg.lower()):
            return

        query = _strip_trigger(msg)
        log.info("Triggered in %s by %s: %r", thread_id, author_id, query[:60])
        try:
            self._handle(query, thread_id, thread_type, author_id)
        except Exception as e:
            log.exception("Error handling message")
            self.say(thread_id, thread_type, f"Xin lỗi, mình gặp lỗi khi xử lý 😢 ({type(e).__name__})")

    def _handle(self, query, thread_id, thread_type, author_id):
        low = query.lower()
        mode = "autonomous" if any(k in low for k in _AUTONOMOUS_KW) else "interactive"

        # Stop a running task NOW (engine halts mid-step via the stop callback).
        if low in ("/huỷ", "/huy", "/cancel", "/stop", "huỷ", "huy"):
            was_running = agent_runner.cancel(thread_id)
            self.registry.cancel_pending(thread_id)  # unblock if parked in ask_user
            self.registry.close(thread_id)
            self.say(thread_id, thread_type,
                     "✅ Đã huỷ — agent đang dừng lại ngay. Bạn ra lệnh mới được rồi nhé."
                     if was_running else
                     "Hiện không có tác vụ nào đang chạy. Bạn cứ ra lệnh mới bình thường nhé.")
            return

        # ⚡ Chen ngang — add a request to the RUNNING task: "@ai /interrupt <yêu cầu>".
        # Reaches here (not the ask-reply capture) because @ai is present → see onMessage.
        if low.startswith("/interrupt") or low.startswith("/chen"):
            parts = query.split(maxsplit=1)
            extra = parts[1].strip() if len(parts) > 1 else ""
            if not extra:
                self.say(thread_id, thread_type,
                         "Cú pháp: /interrupt <yêu cầu bổ sung>. Vd: @ai /interrupt mua thêm 1 cái quần.")
            elif agent_runner.is_running(thread_id):
                interrupts.INTERRUPTS.push(thread_id, extra)
                self.say(thread_id, thread_type,
                         f"🟡 Ghi nhận chen ngang: «{extra}» — mình sẽ làm thêm sau bước hiện tại nhé.")
            else:
                self.say(thread_id, thread_type,
                         "Hiện không có tác vụ nào đang chạy để chen ngang. Bạn cứ ra lệnh mới bình thường nhé.")
            return

        # The tools the front-door model can use: 8 read-tools + browse + self-inventory.
        specs = tools.openai_specs() + [agent_runner.BROWSER_TASK_SPEC, agent_runner.LIST_TOOLS_SPEC]

        def executor(name, args):
            if name == "do_browser_task":
                task = ((args or {}).get("task") or "").strip() or query
                m = (args or {}).get("mode") or mode
                ok = self._start_browser(task, m, thread_id, thread_type, author_id)
                return ("Đã bắt đầu mở trình duyệt làm việc này; kết quả/câu hỏi sẽ "
                        "nhắn lại sau. Chỉ cần xác nhận ngắn gọn với người dùng."
                        if ok else
                        "Đang chạy một tác vụ khác cho nhóm này rồi — báo người dùng đợi xong đã.")
            if name == "list_tools":
                return _tools_inventory(specs)
            return tools.execute(self, thread_id, name, args)

        # No query, or "/tools"/"/help" → let the MODEL self-report its tools
        # (it calls list_tools to get the exact, complete list — no hardcoded text).
        if not query or low.startswith("/tools") or low.startswith("/help"):
            prompt = ("Giới thiệu thật ngắn gọn bạn là ai, rồi liệt kê đầy đủ các công cụ "
                      "và khả năng của bạn cho người dùng. BẮT BUỘC gọi list_tools để lấy "
                      "danh sách CHÍNH XÁC, đừng tự bịa.")
            self.say(thread_id, thread_type, llm.reply_with_tools(prompt, specs, executor))
            return

        # Explicit browse override — "/browse <task>" / "/làm <task>".
        if any(low.startswith(c) for c in _BROWSE_CMDS):
            parts = query.split(maxsplit=1)
            task = parts[1].strip() if len(parts) > 1 else ""
            if not task:
                self.say(thread_id, thread_type,
                         "Bạn muốn mình làm gì trên web? Vd: /browse đặt vé đi Hà Nội ngày 10/6")
                return
            self._start_browser(task, mode, thread_id, thread_type, author_id)
            return

        # Other slash commands → direct read-tool invocation.
        if query.startswith("/"):
            self.say(thread_id, thread_type, tools.run_command(self, thread_id, query))
            return

        # Natural language → front-door model (answer / read-tool / hand off to engine).
        self.say(thread_id, thread_type, llm.reply_with_tools(query, specs, executor))

    def _start_browser(self, task, mode, thread_id, thread_type, author_id):
        # Live-watch link instead of streaming a screenshot every step (that
        # flooded the chat). One link → user watches real-time in the phone browser.
        live_url = f"{PUBLIC_BASE_URL.rstrip('/')}/live" if PUBLIC_BASE_URL else None

        # Native Zalo poll for ask_user (interactive UI in the chat bubble): single
        # choice + members may add a custom option; we read THIS user's vote back.
        # Bot must be group OWNER to create polls — on any failure ask_user falls
        # back to the typed text form (handled in ZaloAskChannel).
        poll_api = None
        if hasattr(self, "createPoll"):
            _logged = {"raw": False}

            def _poll_create(question, options):
                resp = self.createPoll(question, list(options), groupId=thread_id,
                                       multiChoices=False, allowAddNewOption=True, pinAct=True)
                log.info("createPoll raw -> %r", _as_dict(resp))
                return _extract_poll_id(resp)

            def _poll_read(poll_id):
                detail = self.viewPollDetail(poll_id)
                if not _logged["raw"]:
                    log.info("viewPollDetail raw -> %r", _as_dict(detail))
                    _logged["raw"] = True
                return _extract_poll_choice(detail, author_id)

            def _poll_lock(poll_id):
                self.lockPoll(poll_id)

            poll_api = {"create": _poll_create, "read": _poll_read, "lock": _poll_lock}

        return agent_runner.start_task(
            task, mode=mode, thread_id=thread_id, initiator=author_id,
            registry=self.registry,
            send_func=lambda text: self.say(thread_id, thread_type, text),
            send_image=lambda path, caption: self._send_image(thread_id, thread_type, path, caption),
            live_url=live_url, poll_api=poll_api,
        )
