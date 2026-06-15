"""Browser action engine — the REAL engine (not a PoC script).

Builds a browser-use Agent wired with:
- the playbook tools (load_playbook) — progressive-disclosure use-case skills
- a channel-backed ask_user(question, options) — human-in-the-loop, with a
  per-task ASK CAP so the agent can't pester the user.

Two MODES (set per task; Zalo layer maps the "tự lo"/"/auto" keyword -> autonomous):
- interactive (default): ask MATERIAL/ambiguous decisions, auto-decide low-stakes,
  cap 3 questions, max reliability — the demo's ask_user "wow".
- autonomous ("tự lo"): auto-decide everything with sensible defaults, ask ONLY
  when truly blocked / about to need personal data, cap 1, report decisions at
  the end — the fire-and-forget power.

The ask channel is INJECTED (FileAskChannel local, ZaloAskChannel prod).
Goal-not-selector playbooks keep it resilient to site changes.
"""
import asyncio
import base64
import json
import logging
import os
import re

from browser_use import Agent, BrowserSession, ChatOpenAI, Tools
from browser_use.agent.views import ActionResult
from browser_use.llm.messages import UserMessage
from openai import OpenAI

from . import state as appstate   # aliased — build_tools has a local var named `state`
from . import agent_cursor        # virtual mouse-cursor overlay (cosmetic, never blocks)
from . import interrupts          # mid-task "chen ngang" queue (user→agent)
from .playbook_loader import build_system_guidance, load_playbook as _load_playbook

log = logging.getLogger("agent_core")
# Endpoint is env-driven so we can point the engine at PROD MaaS (defaults to dev).
MAAS_BASE = os.getenv("MAAS_BASE", "https://mass-llm-aiplatform-dev.api.vngcloud.tech/v1")
_PREVIEW_DIR = os.getenv("PREVIEW_DIR", "/tmp/agent_preview")
TASK_TIMEOUT = int(os.getenv("TASK_TIMEOUT", "900"))  # wall-clock cap → a hung task frees the thread


# ── Login PROFILE (env-only secrets — the agent logs in LIVE; we do NOT inject cookies) ──
# Cookie injection (WARM_STORAGE_STATE) was REMOVED: a captured Google/Akamai session is
# non-portable (rotating __Secure-*PSIDTS + device binding → rejected even on the same
# residential IP; Akamai bot cookies are IP/fingerprint-bound and die in hours). The robust
# path is a REAL login: the agent fills configured TEST-account credentials via the fill_login
# tool. Secrets live ONLY in env (AGENT_LOGINS), never in a prompt / log / the live view, and
# the values are filled straight into the page (they never enter the model's context).
#
# AGENT_LOGINS = JSON {"<domain>": {"username": "...", "password": "..."}} — optionally base64
# (env-safe) or wrapped in shell quotes. Example:
#   AGENT_LOGINS='{"uniqlo.com":{"username":"acc@example.com","password":"••••"}}'
def _load_logins():
    raw = (os.getenv("AGENT_LOGINS") or "").strip()
    if not raw:
        return {}
    if len(raw) >= 2 and raw[0] in "'\"" and raw[-1] == raw[0]:
        raw = raw[1:-1].strip()                       # strip accidental shell quotes from .env
    try:
        data = raw if raw.lstrip().startswith("{") else base64.b64decode(raw).decode("utf-8")
        obj = json.loads(data)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        log.warning("AGENT_LOGINS is set but unparseable (want JSON {domain:{username,password}})")
        return {}


_LOGINS = _load_logins()
# Passwords to scrub from any user-facing text (defense-in-depth; values never reach the model).
_SECRET_VALUES = [str(c.get("password", "")) for c in _LOGINS.values()
                  if isinstance(c, dict) and c.get("password")]


def _match_login(site):
    """Find the configured login whose domain matches `site` (substring either way)."""
    s = (site or "").strip().lower()
    if not s:
        return None, None
    for domain, cred in _LOGINS.items():
        d = str(domain).lower()
        if d and (d in s or s in d) and isinstance(cred, dict):
            return domain, cred
    return None, None


# Fill the username + password fields of the CURRENT login form using the React/Vue-safe
# native-value setter (plain .value misses framework state). Values are passed in as JSON
# args over CDP only — they never touch the model context, /live, or /logs.
_FILL_JS = r"""
(function(u, p){
  function setVal(el, v){ try{
    var proto = (el.tagName === 'TEXTAREA') ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    var d = Object.getOwnPropertyDescriptor(proto, 'value');
    if (d && d.set) { d.set.call(el, v); } else { el.value = v; }
    el.dispatchEvent(new Event('input',  {bubbles:true}));
    el.dispatchEvent(new Event('change', {bubbles:true}));
    el.dispatchEvent(new Event('blur',   {bubbles:true}));
  } catch(e){} }
  var pw = document.querySelector('input[type=password]:not([disabled])');
  if (!pw) { return 'NO_PASSWORD_FIELD'; }
  var scope = pw.form || document;
  var cands = Array.prototype.slice.call(scope.querySelectorAll(
    'input[type=email],input[type=text],input[type=tel],input[name*=mail i],input[name*=user i],input:not([type])'));
  cands = cands.filter(function(i){ return i !== pw && i.offsetParent !== null && !i.disabled; });
  var uEl = cands[0] || null;
  if (uEl) { uEl.focus(); setVal(uEl, u); }
  pw.focus(); setVal(pw, p);
  return uEl ? 'FILLED_BOTH' : 'FILLED_PASSWORD_ONLY';
})(__U__, __P__);
"""


async def _eval_page(browser_session, js):
    """Run JS in the agent-focused (top) frame and return its value (best-effort)."""
    tid = getattr(browser_session, "agent_focus_target_id", None)
    cdp = await browser_session.get_or_create_cdp_session(tid, focus=False)
    r = await cdp.cdp_client.send.Runtime.evaluate(
        params={"expression": js, "returnByValue": True}, session_id=cdp.session_id)
    return (r or {}).get("result", {}).get("value")

# Neutralize dotted abbreviations like "TP.HCM" in the task so browser-use's
# task-URL autodetect doesn't navigate to a bogus domain (https://TP.HCM → crash).
# Real domains are kept (the part after the dot is a known TLD).
_TLDS = {"com", "vn", "net", "org", "io", "co", "me", "ai", "app", "dev", "gov",
         "edu", "info", "vng", "biz", "xyz"}
_DOTTED_RE = re.compile(r"\b([0-9A-Za-zÀ-ỹ]{1,8})\.([0-9A-Za-zÀ-ỹ]{1,8})\b")


def _neutralize_dotted(text):
    """'TP.HCM' -> 'TP HCM' (keep shopee.vn etc.) so it's never seen as a URL."""
    if not isinstance(text, str):
        return text or ""
    return _DOTTED_RE.sub(
        lambda m: m.group(0) if m.group(2).lower() in _TLDS else f"{m.group(1)} {m.group(2)}",
        text,
    )

# Applies in BOTH modes — the anti-over-ask + auto-decide rules.
_BASE_GUIDANCE = (
    "\n\nMẹo chung: ưu tiên gõ vào ô tìm kiếm/lọc thay vì cuộn mù; nếu thử 2-3 lần "
    "vẫn kẹt thì đổi cách, đừng lặp lại. BẠN ĐƯỢC THỬ–SAI–SỬA: lỡ thao tác ngoài ý muốn "
    "(mở nhầm trang/popup/mục, bị một bước phụ như wishlist/đăng nhập chặn lại) thì bình "
    "tĩnh GỠ ra (đóng X / quay lại / bỏ chọn / đăng nhập rồi gỡ) và quay lại MỤC TIÊU CHÍNH "
    "— đừng coi một cú nhầm là thất bại, đừng kẹt, đừng bỏ cuộc giữa chừng. ĐỪNG hỏi lại "
    "thông tin người dùng ĐÃ cung "
    "cấp trong yêu cầu. TỰ QUYẾT các lựa chọn nhỏ có default rõ ràng (nhiều lựa chọn "
    "sát nhau → chọn sớm nhất / rẻ nhất / phổ biến nhất; hạng vé → rẻ nhất). Khi tới "
    "màn hình nhập thông tin cá nhân / thanh toán = ĐIỂM DỪNG: TỰ DỪNG và tóm tắt kết "
    "quả — KHÔNG hỏi 'có điền không', KHÔNG nhập số thẻ, KHÔNG thanh toán thật. Khi "
    "gọi ask_user, LUÔN kèm 2-3 options ngắn gọn, options[0] là đề xuất tốt nhất. "
    "Khi điều hướng (navigate), CHỈ tới URL trang web THẬT (vd traveloka.com, "
    "shopee.vn); KHÔNG điều hướng tới tên thành phố/địa điểm/từ khoá ('TP.HCM' "
    "KHÔNG phải URL) — địa điểm chỉ để GÕ vào ô tìm trên trang."
    "\n\nBẠN LÀ AI ĐIỀU PHỐI TRÌNH DUYỆT (browser-use): nhìn trang qua element ĐÁNH "
    "SỐ + ảnh, thao tác bằng click/gõ/cuộn theo số. Khi BỊ KẸT — thử 2-3 lần một "
    "bước mà KHÔNG tiến triển, hoặc gặp tình huống lạ/khó — ĐỪNG lặp lại vô ích: "
    "GỌI ask_expert để hỏi Agent Advisor (chuyên gia mạnh hơn, XEM được màn hình "
    "của bạn). Nêu RÕ bước đang làm + vấn đề + đã thử gì, rồi LÀM THEO lời khuyên."
)

_MODE_GUIDANCE = {
    "interactive": (
        "\n\nCHẾ ĐỘ TƯƠNG TÁC: bạn là AGENT — cứ chủ động làm tới. **`ask_user` là CỔNG CHO PHÉP của "
        "bạn**: khi cần một quyết định / sự đồng ý của người dùng (một chiều hay khứ hồi, ngân sách, "
        "**có chốt đơn & trả tiền không**, xin địa chỉ/thông tin…) thì HỎI — và **người dùng nói CÓ thì "
        "bạn ĐƯỢC làm điều đó** (kể cả đặt đơn, thanh toán). Những thứ nhỏ có default rõ → tự quyết, "
        "đừng hỏi vặt. KHÔNG có giới hạn cứng số câu hỏi: hỏi đúng lúc cần, gộp gọn, đừng pester."
    ),
    "autonomous": (
        "\n\nCHẾ ĐỘ TỰ LO (người dùng bận, muốn bạn TỰ LÀM HẾT): tự quyết MỌI lựa chọn bằng default hợp "
        "lý, KHÔNG hỏi từng bước. CHỈ `ask_user` khi: (a) cần sự CHO PHÉP cho việc hệ trọng (chốt đơn / "
        "thanh toán), (b) cần thông tin bạn không thể tự có (địa chỉ, số thẻ), hoặc (c) thật sự bế tắc. "
        "Người dùng nói CÓ thì cứ làm. Cuối cùng báo cáo các quyết định đã tự chọn."
    ),
}

# Not a behaviour cap — only a runaway-loop backstop. WHEN to ask is the agent's judgment
# (_MODE_GUIDANCE); ask_user is the user's permission gate, not something to ration.
_ASK_CAP = {"interactive": int(os.getenv("MAX_ASKS", "12")),
            "autonomous": int(os.getenv("MAX_ASKS_AUTO", "8"))}


def system_guidance(mode="interactive"):
    """Full extend_system_message for a mode (testable without building an Agent)."""
    mode = mode if mode in _MODE_GUIDANCE else "interactive"
    return build_system_guidance() + _BASE_GUIDANCE + _MODE_GUIDANCE[mode]


# ── Commit-button SAFETY VETO ──────────────────────────────────────────────
# Precise "place order" terms only (the irreversible commit — esp. COD "Đặt hàng"
# = a REAL order). Deliberately NOT "thanh toán"/"checkout"/"mua ngay" — those are
# navigation buttons we MUST be able to click; matching them would break the funnel.
_COMMIT_RE = re.compile(
    r"đặt\s*hàng|đặt\s*mua|đặt\s*đơn|hoàn\s*tất\s*(đơn|đặt)|dat\s*hang|"
    r"place\s*order|complete\s*(the\s*)?order|confirm\s*(your\s*)?order",
    re.IGNORECASE,
)

# A FINAL purchase-confirmation question ("đặt đơn này? Có/Không") is a SAFETY gate,
# not "over-asking" — it must NEVER be blocked by the per-task ask-cap. Matches the
# playbook's confirm wording ("Mình sắp đặt đơn… Đặt nhé?").
_CONFIRM_RE = re.compile(
    r"sắp\s*đặt|đặt\s*đơn|đặt\s*nhé|chốt\s*đơn|xác\s*nhận.{0,14}đặt|đồng\s*ý.{0,10}đặt|"
    # handoff gates (continue-to-checkout + keep-session-alive park) are the human-in-the-loop
    # bridge, NOT over-asking → also exempt from the per-task ask-cap:
    r"tới\s*trang\s*thanh\s*toán|tiếp\s*tục.{0,14}thanh\s*toán|giữ\s*phiên|đóng\s*phiên|"
    # ESSENTIAL delivery info the agent CANNOT fabricate (PII) — asking for it is mandatory,
    # not over-asking, so it must NEVER be blocked by the ask-cap (else the agent is stuck:
    # can't ask, can't invent an address → fails at the shipping form):
    r"địa\s*chỉ|giao\s*hàng|nhận\s*hàng|họ\s*tên|số\s*điện\s*thoại|sđt",
    re.IGNORECASE,
)

# The actual MONEY-SPEND confirmation. A user 'yes' to one of these (answer not negative) is the
# explicit permission that opens the place-order gate — the user's principle: "the agent may do
# anything once ask_user returns yes." Navigation asks ("tới trang thanh toán") are deliberately
# NOT here — only the real spend confirmation flips the gate.
_PAY_CONFIRM_RE = re.compile(
    r"chốt\s*đơn|trả\s*tiền|đặt\s*đơn|đặt\s*hàng|đặt\s*mua|place\s*order|pay\s*now|confirm.*pay",
    re.IGNORECASE,
)
_NEG_ANSWER_RE = re.compile(r"không|\bko\b|\bno\b|dừng|hu[ỷy]|cancel|stop|khoan|đừng", re.IGNORECASE)

# Sensitive-payment field detector — a CODE backstop (prose gates measured ~1/3 reliable) so the
# agent physically CANNOT type a card number / CVV into a field, even if a prompt slips. This is
# both the hard line and a real security feature to show: the agent refuses sensitive data.
_CARD_FIELD_RE = re.compile(
    r"card.?number|cardnumber|cc.?number|credit.?card|số\s*thẻ|cvv|cvc|security.?code|mã\s*thẻ|"
    r"card.?holder|expiry|expiration|ngày\s*hết\s*hạn",
    re.IGNORECASE,
)


async def _element_text(session, index):
    """Visible text + key attributes of the element at `index` (lowercased), for the
    commit-veto. Button labels live in CHILD text → use get_all_children_text. Best-effort."""
    try:
        node = await session.get_element_by_index(index)
    except Exception:
        return ""
    if node is None:
        return ""
    parts = []
    for getter in ("get_all_children_text", "get_meaningful_text_for_llm"):
        fn = getattr(node, getter, None)
        if callable(fn):
            try:
                parts.append(str(fn() or ""))
            except Exception:
                pass
    try:
        attrs = node.attributes or {}
        for k in ("aria-label", "value", "title", "name", "placeholder"):
            if attrs.get(k):
                parts.append(str(attrs[k]))
    except Exception:
        pass
    try:
        parts.append(str(getattr(node, "node_value", "") or ""))
    except Exception:
        pass
    return " ".join(parts).lower()


def build_tools(channel, *, ask_cap=3):
    """browser-use tool set bound to a channel, with a per-task ask cap."""
    tools = Tools()
    state = {"asks": 0, "experts": 0, "confirmed_pay": False}

    @tools.action(
        "Lấy PLAYBOOK (quy trình đã kiểm chứng) cho một tác vụ phổ biến. BẮT BUỘC "
        "gọi TRƯỚC khi thao tác trình duyệt nếu yêu cầu khớp một playbook."
    )
    async def load_playbook(name: str) -> str:
        print(f"\n📖 LOAD_PLAYBOOK >>> {name}\n", flush=True)
        return _load_playbook(name)

    @tools.action(
        "Hỏi người dùng khi cần quyết định / làm rõ / nới ràng buộc / bị kẹt. LUÔN "
        "kèm 'options' = 2-3 lựa chọn ngắn gọn; options[0] là đề xuất tốt nhất của "
        "bạn. Trả về câu trả lời của người dùng để bạn làm theo."
    )
    async def ask_user(question: str, options: list[str]) -> str:
        # ask_user is the user's PERMISSION GATE: a 'yes' here authorizes the agent to do what it
        # asked about (incl. paying / placing an order). `ask_cap` is ONLY a runaway-loop backstop
        # (high), NOT a ration on asking — and safety/essential asks (_CONFIRM_RE) are exempt entirely.
        if not _CONFIRM_RE.search(question or ""):
            state["asks"] += 1
            if state["asks"] > ask_cap:
                return ("(Bạn đã hỏi khá nhiều lần rồi — việc nhỏ thì tự quyết hợp lý và tiếp tục; chỉ "
                        "hỏi tiếp nếu THẬT SỰ cần một quyết định / sự cho phép của người dùng.)")
        answer = await channel.ask(question, list(options or []))
        # Record an AFFIRMATIVE answer to a real money-spend confirmation → opens the place-order
        # gate (the user's principle: agent may do anything once ask_user returns yes).
        if _PAY_CONFIRM_RE.search(question or "") and not _NEG_ANSWER_RE.search(answer or ""):
            state["confirmed_pay"] = True
            log.info("✅ User CONFIRMED payment → place-order gate open")
        return answer

    @tools.action(
        "Hỏi **Agent Advisor** — chuyên gia gỡ rối MẠNH HƠN, XEM được màn hình của bạn — khi bạn "
        "KẸT: đã thử 2-3 lần một bước mà KHÔNG tiến triển, hoặc gặp trang lạ/khó chưa rõ cách qua. "
        "PHẢI nêu RÕ: task_step = bạn đang cố làm gì (bước nào), problem = kẹt/lỗi gì, attempts = đã "
        "thử những gì. Trả về lời khuyên cụ thể — hãy LÀM THEO rồi tiếp tục, đừng lặp lại thao tác cũ."
    )
    async def ask_expert(task_step: str, problem: str, attempts: str, browser_session) -> str:
        state["experts"] += 1
        if state["experts"] > EXPERT_CAP:
            return ("(Đã hỏi Agent Advisor đủ số lần cho tác vụ này. TỰ QUYẾT theo gợi ý đã có và "
                    "TIẾP TỤC, đừng hỏi nữa.)")
        # surface the "AI asks a smarter AI" moment on the live page + /logs
        try:
            appstate.live_thought({"kind": "advisor", "n": appstate._live.get("step", 0),
                                   "goal": f"Đang tham khảo Agent Advisor để gỡ rối: {str(problem)[:90]}"})
        except Exception:
            pass
        log.info("🧑‍🏫 Đang tham khảo Agent Advisor để gỡ rối (step problem: %s)", str(problem)[:80])
        print(f"\n🧑‍🏫 ASK_EXPERT [{state['experts']}/{EXPERT_CAP}] "
              f"step={str(task_step)[:50]!r} problem={str(problem)[:60]!r}\n", flush=True)
        try:
            advice = await _consult_expert(browser_session, task_step, problem, attempts)
        except Exception as e:
            log.warning("Agent Advisor call failed", exc_info=True)
            return (f"(Agent Advisor tạm không phản hồi: {type(e).__name__}. Tự xoay xở: ĐỔI cách "
                    "thao tác — dùng picker thay vì gõ, click cả KHỐI thay vì nút nhỏ, cuộn/đợi rồi "
                    "thử lại — đừng lặp y hệt.)")
        print(f"💡 AGENT ADVISOR >>> {str(advice)[:220]}\n", flush=True)
        return f"[Agent Advisor khuyên]: {advice}" if advice else (
            "(Agent Advisor chưa đưa được lời khuyên rõ. Tự đổi cách thao tác, đừng lặp lại.)")

    @tools.action(
        "Điền TÀI KHOẢN ĐĂNG NHẬP đã cấu hình sẵn cho một site (vd 'uniqlo') vào form login ĐANG HIỆN "
        "trên trang. Gọi khi gặp form đăng nhập của site được hỗ trợ. Nó tự điền email/tên + mật khẩu "
        "(bạn KHÔNG thấy và KHÔNG cần biết giá trị) — sau đó bạn chỉ việc BẤM nút Đăng nhập/Login. "
        "KHÔNG dùng cho ô OTP / mã xác minh / CAPTCHA / số thẻ."
    )
    async def fill_login(site: str, browser_session) -> str:
        domain, cred = _match_login(site)
        if not cred:
            avail = ", ".join(_LOGINS.keys()) or "(chưa cấu hình site nào)"
            return (f"(Chưa cấu hình đăng nhập cho '{site}'. Site có sẵn: {avail}. Nếu site hiện tại "
                    "KHÔNG có sẵn tài khoản → DỪNG ở form login và báo người dùng, TUYỆT ĐỐI không tự gõ tay.)")
        user = str(cred.get("username") or cred.get("email") or "")
        pw = str(cred.get("password") or "")
        if not pw:
            return f"(Cấu hình đăng nhập cho '{domain}' thiếu mật khẩu — báo người dùng.)"
        js = _FILL_JS.replace("__U__", json.dumps(user)).replace("__P__", json.dumps(pw))
        try:
            res = await _eval_page(browser_session, js)
        except Exception as e:
            log.warning("fill_login eval failed", exc_info=True)
            return (f"(Chưa tự điền được tài khoản: {type(e).__name__}. Hãy chắc form đăng nhập đang hiện "
                    "rồi gọi lại; nếu vẫn không được, báo người dùng.)")
        log.info("🔐 fill_login site=%s → %s", domain, res)   # log the OUTCOME only — never the values
        if res == "NO_PASSWORD_FIELD":
            return ("Chưa thấy ô MẬT KHẨU trên trang. Hãy MỞ form đăng nhập trước (bấm 'Đăng nhập'/'Login', "
                    "hoặc chuyển sang đăng nhập bằng email–mật khẩu) rồi gọi lại fill_login.")
        what = ("email/tên đăng nhập + mật khẩu" if res == "FILLED_BOTH"
                else "mật khẩu (chưa thấy ô tên đăng nhập — kiểm tra rồi điền tên nếu cần)")
        return (f"✅ Đã tự điền {what} cho {domain}. Giờ BẤM nút 'Đăng nhập'/'Login' để vào. "
                "Sau đó nếu hiện OTP / CAPTCHA / 'xác minh đó là bạn' → DỪNG và báo người dùng (không tự giải).")

    # ── HARD SAFETY GATE (code, not prose): refuse clicking a final place-order button.
    # The actor must get a user "Đặt đơn" via ask_user first; this is the backstop since
    # prose gates measured only ~1/3 reliable. Wrapping tools.act intercepts EVERY click
    # before execution; only precise place-order text is blocked → never blocks navigation.
    _orig_act = tools.act

    # URLs where an unreadable click is treated as DANGEROUS (fail closed).
    _DANGER_URL = ("checkout", "/cart", "payment", "thanh-toan", "gio-hang", "/order")

    async def _guarded_act(action, browser_session, *a, **kw):
        _move_idx = None  # element to glide the cursor to before acting (click OR field-fill)
        try:
            dumped = action.model_dump(exclude_unset=True) if hasattr(action, "model_dump") else {}
            for name, params in (dumped or {}).items():
                nm = name.lower()
                if not (isinstance(params, dict) and "index" in params):
                    continue
                if "input" in nm or "type" in nm or "fill" in nm or "select" in nm:
                    # SENSITIVE-INFO GATE: never type a card number / CVV into a field. Blocks if the
                    # value looks like a card number (12–19 digits) OR the field is a card/CVV field.
                    val = str(params.get("text") or params.get("value") or "")
                    digits = re.sub(r"[\s\-]", "", val)
                    card_value = digits.isdigit() and 12 <= len(digits) <= 19
                    if card_value or (_CARD_FIELD_RE.search(await _element_text(browser_session, params["index"]))
                                      and any(ch.isdigit() for ch in val)):
                        log.warning("⛔ SENSITIVE-INFO GATE — refused to type card-like data, idx=%s", params.get("index"))
                        try:
                            appstate.live_thought({"n": appstate._live.get("step", 0), "kind": "step",
                                "goal": "🔒 Chặn an toàn: KHÔNG nhập thông tin nhạy cảm (số thẻ/CVV)"})
                        except Exception:
                            pass
                        return ActionResult(error=(
                            "[CHẶN AN TOÀN] Mình KHÔNG được phép nhập thông tin nhạy cảm (số thẻ / CVV). Hãy báo "
                            "người dùng nguyên văn: 'Mình không được phép nhận thông tin thẻ/nhạy cảm — vui lòng tự "
                            "thao tác khâu thanh toán qua link mình gửi.' rồi DỪNG. ĐỪNG gõ số thẻ vào ô."))
                    _move_idx = params["index"]   # field-fill → cursor walks to this field (like a human)
                elif "click" in nm:
                    txt = await _element_text(browser_session, params["index"])
                    log.info("🔎 click[idx=%s] target text=%r", params.get("index"), txt[:100])  # veto integration log
                    _move_idx = params["index"]
                    # PAY/PLACE-ORDER GATE (the real money-spend). The user's principle: the agent may
                    # do anything once ask_user returns yes → so allow the place-order click ONLY after
                    # a pay-confirmation yes (state["confirmed_pay"]); otherwise send it back to ask first.
                    # (Not a hard cage: it just enforces "get the user's yes before spending money.")
                    if txt and _COMMIT_RE.search(txt):
                        if not state.get("confirmed_pay"):
                            log.warning("⛔ PAY GATE — place-order click before user confirmation, idx=%s text=%r",
                                        params.get("index"), txt[:80])
                            try:
                                appstate.live_thought({"n": appstate._live.get("step", 0), "kind": "step",
                                    "goal": "⛔ Cần người dùng xác nhận trả tiền trước khi đặt đơn"})
                            except Exception:
                                pass
                            return ActionResult(error=(
                                "[CỔNG THANH TOÁN] Đây là nút ĐẶT ĐƠN / TRẢ TIỀN (tiêu tiền THẬT). Gọi `ask_user` "
                                "xác nhận trước: 'Chốt đơn và trả tiền {tóm tắt}? [Có / Không]'. Người dùng nói CÓ "
                                "→ bấm lại nút này (sẽ được phép); nói KHÔNG → DỪNG và báo lại."))
                        log.info("✅ place-order ALLOWED — user confirmed payment, idx=%s", params.get("index"))
        except Exception:
            log.warning("commit-veto check errored; allowing action", exc_info=True)
        # Virtual cursor: glide to the target (click OR field) before executing, so the live
        # view / recording shows a human-like move + action. Cosmetic; never blocks.
        if _move_idx is not None:
            await agent_cursor.move_to_index(browser_session, _move_idx, click=True)
        return await _orig_act(action, browser_session, *a, **kw)

    tools.act = _guarded_act
    return tools


def build_llm(model=None):
    # Browse brain. gpt-5 (reasoning, low effort) is more CONSISTENT than gpt-4o on
    # hard flows; gpt-4o stays as the chat/routing front door only.
    model = model or os.environ.get("POC_MODEL", "openai/gpt-5")
    # browser-use's ChatOpenAI defaults max_completion_tokens=4096 — too low (a
    # reasoning model's thinking eats the budget → empty/truncated JSON). Roomy cap.
    kwargs = {"max_completion_tokens": int(os.getenv("BROWSE_MAX_TOKENS", "16000"))}
    if "gemini" in model:
        # Gemini's OpenAI-compat endpoint 400s on the frequency_penalty ChatOpenAI
        # sends by default (=0.3) → drop it.
        kwargs["frequency_penalty"] = None
    if "gpt-5" in model:
        # gpt-5 is a REASONING model: mark it so ChatOpenAI sends reasoning_effort and
        # DROPS temperature + frequency_penalty (gpt-5 rejects those). 20k output cap.
        kwargs["reasoning_models"] = ["gpt-5"]
        kwargs["reasoning_effort"] = os.getenv("GPT5_EFFORT", "low")
        kwargs["max_completion_tokens"] = int(os.getenv("BROWSE_MAX_TOKENS", "20000"))
    if "minimax" in model:
        # MaaS does NOT enforce response_format=json_schema for MiniMax (it returns the action
        # as plain TEXT → browser-use's content-parse fails, the "0/3" probe result). Put the
        # schema in the system prompt AND drop response_format — the exact combo verified to
        # yield valid AgentOutput JSON (probe_minimax.py test B). MiniMax is text-only → run
        # it with USE_VISION=false (DOM-only). Reasoning model → roomy token cap for any <think>.
        kwargs["add_schema_to_system_prompt"] = True
        kwargs["dont_force_structured_output"] = True
        kwargs["max_completion_tokens"] = int(os.getenv("BROWSE_MAX_TOKENS", "20000"))
    return ChatOpenAI(model=model, base_url=MAAS_BASE, api_key=os.environ["MAAS_API_KEY"], **kwargs)


# ── Agent Advisor: a gpt-5 reasoning expert the actor consults when stuck ──────
# It SEES the current screenshot (vision) and reads the common-stuck KB, mirroring
# how Claude Code calls its own advisor. gpt-5 only on /v1/responses (reasoning).
# effort=low (~3-4s, still sees the screen) — NOT high (~30s, freezes the demo).
EXPERT_MODEL = os.getenv("EXPERT_MODEL", "openai/gpt-5")
EXPERT_EFFORT = os.getenv("EXPERT_EFFORT", "low")
EXPERT_CAP = int(os.getenv("EXPERT_CAP", "3"))
# When the AUTO stuck-loop detector fires we ESCALATE THE ACTOR (not just inject
# advice): the stronger vision model takes the wheel for this many steps, then we
# hand control back to the fast actor. gpt-5 is ~25s/step → keep this small.
EXPERT_STEPS = int(os.getenv("EXPERT_STEPS", "2"))

_ADVISOR_SYS = (
    "Bạn là **Agent Advisor** — chuyên gia gỡ rối tự-động-hoá-trình-duyệt. Bạn cố vấn cho một agent "
    "**gpt-4o đang ĐIỀU KHIỂN TRÌNH DUYỆT THẬT** qua thư viện browser-use: nó NHÌN trang dưới dạng danh "
    "sách element tương tác có ĐÁNH SỐ (index) kèm ảnh chụp màn hình, và HÀNH ĐỘNG bằng "
    "click / input / scroll / select_dropdown / send_keys theo index. Nó vừa BỊ KẸT và cần bạn chỉ cách gỡ. "
    "Bạn ĐƯỢC XEM ảnh màn hình hiện tại của nó.\n\n"
    "QUY TRÌNH:\n"
    "1) TRƯỚC TIÊN đối chiếu với 'CÁC LỖI KẸT THƯỜNG GẶP' bên dưới — nếu khớp, đưa luôn cách gỡ đã kiểm chứng.\n"
    "2) Nếu không khớp, suy luận từ ảnh + mô tả.\n"
    "Trả lời: **1-3 BƯỚC CỤ THỂ, NGẮN GỌN, hành-động-được** (nói rõ click/gõ/cuộn CÁI GÌ, theo thứ tự) — "
    "viết cho gpt-4o làm theo ngay. KHÔNG lý thuyết dài. Tiếng Việt.\n\n"
    "=== CÁC LỖI KẸT THƯỜNG GẶP (playbook common-stuck) ===\n{kb}"
)


async def _consult_expert(browser_session, task_step, problem, attempts):
    """Snapshot the screen + ask Agent Advisor (gpt-5, vision) for a concrete fix."""
    img_b64, url = None, ""
    try:
        os.makedirs(_PREVIEW_DIR, exist_ok=True)
        path = os.path.join(_PREVIEW_DIR, "expert.jpg")
        await browser_session.take_screenshot(path=path, format="jpeg", quality=70)
        with open(path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
    except Exception:
        log.warning("expert screenshot failed", exc_info=True)
    try:
        url = await browser_session.get_current_page_url()
    except Exception:
        url = ""

    sys_prompt = _ADVISOR_SYS.format(kb=_load_playbook("common-stuck"))
    user_text = (
        f"Trang hiện tại: {url or '(không rõ)'}\n"
        f"MÌNH (gpt-4o) ĐANG LÀM: {task_step}\n"
        f"VẤN ĐỀ GẶP PHẢI: {problem}\n"
        f"ĐÃ THỬ: {attempts}\n"
        "Cho mình cách gỡ cụ thể để đi tiếp."
    )
    content = [{"type": "input_text", "text": user_text}]
    if img_b64:
        content.append({"type": "input_image", "image_url": f"data:image/jpeg;base64,{img_b64}"})

    def _call():
        client = OpenAI(base_url=MAAS_BASE, api_key=os.environ["MAAS_API_KEY"])
        r = client.responses.create(
            model=EXPERT_MODEL,
            instructions=sys_prompt,
            input=[{"role": "user", "content": content}],
            max_output_tokens=2000,
            reasoning={"effort": EXPERT_EFFORT},
        )
        return (getattr(r, "output_text", "") or "").strip()

    return await asyncio.to_thread(_call)


def local_session():
    """Attach to a logged-in debug Chrome on :9222 (headed, watchable)."""
    return BrowserSession(cdp_url="http://localhost:9222")


def container_session():
    """Browser for the container (AgentBase). In prod we run under Xvfb (a virtual
    display) → DISPLAY is set → launch NON-headless. Real (non-headless) rendering
    both DODGES Traveloka's headless bot-block (429/captcha) AND drives the date-picker
    reliably — proven by the headed runs (2/2 reached payment; plain headless 0/2,
    blocked). Falls back to headless if no DISPLAY. UA is spoofed to plain Chrome
    either way (headless UA is itself a tell). --disable-dev-shm-usage so Chrome
    doesn't crash on a small /dev/shm (AgentBase may not allow --shm-size).

    FRESH GUEST profile each run — no stored cookies/profile. When a site needs login,
    the agent does a REAL login via the fill_login tool (test-account creds from env).
    Cookie injection was removed: captured Google/Akamai sessions are non-portable (they
    don't authenticate when copied into another browser/IP — proven empirically)."""
    headless = not os.environ.get("DISPLAY")
    args = ["--disable-dev-shm-usage", "--no-sandbox",
            "--window-size=1920,1080", "--lang=vi-VN,vi"]
    if not headless:
        args.append("--start-maximized")
    return BrowserSession(
        headless=headless, chromium_sandbox=False,
        executable_path=os.environ.get("CHROME_BIN", "/usr/bin/chromium"),
        user_agent=_STEALTH_UA, args=args,
    )


def headed_session():
    """Visible Chrome window (headless=False) so a human can WATCH the agent live
    on a desktop that has a DISPLAY. Same binary as container_session, just shown.
    EPHEMERAL/COLD: a fresh profile, killed at run end — NOT logged in to anything."""
    return BrowserSession(
        headless=False, chromium_sandbox=False,
        executable_path=os.environ.get("CHROME_BIN", "/usr/bin/chromium"),
        args=["--disable-dev-shm-usage", "--no-sandbox", "--start-maximized"],
    )


def warm_session(user_data_dir=None):
    """Headed Chrome on a PERSISTENT, pre-logged-in profile — the fix for "cold
    session, login never sticks". You log into Shopee ONCE in a dedicated profile
    dir on disk; browser-use copies that dir's `Default/` (cookies + Local State)
    into a temp working copy each run, so every run starts ALREADY LOGGED IN and the
    original profile is never corrupted. The agent NEVER types a password.

    One-time login (run it yourself, then CLOSE that Chrome before a run):
        google-chrome --user-data-dir=<dir> https://shopee.vn
    A "profile is locked" error at run start = a Chrome is still open on <dir>.
    Use a DEDICATED dir (not your main ~/.config/google-chrome) for the throwaway acct."""
    d = (user_data_dir or os.environ.get("WARM_PROFILE_DIR")
         or os.path.expanduser("~/.config/zalo-agent-profile"))
    # Drive the profile DIRECTLY (no temp-copy). browser-use copies user_data_dir to a temp dir
    # UNLESS the path contains 'browser-use-user-data-dir-' (profile.py:_copy_profile) — and that
    # copy DROPS keyring-encrypted cookies → a half-valid session (page loads but the cart API
    # 401s → "không tải được giỏ hàng, đăng nhập lại"). A symlink whose NAME carries that marker
    # makes browser-use skip the copy and use the REAL logged-in profile, so cart/checkout work.
    if d and "browser-use-user-data-dir-" not in d:
        link = os.path.join(os.path.dirname(os.path.normpath(d)),
                            "browser-use-user-data-dir-" + os.path.basename(os.path.normpath(d)))
        try:
            if not os.path.lexists(link):
                os.symlink(os.path.abspath(d), link)
            if os.path.realpath(link) == os.path.realpath(d):
                d = link
        except Exception:
            pass
    return BrowserSession(
        headless=False, chromium_sandbox=False,
        executable_path=os.environ.get("CHROME_BIN", "/usr/bin/chromium"),
        user_data_dir=d,
        args=["--disable-dev-shm-usage", "--no-sandbox", "--start-maximized"],
    )


# Real Chrome UA — the default headless UA says "HeadlessChrome/<v>", an instant
# bot tell (Traveloka served 429+captcha to headless). Match the actual Chrome
# major version (override CHROME_UA env if the binary differs).
_STEALTH_UA = os.getenv(
    "CHROME_UA",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36",
)


def stealth_session():
    """Headless (prod-shaped) but with the HeadlessChrome UA tell removed. browser-use
    already passes --headless=new + --disable-blink-features=AutomationControlled, so
    the remaining cheap tell is the UA string — spoof it to plain Chrome. Experiment:
    is UA-spoof enough to pass Traveloka's bot check without a full Xvfb display?"""
    return BrowserSession(
        headless=True, chromium_sandbox=False,
        executable_path=os.environ.get("CHROME_BIN", "/usr/bin/chromium"),
        user_agent=_STEALTH_UA,
        args=["--disable-dev-shm-usage", "--no-sandbox",
              "--window-size=1920,1080", "--lang=vi-VN,vi"],
    )


def build_agent(task, channel, *, mode="interactive", model=None,
                browser_session=None, use_vision=True, cancel_event=None):
    mode = mode if mode in _MODE_GUIDANCE else "interactive"
    task = _neutralize_dotted(task)
    # DOM-only override (for text-only brains like MiniMax): USE_VISION=false → no screenshots.
    if os.getenv("USE_VISION", "").strip().lower() in ("false", "0", "no", "off"):
        use_vision = False
    _model = model or os.environ.get("POC_MODEL", "openai/gpt-5")
    kwargs = {}
    # llm_timeout is set UNCONDITIONALLY (not only for a gpt-5 base model): the stuck
    # escalation can swap the gpt-5 expert in as the ACTOR mid-run, and gpt-5 reasons
    # slower (the default ~75s cuts it off mid-thought → the "no action" symptom). A
    # roomy ceiling is harmless for the fast gpt-4o actor (it returns in seconds).
    kwargs["llm_timeout"] = int(os.getenv("LLM_TIMEOUT", "150"))
    if cancel_event is not None:
        # browser-use checks this several times PER step (before/after model
        # output + after actions) → /huỷ halts the agent mid-task instead of
        # leaving it to run to its own timeout while still emitting screenshots.
        async def _should_stop():
            return cancel_event.is_set()
        kwargs["register_should_stop_callback"] = _should_stop
    # Resilience: if the primary brain hits a provider/parse error, browser-use
    # switches to this fallback for the rest of the run. gpt-4o-mini is cheap +
    # reliable. Set FALLBACK_MODEL=none to disable.
    fb = os.getenv("FALLBACK_MODEL", "openai/gpt-4o-mini")
    if fb and fb.lower() not in ("none", "off", ""):
        kwargs["fallback_llm"] = build_llm(fb)
    # Native browser-use knobs (no fork). use_judge OFF by default: it's not our success
    # bar (we stop before paying) and costs an extra LLM call + misleading FAIL verdicts.
    # tool-call examples ON: help a weaker actor emit valid action-JSON. Both env-toggleable for A/B.
    _use_judge = os.getenv("USE_JUDGE", "false").lower() == "true"
    _tool_examples = os.getenv("TOOL_EXAMPLES", "true").lower() == "true"
    log.info("🧠 build_agent: model=%s · mode=%s · use_vision=%s · use_judge=%s · tool_examples=%s · dom_max=%s · vision=%s",
             _model, mode, use_vision, _use_judge, _tool_examples,
             os.getenv("DOM_MAX", "15000"), os.getenv("VISION_DETAIL", "low"))
    agent = Agent(
        task=task,
        llm=build_llm(model),
        browser_session=browser_session or local_session(),
        tools=build_tools(channel, ask_cap=_ASK_CAP[mode]),
        use_vision=use_vision,
        # Slim the per-step input so a reasoning brain (gpt-5) thinks faster + stays
        # under the LLM timeout: smaller DOM (default 40000) + low-detail screenshot.
        max_clickable_elements_length=int(os.getenv("DOM_MAX", "15000")),
        vision_detail_level=os.getenv("VISION_DETAIL", "low"),
        max_actions_per_step=3,
        # More room to TRY–FAIL–RECOVER before browser-use terminates the run (default 5).
        # The agent should be able to stumble (misclick → login popup) and still find its way
        # out (fill_login → undo → continue) instead of being cut off mid-recovery.
        max_failures=int(os.getenv("MAX_FAILURES", "8")),
        step_timeout=600,  # let a blocking ask_user wait for a human reply
        extend_system_message=system_guidance(mode),
        use_judge=_use_judge,
        include_tool_call_examples=_tool_examples,
        **kwargs,
    )
    # browser-use auto-enables coordinate-clicking for 'gemini-3-pro' but its substring check
    # MISSES 'gemini-3.1-pro' (the ".1" breaks it) → force it for any gemini-3.x (the model IS
    # coordinate-capable). Coordinate (x,y) clicks are more robust than index clicks against the
    # silent-no-op problem. Env COORD_CLICK=false to disable.
    if "gemini-3" in _model and os.getenv("COORD_CLICK", "true").lower() == "true":
        try:
            agent.tools.set_coordinate_clicking(True)
            log.info("🖱️ Forced coordinate-clicking ON for %s", _model)
        except Exception:
            log.warning("could not force coordinate-clicking for %s", _model, exc_info=True)
    return agent


# Internal-architecture terms that must NEVER appear in a user-facing caption.
_INTERNAL_RE = re.compile(
    r"playbook|load_playbook|ask_user|do_browser_task|browser[_-]use|MaaS|qwen|"
    r"gpt-|system prompt|standard procedure|mandatory|tool\b|công cụ nội bộ",
    re.IGNORECASE,
)


def _step_caption(agent, n):
    """User-facing caption for a step. Hide internal-mechanics goals (don't leak
    the playbook system / tool names / model / architecture)."""
    goal = ""
    try:
        thoughts = agent.history.model_thoughts()
        if thoughts:
            goal = (getattr(thoughts[-1], "next_goal", "") or "").strip()
    except Exception:
        goal = ""
    goal = goal.split("\n")[0][:140]
    if goal and _INTERNAL_RE.search(goal):
        goal = ""  # internal mechanics → don't show it
    return f"🖥️ Bước {n}" + (f": {goal}" if goal else ": đang thao tác…")


def _is_blank(path):
    """True if the screenshot is near-uniform (blank/black browser — no real page
    yet). Used to skip the useless black frames at the very start."""
    try:
        from PIL import Image, ImageStat
        return ImageStat.Stat(Image.open(path).convert("L")).stddev[0] < 8
    except Exception:
        return False


def _build_gif(frames, out_path, width=720):
    """Compile step screenshots into one replay GIF (Pillow)."""
    from PIL import Image
    imgs = []
    for f in frames:
        try:
            im = Image.open(f).convert("RGB")
            im = im.resize((width, max(1, int(im.height * width / im.width))))
            imgs.append(im)
        except Exception:
            continue
    if len(imgs) < 2:
        return None
    imgs[0].save(out_path, save_all=True, append_images=imgs[1:],
                 duration=800, loop=0, optimize=True)
    return out_path


def _fmt_actions(acts):
    """Short, human action labels for the live UI:
    {'click_element_by_index':{'index':5}} → 'click(5)'."""
    out = []
    for a in acts or []:
        if not isinstance(a, dict):
            continue
        name = next(iter(a.keys()), "?")
        p = a.get(name)
        short = name.replace("_element_by_index", "").replace("_text", "").replace("_dropdown", "")
        val = ""
        if isinstance(p, dict):
            val = p.get("index", p.get("text", p.get("url", p.get("query", p.get("name", "")))))
        elif p not in (None, ""):
            val = p
        out.append(f"{short}({str(val)[:28]})" if val not in ("", None) else short)
    return out[:5]


# Redact internal mechanics (playbook / model names) from user-facing thoughts —
# viewers/judges must not see "load the flight playbook" or "gpt-4o".
def _clean(s):
    s = s or ""
    s = re.sub(r"load[_ ]?playbook\s*\(?[^)\n]*\)?", "prepare the booking procedure", s, flags=re.I)
    s = re.sub(r"\b(the\s+'?[\w]+'?\s+)?playbooks?\b", "procedure", s, flags=re.I)
    s = re.sub(r"\b(gpt-?5[\w.\-]*|gpt-?4o[\w.\-]*|qwen[\w.\-]*|gemini[\w.\-]*|openai/[\w.\-]+)\b",
               "the engine", s, flags=re.I)
    for secret in _SECRET_VALUES:                  # never leak a configured password into the live view
        if secret and secret in s:
            s = s.replace(secret, "•••")
    return s.strip()


# Auto-stuck detection: the actor loops on hard widgets (Traveloka date-picker)
# WITHOUT realising it should ask for help, so we trigger the Agent Advisor
# ourselves off repeated failure-evals (a self-report trigger never fires here).
_STUCK_RE = re.compile(r"fail|unable|stale|error|issue|repeat|loop|retry|couldn|cannot|incorrect|"
                       r"reset|wrong|keeps|instead|stuck|không|sai|lặp", re.I)
STUCK_TRIGGER = int(os.getenv("STUCK_TRIGGER", "3"))      # N stuck-ish steps in a row → consult
MAX_AUTO_CONSULTS = int(os.getenv("MAX_AUTO_CONSULTS", "2"))


def _stuck_key(ev):
    """Normalised eval signature (digits removed) to detect a REPEATING eval — the
    most reliable stuck signal: the actor narrating the same failure over and over
    ('date keeps resetting to June 7…' identical for 5 steps), regardless of wording."""
    return re.sub(r"\d+", "#", (ev or "").lower()).strip()[:70]


async def run_task(task, channel, *, mode="interactive", model=None, browser_session=None,
                   use_vision=True, max_steps=40, send_image=None, send_gif=None,
                   cancel_event=None, interrupt_key=None):
    """Run a browser task. Every step: push a SANITIZED reasoning step (eval/memory/
    goal) to state.live_* for the /live page, and AUTO-detect stuck-loops → ESCALATE
    the ACTOR to the stronger vision model for a few steps (the actor won't self-
    trigger), capping the escalations. send_image streams a legacy per-step screenshot;
    cancel_event halts the agent + previews (wired for /huỷ)."""
    session = browser_session or local_session()
    interrupt_key = interrupt_key or getattr(channel, "thread_id", None)  # who can "chen ngang" this task
    agent = build_agent(task, channel, mode=mode, model=model,
                        browser_session=session, use_vision=use_vision,
                        cancel_event=cancel_event)
    os.makedirs(_PREVIEW_DIR, exist_ok=True)
    frames = []
    # Point-1 escalation state: capture the FAST actor (gpt-4o) so we can restore it
    # after the stronger gpt-5 actor has driven the hard step(s). The expert LLM is
    # built lazily on first escalation, so a clean run never pays to construct it.
    fast_llm = agent.llm
    _expert = {"llm": None}

    def _expert_llm():
        if _expert["llm"] is None:
            _expert["llm"] = build_llm(EXPERT_MODEL)
        return _expert["llm"]

    counter = {"n": 0, "stuck": 0, "consults": 0, "last_ev": "",
               "escalated": False, "esc_until": 0}
    try:
        appstate.live_begin(task=task, mode=mode, max_steps=max_steps,
                            model=(model or os.environ.get("POC_MODEL", "openai/gpt-4o")),
                            interrupt_key=interrupt_key)
    except Exception:
        pass

    async def on_step_end(ag):
        if cancel_event is not None and cancel_event.is_set():
            return
        counter["n"] += 1
        n = counter["n"]

        # Point 1 — RESTORE the fast actor once the expert has driven the hard step(s).
        if counter["escalated"] and n >= counter["esc_until"]:
            try:
                ag.llm = fast_llm
            except Exception:
                pass
            counter["escalated"] = False
            counter["stuck"] = 0           # give the fast actor a clean slate
            log.info("↩️ Trả quyền điều khiển lại cho model nhanh sau bước khó @ step %s", n)

        ev = goal = ""
        try:  # push the SANITIZED reasoning step to the live UI (no raw actions)
            th = ag.history.model_thoughts()
            last = th[-1] if th else None
            ev = (getattr(last, "evaluation_previous_goal", "") or "") if last else ""
            mem = (getattr(last, "memory", "") or "") if last else ""
            goal = (getattr(last, "next_goal", "") or "") if last else ""
            appstate.live_thought({"n": n, "kind": "step",
                                   "eval": _clean(ev)[:240], "memory": _clean(mem)[:240],
                                   "goal": _clean(goal)[:240]})
        except Exception:
            pass

        # Capture last-good URL + a freeze frame EVERY step so the final handoff always has a
        # real link + a non-black screen, even if the run dies before the end-of-run capture
        # (e.g. browser-use resets the session after consecutive failures → about:blank).
        try:
            appstate.set_live_url(await session.get_current_page_url())
        except Exception:
            pass
        try:
            _lp = os.path.join(_PREVIEW_DIR, "live.jpg")
            await session.take_screenshot(path=_lp, format="jpeg", quality=70)
            with open(_lp, "rb") as _fh:
                appstate.set_final_frame(_fh.read())
        except Exception:
            pass

        # ── Point 1: AUTO-escalate the ACTOR on a detected stuck-loop ──────────────
        # Don't just inject advice the weak actor must still EXECUTE (a grounding-stuck
        # actor can't act on "click the green button" if it can't locate it). Instead
        # HAND THE WHEEL to the stronger vision model for the hard step(s): browser-use
        # reads self.llm fresh each step (get_model_output), so swapping ag.llm takes
        # effect on the very next step — the same mechanism as its fallback_llm switch.
        # Honest multi-agent escalation (router → specialist), capped, then restored.
        try:
            ev_key = _stuck_key(ev)
            repeating = bool(ev_key) and ev_key == counter["last_ev"]   # same eval as last step
            counter["last_ev"] = ev_key
            stuck_now = repeating or bool(ev and _STUCK_RE.search(ev))
            counter["stuck"] = counter["stuck"] + 1 if stuck_now else 0
            if (counter["stuck"] >= STUCK_TRIGGER and counter["consults"] < MAX_AUTO_CONSULTS
                    and not counter["escalated"]):
                counter["stuck"] = 0
                counter["consults"] += 1
                try:
                    ag.llm = _expert_llm()                  # the stronger actor takes over
                    counter["escalated"] = True
                    counter["esc_until"] = n + EXPERT_STEPS
                    try:
                        ag.token_cost_service.register_llm(ag.llm)  # mirror fallback bookkeeping
                    except Exception:
                        pass
                    appstate.live_thought({"n": n, "kind": "advisor",
                        "goal": "Phát hiện bước khó — Agent Advisor (chuyên gia mạnh hơn) tiếp quản, thao tác trực tiếp"})
                    log.info("🧑‍🏫 ESCALATE actor → %s for %s step(s) from step %s (stuck)",
                             EXPERT_MODEL, EXPERT_STEPS, n + 1)
                    # Short SITUATIONAL note to the NOW-stronger actor — state, not a crutch.
                    ag.message_manager._add_context_message(UserMessage(content=(
                        f"⚠️ Bước trước bị KẸT (lặp {STUCK_TRIGGER} lần không tiến triển: {_clean(ev)[:150]}). "
                        "Bạn — chuyên gia mạnh hơn — đang TRỰC TIẾP điều khiển bước này. ĐÁNH GIÁ LẠI màn hình rồi "
                        "ĐỔI cách thao tác: cuộn element vào giữa rồi click, hoặc click cả thẻ/khối thay vì nút nhỏ, "
                        "hoặc chọn đúng element khác. TUYỆT ĐỐI không lặp lại y hệt thao tác cũ.")))
                except Exception:
                    counter["escalated"] = False
                    log.warning("escalation (model swap) failed at step %s", n, exc_info=True)
        except Exception:
            log.warning("auto-escalation check failed at step %s", n, exc_info=True)

        if send_image:  # optional legacy per-step screenshot stream
            try:
                path = os.path.join(_PREVIEW_DIR, f"f{n:03d}.jpg")
                await session.take_screenshot(path=path, format="jpeg", quality=60)
                if _is_blank(path):
                    return
                frames.append(path)
                await asyncio.to_thread(send_image, path, _step_caption(ag, n))
            except Exception:
                log.warning("preview step %s failed", n, exc_info=True)

    _cursor_shown = {"done": False}

    async def on_step_start(ag):
        # Show the virtual cursor as soon as the browser is up (first step, before the
        # first action) → visible from the blank page on. Idempotent + cosmetic.
        if not _cursor_shown["done"]:
            _cursor_shown["done"] = True
            await agent_cursor.show(session)
        # CHEN NGANG: drain user interrupts queued for this task → inject so the agent re-plans.
        if interrupt_key is not None:
            try:
                for text in interrupts.INTERRUPTS.drain(interrupt_key):
                    log.info("⚡ CHEN NGANG injected: %r", text[:120])
                    # add_new_task = PERSISTENT <follow_up_user_request> appended to task+history;
                    # survives prepare_step_state's context_messages.clear() (which silently drops
                    # _add_context_message), so the agent ACTUALLY sees it. Use the message-manager
                    # method (NOT Agent.add_new_task — that recreates the eventbus, unsafe mid-run).
                    mm = getattr(ag, "_message_manager", None) or getattr(ag, "message_manager", None)
                    if mm is not None:
                        mm.add_new_task(
                            f"NGƯỜI DÙNG CHEN NGANG (yêu cầu bổ sung giữa chừng): {text}. Hãy TIẾP NHẬN và "
                            "làm THÊM yêu cầu này — tự quyết hợp lý là xen vào NGAY hay làm sau khi xong việc "
                            "đang dở — rồi cập nhật kế hoạch. Vẫn giữ MỌI cổng an toàn (hỏi phân loại còn "
                            "thiếu, xác nhận cuối trước khi đặt, KHÔNG nhập thẻ).")
                    try:
                        appstate.live_thought({"n": appstate._live.get("step", 0), "kind": "step",
                            "goal": f"⚡ Nhận yêu cầu chen ngang: {_clean(text)[:80]}"})
                    except Exception:
                        pass
            except Exception:
                log.warning("interrupt drain failed", exc_info=True)

    try:
        history = await asyncio.wait_for(
            agent.run(max_steps=max_steps, on_step_start=on_step_start,
                      on_step_end=on_step_end), timeout=TASK_TIMEOUT)
    except BaseException:
        try:
            appstate.live_end(None)
        except Exception:
            pass
        raise
    # Final handoff: BEFORE the browser/loop closes, capture WHERE the agent stopped — a final
    # screenshot + the current URL — and push both to the chat + freeze /live on that frame.
    # Otherwise the session dies when asyncio.run() returns and the live feed just goes black
    # (no stop-screen, no link for the user to continue from).
    final_url = ""
    if not (cancel_event and cancel_event.is_set()):
        try:
            final_url = (await session.get_current_page_url()) or ""
        except Exception:
            final_url = ""
        try:
            fpath = os.path.join(_PREVIEW_DIR, "final.jpg")
            await session.take_screenshot(path=fpath, format="jpeg", quality=80)
            try:
                with open(fpath, "rb") as fh:
                    appstate.set_final_frame(fh.read())          # freeze /live on the stop screen
            except Exception:
                pass
            if send_image:
                cap = "🏁 Màn hình Agent dừng tại đây."
                if final_url:
                    cap += f"\n🔗 Mở để xem / thao tác tiếp:\n{final_url}"
                await asyncio.to_thread(send_image, fpath, cap)
        except Exception:
            log.warning("final handoff capture failed", exc_info=True)
    try:
        appstate.live_end((history.final_result() or "").strip() or None, url=final_url)
    except Exception:
        pass

    if send_gif and len(frames) >= 2 and not (cancel_event and cancel_event.is_set()):
        try:
            gif = _build_gif(frames, os.path.join(_PREVIEW_DIR, "replay.gif"))
            if gif:
                await asyncio.to_thread(send_gif, gif)
        except Exception:
            log.warning("gif build/send failed", exc_info=True)
    return history
