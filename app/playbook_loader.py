"""Use-case PLAYBOOK loader — mirrors the SRE agent's progressive-disclosure
skills (runbook/<category>/SKILL.md), but for a live-action browser agent.

- L1  build_l1_index()        : name + 1-line description of every playbook
                                (always injected into the agent's system msg).
- L2  load_playbook(name)     : full SKILL.md body, pulled on demand by the
                                agent via the load_playbook tool.
- build_system_guidance()     : the L1 catalog + the hard-gate instruction,
                                shared by the live agent AND the routing test
                                so both exercise the exact same routing prompt.

Goal-not-selectors: playbooks describe the GOAL of each step + what to ask the
user, never brittle DOM selectors — browser-use adapts the actual clicks. (Same
spirit as the SRE rule "describe the task, not the tool function".)
"""
import glob
import os
import re

PLAYBOOK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "playbooks")


def _parse_frontmatter(text):
    """Return (meta_dict, body). Frontmatter is a `--- ... ---` block at top."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    fm, body = m.group(1), m.group(2)
    meta = {}
    for line in fm.splitlines():
        if ":" in line and not line.startswith((" ", "\t", "-")):
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


def discover():
    """List of {name, description, path, body} for every playbooks/*/SKILL.md."""
    out = []
    for skill_path in sorted(glob.glob(os.path.join(PLAYBOOK_DIR, "*", "SKILL.md"))):
        with open(skill_path, encoding="utf-8") as f:
            text = f.read()
        meta, body = _parse_frontmatter(text)
        name = meta.get("name") or os.path.basename(os.path.dirname(skill_path))
        out.append({
            "name": name,
            "description": meta.get("description", ""),
            "path": skill_path,
            "body": body,
        })
    return out


# Playbooks the ACTOR (gpt-4o) must NOT see in its routing catalog — they're not
# user-facing use-cases. `common-stuck` is an expert-only KB (Agent Advisor reads it).
_ACTOR_HIDDEN = {"common-stuck"}


def build_l1_index():
    """L1 catalog: one bullet per use-case playbook (name + pushy description).
    Hides expert-only KBs so the actor doesn't try to route to them."""
    pbs = [p for p in discover() if p["name"] not in _ACTOR_HIDDEN]
    if not pbs:
        return "(chưa có playbook nào)"
    return "\n".join(f"- **{p['name']}**: {p['description']}" for p in pbs)


def load_playbook(name):
    """L2: full playbook body for `name`, or a helpful miss message."""
    key = (name or "").strip().lower()
    pbs = discover()
    for p in pbs:
        if p["name"].lower() == key:
            return p["body"].strip()
    avail = ", ".join(p["name"] for p in pbs) or "(không có)"
    return (
        f"(Không có playbook tên '{name}'. Hiện có: {avail}. "
        "Nếu yêu cầu không khớp playbook nào, cứ tự làm theo cách tổng quát.)"
    )


def build_system_guidance():
    """The catalog + hard-gate, shared by the live agent and the routing test."""
    return (
        "Bạn có sẵn một bộ PLAYBOOK — quy trình đã được kiểm chứng cho các tác "
        "vụ phổ biến.\n"
        "NGUYÊN TẮC BẮT BUỘC: nếu yêu cầu của người dùng KHỚP một trong các "
        "playbook dưới đây, bạn PHẢI gọi tool `load_playbook(name)` NGAY, TRƯỚC "
        "bất kỳ thao tác trình duyệt nào, để lấy quy trình chuẩn rồi bám theo. "
        "Nếu KHÔNG khớp playbook nào, đừng gọi tool — cứ tự làm theo cách tổng quát.\n\n"
        "Các playbook hiện có:\n" + build_l1_index()
    )


if __name__ == "__main__":
    # Quick self-check: print the L1 catalog the agent will see.
    print(build_system_guidance())
    print("\n--- discovered ---")
    for p in discover():
        print(f"{p['name']:12s} ({len(p['body'])} chars)  {p['path']}")
