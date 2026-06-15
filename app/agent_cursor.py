"""Virtual cursor overlay for the browse agent.

Injects a yellow pointer into the page that GLIDES (CSS-animated, ease-out) to each
click target *before* the real click fires, with a click "ripple" — so the live view
and any recording look like a human moving the mouse (à la Claude's Chrome cursor).

PURELY COSMETIC. Every entry point swallows all errors: if anything about the CDP
injection fails, the cursor simply doesn't show and the actual task is untouched.
Disable with VIRTUAL_CURSOR=0. Tune the glide with CURSOR_GLIDE_MS (default 550).

Mechanism (browser-use 0.12.9):
- `_cdp_add_init_script` (Page.addScriptToEvaluateOnNewDocument, runImmediately) defines
  the cursor + a `window.__agentCursor.to(pageX,pageY,click)` once per document.
- per click: read the element's `absolute_position` (DOMRect, page coords) → center →
  `Runtime.evaluate("window.__agentCursor.to(...)")`. The JS subtracts scroll for the
  fixed-position cursor, so it lands on the element regardless of scroll.
"""
import asyncio
import logging
import os

log = logging.getLogger("agent_cursor")

ENABLED = os.getenv("VIRTUAL_CURSOR", "1").strip().lower() not in ("0", "false", "no", "off")
GLIDE_MS = int(os.getenv("CURSOR_GLIDE_MS", "550"))  # CSS transition duration for the A→B glide
# Real mouse-move (hover) before each click — only needed for hover-activated controls.
# OFF by default: filters now go via URL params, and a pre-hover can open nav mega-menus
# and shift layout before the click. Opt in with CURSOR_HOVER=1 for a hover-heavy site.
HOVER = os.getenv("CURSOR_HOVER", "0").strip().lower() in ("1", "true", "yes", "on")
# Hide the REAL OS cursor over the page (only the yellow one shows). OFF by default so the
# human's own cursor keeps working while watching; turn on (CURSOR_HIDE_OS=1) for a clean clip.
HIDE_OS = os.getenv("CURSOR_HIDE_OS", "0").strip().lower() in ("1", "true", "yes", "on")

_INIT_JS = r"""
(function(){
  try{ if (window.top !== window.self) return; }catch(e){ return; }   // TOP frame only — iframes (e.g. card fields) must NOT each spawn a cursor
  if (window.__agentCursor) return;
  var GLIDE = __GLIDE_MS__;
  var c = document.createElement('div');
  c.id = '__agent_cursor';
  c.style.cssText = 'position:fixed;left:0;top:0;width:26px;height:26px;z-index:2147483647;'
    + 'pointer-events:none;transition:transform ' + (GLIDE/1000) + 's cubic-bezier(.22,1,.36,1);'
    + 'will-change:transform;transform:translate(-120px,-120px);'
    + 'filter:drop-shadow(0 2px 3px rgba(0,0,0,.45));';
  c.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    + '<path d="M5 2.5 L5 19 L9.2 14.8 L12.3 21.5 L15 20.2 L11.9 13.6 L18 13.6 Z" '
    + 'fill="#FFC400" stroke="#5b4300" stroke-width="1" stroke-linejoin="round"/></svg>';
  var HIDE_OS = __HIDE_OS__;   // hide the real OS cursor too? default false → the human's cursor still shows
  var st = document.createElement('style');
  st.textContent = '*{cursor:none!important}';
  var lastX = null, lastY = null;   // remember position so an SPA re-render re-adds at the same spot
  function place(x,y){ lastX=x; lastY=y; c.style.transform = 'translate(' + x + 'px,' + y + 'px)'; }
  function center(){ try{ place((window.innerWidth||900)/2, (window.innerHeight||600)/2); }catch(e){} }
  function add(){ try{
    if(HIDE_OS && !st.parentNode){ (document.head||document.documentElement||document.body).appendChild(st); }
    if(document.body && !document.getElementById('__agent_cursor')){
      document.body.appendChild(c);
      if(lastX===null) center(); else c.style.transform='translate('+lastX+'px,'+lastY+'px)';
    }
  }catch(e){} }
  function ripple(x,y){
    try{
      var r=document.createElement('div');
      r.style.cssText='position:fixed;left:'+x+'px;top:'+y+'px;width:14px;height:14px;border-radius:50%;'
        +'z-index:2147483646;pointer-events:none;border:2px solid #FFC400;background:rgba(255,196,0,.25);'
        +'transform:translate(-50%,-50%) scale(.4);opacity:.95;'
        +'transition:transform .5s ease-out,opacity .5s ease-out;';
      (document.body||document.documentElement).appendChild(r);
      requestAnimationFrame(function(){ r.style.transform='translate(-50%,-50%) scale(3.2)'; r.style.opacity='0'; });
      setTimeout(function(){ try{r.remove();}catch(e){} }, 560);
    }catch(e){}
  }
  window.__agentCursor = {
    to: function(x,y,click){          // x,y are VIEWPORT coords (from getBoundingClientRect)
      add();
      place(x,y);
      if(click){ setTimeout(function(){ ripple(x,y); }, GLIDE); }
    },
    home: function(){ add(); center(); }   // park at viewport center (visible right on open)
  };
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', add); else add();
  try{ setInterval(add, 400); }catch(e){}   // heartbeat: re-add the cursor if an SPA re-render removed it
})();
""".replace("__GLIDE_MS__", str(GLIDE_MS)).replace("__HIDE_OS__", "true" if HIDE_OS else "false")

_installed = set()  # id(browser_session) we've added the init script to (once per session)


async def install(browser_session):
    """Register the cursor init-script on the session (idempotent). runImmediately=True
    means it also takes on the page already loaded, and it re-runs on every navigation."""
    if not ENABLED:
        return
    key = id(browser_session)
    if key in _installed:
        return
    try:
        ident = await browser_session._cdp_add_init_script(_INIT_JS)
        _installed.add(key)
        log.info("🖱️ cursor init-script installed (id=%s)", ident)
    except Exception:
        log.warning("🖱️ cursor install FAILED", exc_info=True)


async def show(browser_session):
    """Install + park the cursor at viewport center so it's visible IMMEDIATELY (even on
    the blank page right after the browser opens). Call once at task start."""
    if not ENABLED:
        return
    try:
        await install(browser_session)
        await _eval_top(browser_session, "window.__agentCursor&&window.__agentCursor.home()")
        log.info("🖱️ cursor shown at center (browser-open)")
    except Exception:
        log.warning("🖱️ cursor show FAILED", exc_info=True)


async def _eval_top(browser_session, js):
    """Run JS in the agent-focused (top) frame, where the cursor div lives."""
    tid = getattr(browser_session, "agent_focus_target_id", None)
    cdp = await browser_session.get_or_create_cdp_session(tid, focus=False)
    return await cdp.cdp_client.send.Runtime.evaluate(
        params={"expression": js, "returnByValue": True}, session_id=cdp.session_id,
    )


async def _hover(browser_session, x, y):
    """Dispatch a REAL mouse-move to (x,y) so hover-activated controls (e.g. Uniqlo's
    price-range box that only lights up on hover) ACTIVATE before browser-use clicks —
    fixes 'click lands on an inactive element → miss'. Top frame, viewport CSS px."""
    tid = getattr(browser_session, "agent_focus_target_id", None)
    cdp = await browser_session.get_or_create_cdp_session(tid, focus=False)
    await cdp.cdp_client.send.Input.dispatchMouseEvent(
        params={"type": "mouseMoved", "x": float(x), "y": float(y)}, session_id=cdp.session_id)


# Run on the actual element: scroll it into view, then return its VIEWPORT-space center.
_CENTER_FN = (
    "function(){"
    " try{ this.scrollIntoView({block:'center',inline:'center'}); }catch(e){}"
    " var r=this.getBoundingClientRect();"
    " return {x:r.left+r.width/2, y:r.top+r.height/2}; }"
)


async def _element_center(browser_session, node):
    """Viewport (x,y) center of <node> AFTER scrolling it into view — resolved in the
    node's own frame (correct even for iframes). None if it can't be resolved."""
    cdp = await browser_session.cdp_client_for_node(node)
    resolved = await cdp.cdp_client.send.DOM.resolveNode(
        params={"backendNodeId": node.backend_node_id}, session_id=cdp.session_id)
    oid = (resolved or {}).get("object", {}).get("objectId")
    if not oid:
        return None
    res = await cdp.cdp_client.send.Runtime.callFunctionOn(
        params={"functionDeclaration": _CENTER_FN, "objectId": oid, "returnByValue": True},
        session_id=cdp.session_id)
    val = (res or {}).get("result", {}).get("value") or {}
    if "x" not in val:
        return None
    return float(val["x"]), float(val["y"])


async def move_to_index(browser_session, index, *, click=True):
    """Glide the cursor to element <index>'s center (after scrolling it into view), ripple
    if click=True, and WAIT for the glide so the motion is visible before the real click.
    Cosmetic only — swallows every error (never affects the task)."""
    if not ENABLED:
        return
    try:
        await install(browser_session)
        node = await browser_session.get_element_by_index(index)
        if node is None:
            log.info("🖱️ move idx=%s: no node", index)
            return
        center = await _element_center(browser_session, node)
        if not center:
            log.info("🖱️ move idx=%s: no center", index)
            return
        cx, cy = center
        res = await _eval_top(browser_session,
                              "(window.__agentCursor?(window.__agentCursor.to(%f,%f,%s),'OK'):'NO_CURSOR')"
                              % (cx, cy, "true" if click else "false"))
        try:
            val = res.get("result", {}).get("value")
        except Exception:
            val = res
        # REAL mouse-move to the same point → triggers :hover for hover-activated controls.
        # Opt-in (CURSOR_HOVER=1): off by default to avoid opening nav menus before a click.
        if HOVER:
            try:
                await _hover(browser_session, cx, cy)
            except Exception:
                pass
        log.info("🖱️ move idx=%s → (%.0f,%.0f) eval=%s", index, cx, cy, val)
        await asyncio.sleep(GLIDE_MS / 1000.0 + 0.05)  # let the glide+hover settle before the click
        if os.getenv("VIRTUAL_CURSOR_DEBUG"):  # snapshot with the cursor parked at target
            try:
                await browser_session.take_screenshot(
                    path="/tmp/agent_preview/cursor_dbg.jpg", format="jpeg", quality=70)
            except Exception:
                pass
    except Exception:
        log.warning("🖱️ cursor move FAILED idx=%s", index, exc_info=True)
