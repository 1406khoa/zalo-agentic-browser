"""Per-run SESSION journal — capture the agent's full journey into sessions/session_NNN/
so later analysis can mine many runs for a shorter, more reliable workflow.

Stdlib-only (imports on 3.10 and 3.12). Each run writes:
  sessions/session_NNN/summary.md   — human-readable: task, outcome, ask_user Q&A,
                                      per-step trajectory (goal+eval), actions, final result
  sessions/session_NNN/meta.json    — machine-readable metrics (stats across sessions)
  sessions/session_NNN/{trajectory.txt, debug.log}  — optional raw-log copies (if paths given)
"""
import json
import os
import re
import shutil

# Repo-root/sessions (this file is app/session_log.py → parent of app/ is the repo root).
SESSIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sessions"
)


def next_session_dir(base=None):
    """Create and return (path, number) of the next session_NNN dir (001, 002, ...)."""
    base = base or os.environ.get("SESSIONS_DIR", SESSIONS_DIR)
    os.makedirs(base, exist_ok=True)
    nums = []
    for d in os.listdir(base):
        m = re.match(r"session_(\d+)$", d)
        if m:
            nums.append(int(m.group(1)))
    n = (max(nums) + 1) if nums else 1
    path = os.path.join(base, "session_%03d" % n)
    os.makedirs(path, exist_ok=True)
    return path, n


def _extract(history):
    """Best-effort trajectory + outcome from a browser-use AgentHistoryList."""
    ex = {"n_steps": None, "is_successful": None, "final_result": "",
          "reached_checkout": None, "steps": [], "actions": []}
    if history is None:
        return ex
    for key, fn in (("n_steps", "number_of_steps"),
                    ("is_successful", "is_successful"),
                    ("final_result", "final_result")):
        try:
            ex[key] = getattr(history, fn)()
        except Exception:
            pass
    ex["final_result"] = (ex["final_result"] or "")
    try:
        for i, t in enumerate(history.model_thoughts() or [], 1):
            ex["steps"].append({
                "step": i,
                "eval": (getattr(t, "evaluation_previous_goal", "") or "").replace("\n", " ")[:300],
                "goal": (getattr(t, "next_goal", "") or "").replace("\n", " ")[:300],
            })
    except Exception:
        pass
    try:
        for a in history.model_actions() or []:
            if isinstance(a, dict):
                name = next(iter(a.keys()), "?")
                ex["actions"].append("%s: %s" % (name, str(a.get(name))[:120]))
    except Exception:
        pass
    fr = (ex["final_result"] or "").lower()
    ex["reached_checkout"] = any(k in fr for k in
                                 ("checkout", "thanh toán", "xác nhận đơn", "giỏ hàng"))
    return ex


def save_session(*, task, mode="", model="", history=None, ask_log=None, metrics=None,
                 trajectory_path=None, debug_path=None, screenshot_path=None, base=None, label=""):
    """Write one session_NNN/ folder. Returns (path, number)."""
    path, n = next_session_dir(base)
    ex = _extract(history)
    ask_log = ask_log or []
    meta = {
        "session": n, "label": label, "task": task, "mode": mode, "model": model,
        "n_steps": ex["n_steps"], "is_successful": ex["is_successful"],
        "reached_checkout": ex["reached_checkout"], "n_questions": len(ask_log),
    }
    if metrics:
        meta.update(metrics)
    with open(os.path.join(path, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    L = ["# Session %03d%s" % (n, (" — " + label) if label else ""), "",
         "- **Task:** %s" % task,
         "- **Model (browse):** %s | **Mode:** %s" % (model or "?", mode or "?"),
         "- **Outcome:** n_steps=%s · is_successful=%s · reached_checkout=%s"
         % (ex["n_steps"], ex["is_successful"], ex["reached_checkout"])]
    if metrics:
        L.append("- **Metrics:** " + " · ".join("%s=%s" % (k, v) for k, v in metrics.items()))
    L += ["", "## ask_user log"]
    if ask_log:
        for i, qa in enumerate(ask_log, 1):
            L.append("%d. **Q:** %s" % (i, qa.get("q", "")))
            if qa.get("options"):
                L.append("   - options: %s" % (qa.get("options"),))
            L.append("   - **A:** %s" % qa.get("answer", ""))
    else:
        L.append("(no ask_user calls captured)")
    L += ["", "## Trajectory (goal per step)"]
    for s in ex["steps"]:
        L.append("- **step %d** · GOAL: %s" % (s["step"], s["goal"]))
        if s["eval"]:
            L.append("    - eval: %s" % s["eval"])
    L += ["", "## Actions (in order)"]
    L += ["- %s" % a for a in ex["actions"]] or ["(none)"]
    L += ["", "## Final result", (ex["final_result"].strip() or "(none)")]
    with open(os.path.join(path, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")

    if trajectory_path and os.path.exists(trajectory_path):
        try:
            shutil.copy(trajectory_path, os.path.join(path, "trajectory.txt"))
        except Exception:
            pass
    # debug log can be many MB → only copy when explicitly asked
    if debug_path and os.path.exists(debug_path) and os.environ.get("SESSION_COPY_DEBUG"):
        try:
            shutil.copy(debug_path, os.path.join(path, "debug.log"))
        except Exception:
            pass
    # the stop-point screenshot (e.g. the payment/card-entry screen)
    if screenshot_path and os.path.exists(screenshot_path):
        try:
            shutil.copy(screenshot_path, os.path.join(path, "stop_screenshot.jpg"))
        except Exception:
            pass
    return path, n
