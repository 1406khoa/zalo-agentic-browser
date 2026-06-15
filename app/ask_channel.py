"""Abstract ASK-USER channel (shared by the engine and the Zalo bridge).

The engine asks a question + 2-3 options (options[0] = its recommendation); a
channel delivers it to a human and returns the chosen/typed answer.

Response model: reply with a NUMBER to pick an option, or type anything else as
a custom answer. resolve_answer() maps that to a value. Stdlib-only → imports on
Python 3.10 (bot's local env) and 3.12 (container).
"""
import abc
import asyncio
import os
import re

# A reply is an option-pick ONLY when the whole message is a single digit
# (optionally with trailing ".", ")", or the keycap emoji). "3 người" stays custom.
_NUM_RE = re.compile(r"^([1-9])(?:[.)️⃣\s])*$")
_NUMS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]


def render_form(question: str, options) -> str:
    """Human-readable numbered form. options[0] gets the '(đề xuất)' suffix."""
    options = options or []
    lines = [f"🤔 {question}"]
    for i, opt in enumerate(options):
        bullet = _NUMS[i] if i < len(_NUMS) else f"{i + 1}."
        suffix = "  (đề xuất)" if i == 0 else ""
        lines.append(f"{bullet} {opt}{suffix}")
    if options:
        lines.append("✍️ Hoặc nhập câu trả lời của bạn.")
    return "\n".join(lines)


def resolve_answer(reply: str, options) -> str:
    """Map a raw reply to an option (whole-message number) or custom text."""
    r = (reply or "").strip()
    m = _NUM_RE.match(r)
    if m and options:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(options):
            return options[idx]
    return r


class AskChannel(abc.ABC):
    @abc.abstractmethod
    async def ask(self, question: str, options) -> str:
        raise NotImplementedError


class FileAskChannel(AskChannel):
    """Local channel: write the form to a file, poll for an answer file."""

    def __init__(self, q_file="/tmp/agent_question.txt",
                 a_file="/tmp/agent_answer.txt", timeout=900):
        self.q_file, self.a_file, self.timeout = q_file, a_file, timeout

    async def ask(self, question: str, options) -> str:
        options = list(options or [])
        for f in (self.q_file, self.a_file):
            try:
                os.remove(f)
            except FileNotFoundError:
                pass
        form = render_form(question, options)
        with open(self.q_file, "w") as f:
            f.write(form)
        print(f"\n🙋 ASK_USER >>>\n{form}\n", flush=True)
        waited = 0
        while not os.path.exists(self.a_file):
            await asyncio.sleep(2)
            waited += 2
            if waited >= self.timeout:
                return options[0] if options else "(người dùng không trả lời, tự quyết hợp lý)"
        raw = open(self.a_file).read().strip()
        try:
            os.remove(self.a_file)
        except FileNotFoundError:
            pass
        ans = resolve_answer(raw, options)
        print(f"💬 USER >>> {ans}\n", flush=True)
        return ans
