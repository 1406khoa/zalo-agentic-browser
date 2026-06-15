"""Tool registry for the Zalo AI bot (OpenAI function-calling).

SECURITY: every tool is hard-scoped to the CURRENT group. `thread_id` is always
supplied by the caller (the listener), NEVER by the model or user — so a tool can
only ever read the group the message came from. This preserves multi-group
isolation no matter what the model is tricked into asking.
"""
import ast
import re
import operator
from collections import Counter
from datetime import datetime, timezone, timedelta

HISTORY_FETCH = 100  # how many recent messages tools may scan

_URL_RE = re.compile(r"https?://[^\s]+")


# ---- shared history fetch (scoped to thread_id) --------------------------

def _fetch(bot, thread_id):
    msgs = []
    try:
        g = bot.getRecentGroup(thread_id)
        msgs = (g.get("groupMsgs") if hasattr(g, "get") else None) or []
    except Exception:
        msgs = []
    items = []
    for m in msgs:
        d = dict(m) if hasattr(m, "keys") else {}
        c = d.get("content")
        if not isinstance(c, str) or not c.strip():
            continue
        items.append({
            "name": d.get("dName") or str(d.get("uidFrom") or "?"),
            "text": c.strip(),
            "ts": int(d["ts"]) if str(d.get("ts", "")).isdigit() else 0,
        })
    items.sort(key=lambda x: x["ts"])
    return items[-HISTORY_FETCH:]


def _lines(items, limit):
    return "\n".join(f"- {it['name']}: {it['text']}" for it in items[:limit])


# ---- tool implementations (return human-readable strings) ----------------

def t_search(bot, thread_id, keyword="", limit=25):
    kw = (keyword or "").lower().strip()
    if not kw:
        return "Cần một từ khoá để tìm."
    hits = [it for it in _fetch(bot, thread_id) if kw in it["text"].lower()]
    if not hits:
        return f"Không thấy tin nào chứa '{keyword}' trong các tin gần đây."
    return f"Tìm thấy {len(hits)} tin chứa '{keyword}':\n" + _lines(hits, int(limit or 25))


def t_recent(bot, thread_id, count=30):
    try:
        count = max(1, min(int(count), HISTORY_FETCH))
    except (TypeError, ValueError):
        count = 30
    items = _fetch(bot, thread_id)[-count:]
    if not items:
        return "Chưa có tin nhắn nào trong nhóm."
    return f"{len(items)} tin gần nhất:\n" + _lines(items, count)


def t_count(bot, thread_id):
    items = _fetch(bot, thread_id)
    c = Counter(it["name"] for it in items)
    if not c:
        return "Chưa có dữ liệu để thống kê."
    return "Số tin theo người (trong các tin gần đây):\n" + \
        "\n".join(f"- {n}: {k} tin" for n, k in c.most_common())


def t_by_user(bot, thread_id, name="", limit=30):
    nm = (name or "").lower().strip()
    if not nm:
        return "Cần tên người để lọc."
    hits = [it for it in _fetch(bot, thread_id) if nm in it["name"].lower()]
    if not hits:
        return f"Không thấy tin nào của '{name}' trong các tin gần đây."
    return f"Tin của '{name}':\n" + _lines(hits, int(limit or 30))


def t_group_info(bot, thread_id):
    try:
        g = bot.fetchGroupInfo(thread_id)
        d = dict(g) if hasattr(g, "keys") else {}
        info = d
        for k in (str(thread_id), "gridInfoMap"):
            if isinstance(d.get(k), dict):
                info = d[k]
                break
        name = info.get("name") or info.get("groupName") or "(không rõ tên)"
        total = info.get("totalMember") or info.get("total_member")
        out = f"Tên nhóm: {name}"
        if total:
            out += f"\nSố thành viên: {total}"
        return out
    except Exception:
        return "Không lấy được thông tin nhóm."


_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _safe_eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("biểu thức không hợp lệ")


def t_calc(bot, thread_id, expression=""):
    try:
        return f"{expression} = {_safe_eval(ast.parse(expression, mode='eval').body)}"
    except Exception:
        return f"Không tính được biểu thức: {expression}"


def t_time(bot, thread_id):
    now = datetime.now(timezone(timedelta(hours=7)))
    return now.strftime("Bây giờ là %H:%M, ngày %d/%m/%Y (giờ Việt Nam, UTC+7).")


def t_links(bot, thread_id):
    links = []
    for it in _fetch(bot, thread_id):
        for u in _URL_RE.findall(it["text"]):
            links.append(f"- {it['name']}: {u}")
    if not links:
        return "Không thấy link nào được chia sẻ trong các tin gần đây."
    return "Các link đã chia sẻ gần đây:\n" + "\n".join(links[-30:])


# ---- registry ------------------------------------------------------------
# cmd  : short slash-command alias for direct use
# arg  : which param receives the free-text remainder of a direct command
TOOLS = [
    {"name": "search_messages", "cmd": "search", "arg": "keyword",
     "desc": "Tìm tin nhắn chứa từ khoá trong nhóm", "fn": t_search,
     "params": {"type": "object", "properties": {
         "keyword": {"type": "string", "description": "từ khoá cần tìm"}}, "required": ["keyword"]}},
    {"name": "get_recent_messages", "cmd": "recent", "arg": "count",
     "desc": "Lấy N tin nhắn gần nhất của nhóm", "fn": t_recent,
     "params": {"type": "object", "properties": {
         "count": {"type": "integer", "description": "số tin muốn lấy (mặc định 30)"}}}},
    {"name": "count_messages_by_user", "cmd": "count", "arg": None,
     "desc": "Đếm số tin mỗi người đã nhắn", "fn": t_count,
     "params": {"type": "object", "properties": {}}},
    {"name": "get_messages_by_user", "cmd": "user", "arg": "name",
     "desc": "Lấy các tin của một người cụ thể", "fn": t_by_user,
     "params": {"type": "object", "properties": {
         "name": {"type": "string", "description": "tên người cần lấy tin"}}, "required": ["name"]}},
    {"name": "get_group_info", "cmd": "group", "arg": None,
     "desc": "Xem tên nhóm và số thành viên", "fn": t_group_info,
     "params": {"type": "object", "properties": {}}},
    {"name": "calculate", "cmd": "calc", "arg": "expression",
     "desc": "Tính toán biểu thức số học", "fn": t_calc,
     "params": {"type": "object", "properties": {
         "expression": {"type": "string", "description": "biểu thức, vd 2+3*4"}}, "required": ["expression"]}},
    {"name": "get_datetime", "cmd": "time", "arg": None,
     "desc": "Xem ngày giờ hiện tại (giờ VN)", "fn": t_time,
     "params": {"type": "object", "properties": {}}},
    {"name": "find_links", "cmd": "links", "arg": None,
     "desc": "Liệt kê các link đã chia sẻ trong nhóm", "fn": t_links,
     "params": {"type": "object", "properties": {}}},
]

_BY_NAME = {t["name"]: t for t in TOOLS}
_BY_CMD = {t["cmd"]: t for t in TOOLS}


def openai_specs():
    return [{"type": "function", "function": {
        "name": t["name"], "description": t["desc"], "parameters": t["params"]}} for t in TOOLS]


def execute(bot, thread_id, name, args):
    """Run a tool by name. thread_id is fixed by the caller (never from args)."""
    t = _BY_NAME.get(name)
    if not t:
        return f"Không có công cụ tên '{name}'."
    args = {k: v for k, v in (args or {}).items() if k != "thread_id"}  # never let model override scope
    try:
        return str(t["fn"](bot, thread_id, **args))
    except TypeError:
        return f"Tham số không hợp lệ cho công cụ '{name}'."
    except Exception as e:
        return f"Lỗi khi chạy '{name}': {type(e).__name__}"


def list_text():
    lines = ["🛠 Các công cụ mình có (gõ trực tiếp /lệnh hoặc cứ hỏi tự nhiên):"]
    for t in TOOLS:
        arg = f" <{t['arg']}>" if t["arg"] else ""
        lines.append(f"• /{t['cmd']}{arg} — {t['desc']}")
    lines.append("Ví dụ: `@ai /search bóng đá` hoặc `@ai ai nhắn nhiều nhất?`")
    return "\n".join(lines)


def run_command(bot, thread_id, text):
    """Direct slash-command invocation, e.g. '/search bóng đá'."""
    parts = text[1:].strip().split(maxsplit=1)
    cmd = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""
    t = _BY_CMD.get(cmd)
    if not t:
        return f"Không có lệnh /{cmd}. Gõ `@ai /tools` để xem danh sách."
    args = {t["arg"]: rest} if t["arg"] and rest else {}
    return execute(bot, thread_id, t["name"], args)
