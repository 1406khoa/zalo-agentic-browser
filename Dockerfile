FROM python:3.12-slim

# Chromium + Xvfb (virtual display) + runtime deps. In prod we run Chrome
# NON-headless under Xvfb: real rendering dodges Traveloka's headless bot-block
# (429/captcha) AND drives date-pickers reliably (proven by the headed runs;
# plain headless got 429+captcha). xauth is needed by `xvfb-run -a`.
# --no-sandbox via chromium_sandbox=False. Give the container RAM + shm
# (--disable-dev-shm-usage) or Chrome crashes.
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        xvfb \
        xauth \
        x11vnc \
        fonts-liberation \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV CHROME_BIN=/usr/bin/chromium \
    PYTHONUNBUFFERED=1

# Baked OPERATIONAL DEFAULTS (non-secret) so a freshly-created AgentBase agent needs ONLY the
# secrets on the console: MAAS_API_KEY · ZALO_IMEI · ZALO_COOKIES · AGENT_LOGINS · PUBLIC_BASE_URL.
# (AGENT_LOGINS = JSON login profile for live login via fill_login; replaced the removed cookie-injection
#  WARM_STORAGE_STATE — captured Google/Akamai sessions proved non-portable.)
# Console env still OVERRIDES any of these. Fixes the footguns where the *code* defaults are wrong for
# prod (MAAS_URL/MAAS_BASE pointed at a DEV endpoint; POC_MODEL defaulted to gpt-5). These values are NOT
# secrets (model names, tuning numbers, the public MaaS gateway URL) — fine to live in the image.
ENV POC_MODEL=gemini/gemini-3.1-pro-preview \
    FALLBACK_MODEL=openai/gpt-4o-mini \
    MAAS_BASE=https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1 \
    MAAS_URL=https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1/chat/completions \
    DOM_MAX=8000 \
    VISION_DETAIL=auto \
    CURSOR_GLIDE_MS=300

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

COPY app/ ./app/

EXPOSE 8080

# entrypoint.sh starts Xvfb + exports DISPLAY, then execs the CMD → the on-demand
# browser engine renders NON-headless on the virtual display (container_session
# auto-detects DISPLAY). FastAPI (port 8080, /health) + Zalo listener thread;
# engine runs in a worker thread (agent_runner).
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "app.main"]
