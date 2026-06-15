#!/bin/sh
# Start a virtual display so the browser engine runs Chrome NON-headless (real
# rendering dodges Traveloka's headless bot-block 429/captcha; proven by headed
# runs). We start Xvfb manually rather than via xvfb-run, which hangs in this
# slim image before ever launching the command. container_session() sees the
# exported DISPLAY and launches non-headless automatically.
set -e

rm -f /tmp/.X99-lock 2>/dev/null || true
Xvfb :99 -screen 0 1920x1080x24 -ac -nolisten tcp >/tmp/xvfb.log 2>&1 &
export DISPLAY=:99

# Wait (max ~5s) for the X socket so Chrome doesn't race the display.
i=0
while [ ! -S /tmp/.X11-unix/X99 ] && [ $i -lt 25 ]; do
    i=$((i + 1))
    sleep 0.2
done

# Export the Xvfb display over VNC so /live can stream it (FastAPI bridges WS↔this VNC).
# XDAMAGE-driven by default (only changed regions → light CPU, must not starve the agent);
# -localhost so ONLY the in-container FastAPI bridge can reach it (the sole public path is
# port 8080 via Kong); -nopw (gate is the bridge, view-only); -forever/-shared = survive
# reconnects + allow >1 viewer. Backgrounded so the CMD (the app) still execs.
x11vnc -display :99 -nopw -localhost -forever -shared -rfbport 5900 -quiet -o /tmp/x11vnc.log 2>/dev/null &

exec "$@"
