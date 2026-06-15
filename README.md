# Agentency — a live-action browser agent inside Zalo

> Built for the **GreenNode Claw-a-thon**. You `@ai` it in a Zalo group; it opens a **real
> browser** and **does the task for you** — book a flight, shop Shopee/Tiki/Uniqlo, reserve a
> restaurant — **asking you back inside Zalo when it needs a decision**, and **never spending your
> money without an explicit "yes"**.

It began as a Q&A / summarize chatbot ("Meta AI for Zalo") and **pivoted to a live-action browser
agent**. The chatbot is now just the front door: ask a question and it answers; ask it to *do*
something and it drives a real Chromium to get it done — and lets you watch.

---

## What it feels like

Buying a shirt, end to end, from a group chat:

1. **You:** `@ai mua giúp mình áo thun nam Uniqlo dưới 400k`
2. **It:** replies with a **live link**, opens a real browser, and starts shopping.
3. Needs a decision (size? colour?) → drops a **native Zalo poll**; you tap one option.
4. Site demands login → it **logs in itself** — your password never touches the AI.
5. At checkout it **stops and asks**: *"Chốt đơn và trả tiền? [Có / Không]"*. Only your **"Có"**
   lets it place the order — and it **physically cannot type a card number**.
6. Done → it reports back: a summary, a screenshot, and the real order link. The browser stays
   alive so you can take over.

---

## Features

### 🤝 Human-in-the-loop — right inside the chat
When the agent needs a decision, it doesn't guess: it asks via a **native Zalo poll** (or a typed
reply), scoped to whoever started the task, first answer wins. The conversation *is* the control panel.

### 🛑 Code-enforced safety (not just a prompt)
- It **can never type a card number / CVV** — blocked in code before the keystroke, even if asked.
- Placing an order is **gated**: it cannot click *"Đặt hàng / Trả tiền"* until you confirm in chat.
- These are real backstops in the action layer, not polite instructions a model might ignore.

### 📺 Watch it work — live, from your phone
`/live` streams the agent's **real Chrome** screen over noVNC, plus a sanitized **reasoning stream**
showing what it's thinking at each step. Open the link on your phone and watch it click.

### 🧠 Knows when it's stuck → escalates
A stuck-loop detector spots when a step isn't making progress and **hands the wheel to a stronger,
vision-capable model** for the hard steps — then hands it back. There's also an on-demand expert
that reads the current screenshot and suggests a way through.

### 📖 Skills (playbooks), loaded on demand
Per-use-case procedures — `flight`, `shopping`, `restaurant`, `trip` — written as **goals, not
brittle selectors**. Only a one-line catalogue stays in context; the full procedure is pulled when
the task matches one (progressive disclosure).

### 🔑 Logs in for real — password-blind
On a login wall it types pre-configured **test-account** credentials straight into the site's own
form. The values **never enter the model's context, the live view, or the logs**. It still stops at
OTP / 2FA / CAPTCHA — it won't fake being you.

### 🧩 Two-and-a-half-model design
| Role | Model |
|------|-------|
| Front door: chat + read-tools + **routing** | `gpt-4o-mini` |
| Browse **actor** (drives the browser) | `gemini-3.1-pro` |
| **Expert advisor** (vision, consulted when stuck) | `gpt-5` |

The router is a **prompt**, not code: the chat model decides whether to open the browser purely
from a tool's description. "mua giúp / đặt vé" → browse; "nên mua gì / giá bao nhiêu" → just answer.

---

## Why it's genuinely *agentic* (not browser-use + a prompt)

Measured against the agent patterns Anthropic / OpenAI / Google recommend, Agentency implements the
**full loop — router → actor → advisor** — with the parts most browser agents skip:

- **Human-in-the-loop confirmation** at sensitive/irreversible steps (the permission gate).
- **Code-enforced guardrails** (the never-type-a-card-number rule, the place-order gate) — enforced
  in the action layer, not just the prompt.
- **Live observability** — you can watch the real browser and read the agent's reasoning as it goes.
- **Self-correction & escalation** — it detects its own stuck loops and routes the hard step to a
  stronger model instead of blindly retrying.

These three — *ask before spending, never type a card, watch it live* — are exactly where typical
browser agents are weak. Here they're first-class.

---

## Architecture — one container, three concerns

```
Zalo group ──websocket(outbound)──► zlapi listener ─┐
                                                     ├─► chat model (routing)
AgentBase probe ──HTTP /health──► FastAPI ───────────┘        │
                                  (port 8080)                 │ do_browser_task
                                      │                        ▼
                                  /live, /state, /logs ◄── browser worker thread
                                      ▲                   (browser-use Agent on a
                                      └── noVNC ◄── x11vnc ── real Chromium under Xvfb)
```

- **One container** runs FastAPI (port 8080, required by AgentBase) **+** a Zalo listener thread.
- The browse engine runs in **its own worker thread** per task, so the listener stays responsive.
- **`/health` is liveness-gated**: if the listener thread dies, it returns 503 so AgentBase restarts.
- **No Zalo creds → `/chat` shim mode**: the container stays healthy and `/chat` works, no listener.
- Chrome runs **non-headless under Xvfb** — real rendering dodges headless bot-blocks and drives
  date-pickers / dropdowns reliably.

---

## Request lifecycle (group message → action → answer)

1. `onMessage`: suppress the bot's own echoes → capture any `ask_user` reply **before** the `@ai`
   gate → require a mention/trigger → handle.
2. Build the tool set (read-tools + `do_browser_task`) and run a function-calling loop.
3. `do_browser_task` spawns the worker → builds a browser-use `Agent` and runs it; each step pushes
   sanitized reasoning to the live view.
4. The agent calls `load_playbook` (when a task matches), `ask_user` (routed to Zalo), and
   `ask_expert` (the advisor). On a detected stuck-loop it auto-escalates the actor model.
5. The result (or a `/huỷ` cancel) is sent back to the originating thread.

You can also **interrupt mid-task** with `@ai /interrupt <thêm yêu cầu>` and **cancel** with `/huỷ`.

---

## Project layout

| Path | Role |
|------|------|
| `app/main.py` | Entrypoint: FastAPI + Zalo listener thread (auto-reconnect) |
| `app/zalo_bot.py` | Mention/trigger detection, command routing, echo suppression |
| `app/agent_runner.py` | Spawns the browse worker; the `do_browser_task` router spec; `ZaloAskChannel` (polls) |
| `app/agent_core.py` | The browse engine: builds the browser-use Agent, tools, safety gates, stuck-escalation, advisor |
| `app/playbook_loader.py` + `app/playbooks/*/SKILL.md` | Progressive-disclosure skills |
| `app/ask_channel.py` / `app/interrupts.py` | Human-in-the-loop ask + mid-task interrupts |
| `app/server.py` + `app/live.html` + `app/web/novnc/` | FastAPI endpoints + the live view |
| `app/llm.py` / `app/tools.py` / `app/state.py` | Chat model calls, read-tool registry, shared liveness state |

---

## Run locally

`.env` is not auto-loaded — export vars yourself (see `.env.example`).

```bash
pip install -r requirements.txt
set -a; . ./.env; set +a
python3 -m app.main
curl -s localhost:8080/health
curl -s -X POST localhost:8080/chat -H 'Content-Type: application/json' -d '{"message":"xin chào"}'
```

With Zalo creds → full listener. Without → `/chat` shim mode (stays healthy, no listener).

## Deploy

Containerised; deployed as a single image on **GreenNode AgentBase** (FastAPI on port 8080).
Build → push → point the AgentBase runtime at the image → add env vars (see `.env.example`).

## Safety model

- Secrets (model key, Zalo cookies, login creds) live in **env only — never in any prompt**.
- Every read-tool is **hard-scoped to the current thread**, supplied by the caller, never the model.
- **Live login, not cookie injection** — the agent types test-account creds into the site's own
  form over CDP; the values never reach the model, the live view, or the logs.
- **Never types card numbers / CVV** (code-enforced) and **stops to confirm before spending money**.

> ⚠️ `zlapi` is an unofficial, reverse-engineered Zalo API — use a dedicated/secondary account;
> sessions expire and accounts can be rate-limited.
