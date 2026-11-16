import sys
import json
import os
import re
from datetime import datetime
from pathlib import Path

# Handle non-ASCII characters in console output
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout


SESSION_FILE = Path(__file__).parent / "session.json"


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"{ts} [{level}] {msg}")


def error(msg):
    log(msg, "ERROR")


def step(msg):
    log(msg, "STEP")


def load_dotenv(path=None):
    """Load KEY=VALUE pairs from a .env file into os.environ (does not override)."""
    if path is None:
        path = Path(__file__).parent / ".env"
    path = Path(path)
    if not path.exists():
        return False
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            os.environ.setdefault(key, val)
    log(f"Environment loaded: {path}")
    return True


def load_config():
    load_dotenv()

    cfg = {
        "dsm": {
            "url": "",
            "username": "",
            "password": "",
            "ignoreSslErrors": True,
        },
        "actions": {},
        "browser": {"headless": True},
        "selectors": {
            "loginUsername": "#dsm-user-fieldset input",
            "loginPassword": "#dsm-pass-fieldset input[type='password']",
            "loginSubmitButton": "div.login-btn",
            "loginStaySignedIn": "#remember_me",
            "desktopReadyIndicator": "#sds-desktop",
        },
    }

    env = os.environ
    if env.get("DSM_URL"):
        cfg.setdefault("dsm", {})["url"] = env["DSM_URL"]
    if env.get("DSM_USERNAME"):
        cfg["dsm"]["username"] = env["DSM_USERNAME"]
    if env.get("DSM_PASSWORD"):
        cfg["dsm"]["password"] = env["DSM_PASSWORD"]
    if env.get("MAILPLUS_HEADLESS"):
        cfg.setdefault("browser", {})["headless"] = env["MAILPLUS_HEADLESS"].strip().lower() in ("1", "true", "yes", "on")

    if not cfg.get("dsm", {}).get("url"):
        print("DSM URL not configured. Set DSM_URL in .env.")
        sys.exit(1)
    if not cfg.get("dsm", {}).get("username") or not cfg.get("dsm", {}).get("password"):
        print("DSM credentials not configured. Set DSM_USERNAME / DSM_PASSWORD in .env.")
        sys.exit(1)

    return cfg


def wait_for(page, selector, timeout=15000):
    try:
        page.wait_for_selector(selector, timeout=timeout)
        return page.query_selector(selector)
    except PwTimeout:
        return None


def screenshot(page, name, session_dir):
    path = os.path.join(session_dir, f"{name}.png")
    page.screenshot(path=path)
    log(f"Screenshot: {name}.png")


def save_session(context):
    state = context.storage_state()
    with open(SESSION_FILE, "w") as f:
        json.dump(state, f)
    log(f"Session saved ({len(state['cookies'])} cookies)")


def load_session(context):
    if not SESSION_FILE.exists():
        return False
    with open(SESSION_FILE) as f:
        state = json.load(f)
    context.add_cookies(state["cookies"])
    log(f"Session loaded ({len(state['cookies'])} cookies)")
    return state


def restore_local_storage(page, state):
    for origin in state.get("origins", []):
        for item in origin.get("localStorage", []):
            try:
                page.evaluate("localStorage.setItem(arg1, arg2)", item["name"], item["value"])
            except:
                pass


def dismiss_system_dialogs(page):
    """Close any system notification dialogs that may be blocking the UI."""
    dismissed = page.evaluate("""() => {
        const dialogs = document.querySelectorAll('.x-window');
        let count = 0;
        dialogs.forEach(d => {
            if (d.offsetParent === null) return;
            const text = d.textContent || '';
            if (text.includes('File System Scan') || text.includes('Firewall Notification') || text.includes('Notification')) {
                const buttons = d.querySelectorAll('button');
                let target = null;
                buttons.forEach(b => {
                    const t = b.textContent.trim();
                    if (t === 'Ignore' || t === 'Cancel' || t === 'OK' || t === 'Remind me later') {
                        target = b;
                    }
                });
                if (target) {
                    target.click();
                    count++;
                }
            }
        });
        return count;
    }""")
    if dismissed:
        log(f"Dismissed {dismissed} system dialog(s)")
        page.wait_for_timeout(1000)
    return dismissed


def login_dsm(page, cfg, session_dir):
    step("Opening DSM")
    page.goto(cfg["dsm"]["url"], wait_until="domcontentloaded")
    user_sel = cfg["selectors"]["loginUsername"]
    wait_for(page, user_sel, timeout=15000)
    log(f"Page title: '{page.title()}', URL: {page.url}")
    screenshot(page, "01_login_page", session_dir)

    step("Entering username")
    el = page.query_selector(user_sel)
    if not el:
        error(f"Username field not found: {user_sel}")
        return False
    el.fill(cfg["dsm"]["username"])
    log(f"Username entered: {cfg['dsm']['username']}")

    step("Triggering username submission")
    page.wait_for_timeout(500)
    page.evaluate("""
        const inp = document.querySelector('#dsm-user-fieldset input');
        if (inp) {
            inp.dispatchEvent(new Event('input', { bubbles: true }));
            inp.dispatchEvent(new Event('change', { bubbles: true }));
        }
    """)
    page.wait_for_timeout(500)
    btn_sel = cfg["selectors"]["loginSubmitButton"]
    clicked = page.evaluate(f"""
        const btn = document.querySelector('{btn_sel}');
        if (btn) {{
            btn.dispatchEvent(new MouseEvent('click', {{ bubbles: true, cancelable: true }}));
            true;
        }} else {{
            false;
        }}
    """)
    log(f"Button click dispatched: {clicked}")

    step("Waiting for password field")
    pass_sel = cfg["selectors"]["loginPassword"]
    el = wait_for(page, pass_sel, timeout=25000)
    if not el:
        error(f"Password field not found: {pass_sel}")
        screenshot(page, "02_password_field_missing", session_dir)
        return False
    el.fill(cfg["dsm"]["password"])

    step("Checking 'Stay signed in' checkbox")
    try:
        stay_sel = cfg.get("selectors", {}).get("loginStaySignedIn", "#remember_me")
        stay_cb = page.query_selector(stay_sel)
        if stay_cb and stay_cb.is_visible() and not stay_cb.is_checked():
            stay_cb.check()
            log("Checked 'Stay signed in'")
    except:
        log("Stay signed in checkbox not found or already checked")

    step("Clicking Sign In")
    page.wait_for_timeout(500)
    page.keyboard.press("Enter")
    log("Pressed Enter to submit login")

    step("Waiting for desktop")
    desktop_sel = cfg["selectors"]["desktopReadyIndicator"]
    el = wait_for(page, desktop_sel, timeout=30000)
    if not el:
        error("DSM desktop did not load")
        screenshot(page, "03_login_failed", session_dir)
        return False
    screenshot(page, "03_desktop_loaded", session_dir)
    log("DSM login successful")

    dismiss_system_dialogs(page)
    return True


def launch_mailplus(page, cfg, session_dir):
    step("Launching MailPlus Server from desktop")
    icon_sel = '[syno-id="SYNO.SDS.MailPlusServer.Instance"]'
    el = wait_for(page, icon_sel, timeout=10000)
    if not el:
        icon_sel = '[aria-label="Synology MailPlus Server"]'
        el = wait_for(page, icon_sel, timeout=5000)
    if not el:
        error("MailPlus Server icon not found on desktop")
        return False
    el.click()
    dismiss_system_dialogs(page)
    # Wait for MailPlus app to render (sidebar "Mail Delivery" = app loaded)
    try:
        page.get_by_text("Mail Delivery", exact=False).first.wait_for(state="visible", timeout=20000)
        log("MailPlus app window loaded")
    except Exception:
        log("Mail Delivery didn't appear, continuing with fallback wait")
        page.wait_for_timeout(3000)
    dismiss_system_dialogs(page)
    screenshot(page, "03_mailplus_server", session_dir)
    return True


def click_extjs_button(page, button_text, parent_sel=None):
    """Click an ExtJS button by text using Ext.getCmp or DOM click fallback."""
    scope_js = f'document.querySelector("{parent_sel}")' if parent_sel else 'document'
    result = page.evaluate(f"""(text) => {{
        const root = {scope_js};
        if (!root) return 'Parent not found: {parent_sel or "document"}';
        const wrappers = root.querySelectorAll('.x-btn');
        for (const w of wrappers) {{
            if (w.offsetParent === null) continue;
            const textEl = w.querySelector('.x-btn-text');
            if (!textEl) continue;
            const t = (textEl.textContent || '').trim();
            if (t === text) {{
                if (typeof Ext !== 'undefined' && typeof Ext.getCmp === 'function') {{
                    const cmp = Ext.getCmp(w.id);
                    if (cmp) {{
                        if (typeof cmp.handler === 'function' && !cmp.disabled) {{
                            cmp.handler.call(cmp.scope || cmp, cmp);
                            return 'Ext handler: ' + cmp.$className + ' id=' + w.id;
                        }}
                        if (typeof cmp.fireEvent === 'function') {{
                            cmp.fireEvent('click', cmp);
                            return 'Ext fireEvent: ' + w.id;
                        }}
                    }}
                }}
                w.click();
                return 'DOM click: ' + w.id;
            }}
        }}
        return 'Not found: ' + text;
    }}""", button_text)
    log(f"ExtJS button click '{button_text}': {result}")
    return "Not found" not in result


def navigate_to_block_list(page, cfg, session_dir):
    if not launch_mailplus(page, cfg, session_dir):
        return False

    step("Clicking Mail Delivery in sidebar")
    dismiss_system_dialogs(page)
    page.wait_for_timeout(2000)
    for attempt in range(3):
        if not click_sidebar_item(page, "Mail Delivery"):
            page.wait_for_timeout(2000)
            continue
        log("Clicked Mail Delivery")
        page.wait_for_timeout(500)
        dismiss_system_dialogs(page)
        try:
            page.wait_for_function("""() => {
                const anchors = document.querySelectorAll('a');
                for (const a of anchors) {
                    if (a.offsetParent === null) continue;
                    if ((a.textContent || '').trim() === 'Security' && a.offsetParent !== null) {
                        const r = a.getBoundingClientRect();
                        if (r.x > 300) return true;
                    }
                }
                return false;
            }""", timeout=15000)
            break
        except:
            if attempt < 2:
                log("Security tab not loaded, retrying sidebar click...")
                dismiss_system_dialogs(page)
            else:
                error("Security tab not loaded after 3 attempts")
                screenshot(page, "04_nav_fail", session_dir)
                return False

    step("Clicking Security tab in Mail Delivery content area")
    try:
        security_tabs = page.locator("a", has_text="Security").all()
        clicked = False
        for tab in security_tabs:
            try:
                box = tab.bounding_box()
                if box and box["x"] > 300 and tab.is_visible():
                    tab.click()
                    log("Clicked Security tab in content area")
                    clicked = True
                    break
            except:
                pass
        if not clicked:
            log("Security tab not found in content area, waiting and retrying")
            page.wait_for_timeout(2000)
            security_tabs = page.locator("a", has_text="Security").all()
            for tab in security_tabs:
                try:
                    box = tab.bounding_box()
                    if box and box["x"] > 300 and tab.is_visible():
                        tab.click()
                        log("Clicked Security tab on retry")
                        clicked = True
                        break
                except:
                    pass
    except Exception as e:
        log(f"Security tab click issue: {e}")

    dismiss_system_dialogs(page)
    step("Clicking Block/Allow List via JS")
    click_extjs_button(page, "Block/Allow List")
    # Wait for the Block/Allow List panel to open
    try:
        page.locator(".x-window").filter(has_text="Block list").filter(has_text="Allow list").first.wait_for(state="visible", timeout=5000)
    except:
        pass

    step("Verifying Block/Allow List page")
    page_content = page.evaluate("document.body.innerText")
    if "Create" in page_content and ("Block list" in page_content or "Allow list" in page_content):
        log("Block/Allow List page confirmed!")
        screenshot(page, "04_block_allow_list", session_dir)
        return True

    error("Could not reach Block/Allow List page")
    screenshot(page, "04_block_list_missing", session_dir)
    return False





def find_block_list_panel_id(page):
    """Find the Block/Allow List panel DOM id for scoped button searches."""
    return page.evaluate("""() => {
        const wins = document.querySelectorAll('.x-window');
        for (const w of wins) {
            if (w.offsetParent === null) continue;
            if (w.classList.contains('syno-app-mailplus-server')) continue;
            const txt = w.textContent || '';
            if (txt.includes('Block list') && txt.includes('Allow list')) return w.id;
        }
        return '';
    }""")


def add_rule_via_dialog(page, sender, session_dir, panel_sel):
    """Add one rule to the grid via the Create dialog (panel stays open)."""
    step(f"Adding rule for {sender}")

    # Try clicking Create, if dialog doesn't appear force-enable and retry
    for attempt in range(2):
        if click_extjs_button(page, "Create", parent_sel=panel_sel):
            try:
                page.locator(".x-window").filter(has_text="-Create").first.wait_for(state="visible", timeout=3000)
                break
            except:
                pass
        if attempt == 0:
            log("Create dialog not opened, force-enabling Create button")
            page.evaluate(f"""((sel) => {{
                const root = document.querySelector(sel);
                if (!root) return;
                const wrappers = root.querySelectorAll('.x-btn');
                for (const w of wrappers) {{
                    const t = w.querySelector('.x-btn-text');
                    if (t && (t.textContent || '').trim() === 'Create') {{
                        const cmp = Ext && Ext.getCmp && Ext.getCmp(w.id);
                        if (cmp) {{
                            cmp.setDisabled(false);
                            cmp.enable();
                            cmp.disabled = false;
                            if (typeof cmp.handler === 'function') {{
                                cmp.handler.call(cmp.scope || cmp, cmp);
                            }}
                            return;
                        }}
                        w.click();
                    }}
                }}
            }})({json.dumps(panel_sel)})""")
            page.wait_for_timeout(1000)
        else:
            error("Create button not found or dialog not opening")
            return False

    # Wait for Create dialog to appear
    try:
        page.locator(".x-window").filter(has_text="-Create").first.wait_for(state="visible", timeout=3000)
    except:
        pass

    block_id = find_block_list_panel_id(page)
    dialog_id = page.evaluate(f"""((skipId) => {{
        const wins = document.querySelectorAll('.x-window');
        for (const w of wins) {{
            if (w.offsetParent === null) continue;
            if (w.id === skipId) continue;
            if (w.classList.contains('syno-app-mailplus-server')) continue;
            const txt = w.textContent || '';
            if (txt.includes('-Create')) return w.id;
        }}
        return '';
    }})({json.dumps(block_id)})""")
    if not dialog_id:
        error("Could not find Create Rule dialog")
        return False

    dlg = page.locator(f"#{dialog_id}")
    dlg.locator("input[name=description]").fill(sender, timeout=3000)
    dlg.locator("input[name=pattern]").fill(sender, timeout=3000)

    click_extjs_button(page, "OK", parent_sel=f"#{dialog_id}")
    # Wait for dialog to close
    try:
        page.locator(f"#{dialog_id}").wait_for(state="hidden", timeout=5000)
    except:
        pass
    dismiss_system_dialogs(page)

    still_open = page.evaluate(f"""((id) => {{
        const d = document.getElementById(id);
        return d ? d.offsetParent !== null : false;
    }})({json.dumps(dialog_id)})""")
    if still_open:
        error(f"Create dialog did not close for {sender}")
        return False

    found = page.evaluate("""(s) => {
        const rows = document.querySelectorAll('.x-grid3-row');
        for (const r of rows) { if (r.textContent.includes(s)) return true; }
        return false;
    }""", sender)
    if found:
        log(f"Verified {sender} in grid")
    else:
        error(f"Warning: {sender} not found in grid")
    return True


def block_sender(page, cfg, sender, session_dir):
    """Block a single sender: navigate, add rule, save."""
    if not navigate_to_block_list(page, cfg, session_dir):
        return False

    panel_id = find_block_list_panel_id(page)
    if not panel_id:
        error("Could not find Block/Allow List panel")
        return False
    panel_sel = f"#{panel_id}"

    if not add_rule_via_dialog(page, sender, session_dir, panel_sel):
        return False

    screenshot(page, "05_rule_added", session_dir)

    step("Saving rule to server via panel OK")
    click_extjs_button(page, "OK", parent_sel=panel_sel)
    try:
        page.locator(f"#{panel_id}").wait_for(state="hidden", timeout=10000)
    except:
        pass
    dismiss_system_dialogs(page)

    panel_still_open = page.evaluate(f"""((pid) => {{
        const p = document.getElementById(pid);
        return p ? p.offsetParent !== null : false;
    }})({json.dumps(panel_id)})""")
    if panel_still_open:
        error("Block/Allow List panel did not close after OK")
        return False

    screenshot(page, "07_rule_saved", session_dir)
    log(f"Block rule created for: {sender}")
    return True


def find_mcp_panel_id(page):
    """Find the MCP Quarantine panel DOM id."""
    return page.evaluate("""() => {
        const wins = document.querySelectorAll('.x-window');
        for (const w of wins) {
            if (w.offsetParent === null) continue;
            if (w.classList.contains('syno-app-mailplus-server')) continue;
            const txt = w.textContent || '';
            if (txt.includes('MCP Quarantine')) return w.id;
        }
        return '';
    }""")


def click_sidebar_item(page, text):
    """Click a sidebar tree node by dispatching click on the .x-tree-node-el parent."""
    return page.evaluate("""(t) => {
        const all = document.querySelectorAll('*');
        for (const el of all) {
            if (el.offsetParent === null) continue;
            if ((el.textContent || '').trim() !== t) continue;
            const r = el.getBoundingClientRect();
            if (r.x >= 50) continue;
            const nodeEl = el.closest('.x-tree-node-el');
            if (nodeEl) {
                nodeEl.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true, clientX: r.left + 5, clientY: r.top + 5}));
                nodeEl.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, cancelable: true, clientX: r.left + 5, clientY: r.top + 5}));
                nodeEl.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, clientX: r.left + 5, clientY: r.top + 5}));
                return true;
            }
        }
        return false;
    }""", text)


def navigate_to_mcp_quarantine(page, cfg, session_dir):
    if not launch_mailplus(page, cfg, session_dir):
        return False

    # Wait for interface to settle before sidebar interaction
    page.wait_for_timeout(2000)
    dismiss_system_dialogs(page)

    for attempt in range(3):
        step(f"Clicking Security in sidebar (attempt {attempt+1})")
        if not click_sidebar_item(page, "Security"):
            page.wait_for_timeout(2000)
            continue

        dismiss_system_dialogs(page)

        # Wait for Data Protection tab to appear (up to 10s per attempt)
        try:
            page.wait_for_function("""() => {
                const anchors = document.querySelectorAll('a');
                for (const a of anchors) {
                    if ((a.textContent || '').trim() === 'Data Protection' && a.offsetParent !== null) {
                        const r = a.getBoundingClientRect();
                        if (r.x > 300) return true;
                    }
                }
                return false;
            }""", timeout=10000)
            break
        except:
            log("Data Protection tab not found, retrying...")

    step("Clicking Data Protection tab")
    try:
        dp_tabs = page.locator("a", has_text="Data Protection").all()
        for tab in dp_tabs:
            try:
                box = tab.bounding_box()
                if box and box["x"] > 300 and tab.is_visible():
                    tab.click()
                    log("Clicked Data Protection tab")
                    break
            except:
                pass
    except Exception as e:
        log(f"Data Protection tab click: {e}")
        error("Could not find Data Protection tab")
        return ""

    page.wait_for_timeout(300)
    dismiss_system_dialogs(page)

    step("Clicking MCP Quarantine")
    if not click_extjs_button(page, "MCP Quarantine"):
        error("MCP Quarantine button not found")
        return False
    page.wait_for_timeout(2000)
    dismiss_system_dialogs(page)

    panel_id = find_mcp_panel_id(page)
    if not panel_id:
        error("Could not find MCP Quarantine panel")
        return False
    log(f"MCP Quarantine panel: {panel_id}")
    screenshot(page, "04_mcp_quarantine", session_dir)
    return panel_id


def release_quarantine(page, cfg, sender, subject, session_dir):
    panel_id = navigate_to_mcp_quarantine(page, cfg, session_dir)
    if not panel_id:
        return False

    panel_sel = f"#{panel_id}"

    # ----- Build candidate search terms in priority order -----
    candidates = []

    # 1. First 3-4 subject words (most precise)
    if subject:
        words = re.split(r'[^a-zA-Z0-9]+', subject)
        words = [w for w in words if w]
        if words:
            n = min(len(words), 4) if len(words) >= 3 else len(words)
            candidates.append(("subject", " ".join(words[:n])))

    # 2. Full sender local part (exact, without @domain)
    if sender:
        raw = sender.split("@")[0] if "@" in sender else sender
        candidates.append(("sender_local", raw))
        # If local part has underscore, try replacing with space (AND search)
        if "_" in raw:
            candidates.append(("sender_spaced", raw.replace("_", " ")))

    # ----- Try each candidate until one matches in the store -----
    target_index = -1

    def search_and_match(page, panel_id, term):
        """Search the quarantine, then find the matching row in the ExtJS store."""
        try:
            si = page.locator(f"#{panel_id} input[placeholder='Search']")
            si.wait_for(state="visible", timeout=5000)
            si.click()
            page.wait_for_timeout(200)
            si.fill("")
            page.wait_for_timeout(300)
            si.type(term, delay=80)
            page.wait_for_timeout(500)
            si.press("Enter")
            try:
                page.wait_for_function("""() => {
                    const masks = document.querySelectorAll('.x-mask-loading');
                    for (const m of masks) { if (m.offsetParent !== null) return false; }
                    return true;
                }""", timeout=30000)
            except:
                pass
            page.wait_for_timeout(1500)
            dismiss_system_dialogs(page)
        except Exception as e:
            log(f"Search bar interaction failed: {e}")

    def find_in_store(page, panel_id, field, value):
        """Find row index where store record's `field` contains `value` (case-insensitive)."""
        return page.evaluate(f"""((val) => {{
            var pc = Ext.getCmp('{panel_id}');
            if (!pc || !pc.items) return -2;
            var gc = null;
            pc.items.each(function(it){{ if (it.getStore) {{ gc = it; return false; }} }});
            if (!gc) return -3;
            var st = gc.getStore();
            if (!st) return -4;
            var lv = val.toLowerCase();
            for (var i = 0; i < st.getCount(); i++) {{
                var rec = st.getAt(i);
                if (rec) {{
                    var f = rec.get('{field}');
                    if (f && f.toLowerCase().indexOf(lv) !== -1) return i;
                }}
            }}
            return -1;
        }})""", value)

    for source, term in candidates:
        step(f"Searching [{source}]: '{term}'")
        search_and_match(page, panel_id, term)
        idx = find_in_store(page, panel_id, "sender", sender)
        if idx >= 0:
            target_index = idx
            log(f"  ✓ [{source}] → sender match at index {target_index}")
            break
        else:
            log(f"  ✗ [{source}] no sender match for '{sender}'")

    if target_index < 0:
        error(f"Sender '{sender}' not matched by any search candidate — aborting")
        screenshot(page, "06_no_match", session_dir)
        return False

    # Select the row using ExtJS selection model
    page.evaluate(f"""((idx) => {{
        var panelCmp = Ext.getCmp('{panel_id}');
        if (!panelCmp || !panelCmp.items) return;
        var gridCmp = null;
        panelCmp.items.each(function(item) {{
            if (item.getStore) {{ gridCmp = item; return false; }}
        }});
        if (!gridCmp) return;
        var sm = gridCmp.getSelectionModel();
        if (sm && sm.selectRow) {{
            sm.selectRow(idx);
        }}
    }})""", target_index)
    page.wait_for_timeout(500)

    # Verify row is selected via DOM
    is_selected = page.evaluate("""() => {
        const rows = document.querySelectorAll('.x-grid3-row');
        for (const row of rows) {
            if (row.offsetParent === null) continue;
            return row.classList.contains('x-grid3-row-selected');
        }
        return false;
    }""")
    if not is_selected:
        log("ExtJS selectRow did not reflect in DOM, clicking via mouse")
        coords = page.evaluate("""() => {
            const rows = document.querySelectorAll('.x-grid3-row');
            if (rows.length === 0) return null;
            for (const row of rows) {
                if (row.offsetParent === null) continue;
                const r = row.getBoundingClientRect();
                return {x: r.left + r.width / 2, y: r.top + r.height / 2};
            }
            return null;
        }""")
        if coords:
            page.mouse.click(coords["x"], coords["y"])
            page.wait_for_timeout(500)

    # Wait for Release button to become enabled after row selection
    step("Waiting for Release button to enable")
    try:
        page.wait_for_function("""() => {
            const wrappers = document.querySelectorAll('.x-btn');
            for (const w of wrappers) {
                if (w.offsetParent === null) continue;
                const textEl = w.querySelector('.x-btn-text');
                if (!textEl) continue;
                if ((textEl.textContent || '').trim() === 'Release') {
                    const cmp = Ext && Ext.getCmp && Ext.getCmp(w.id);
                    if (cmp && !cmp.disabled) return true;
                }
            }
            return false;
        }""", timeout=5000)
        log("Release button is now enabled")
    except:
        log("Release button did not enable within 5s, trying click anyway")

    page.wait_for_timeout(300)

    if not click_extjs_button(page, "Release", parent_sel=panel_sel):
        # If still disabled, force-enable it and retry
        log("Release click via handler failed, trying force-enable")
        enabled = page.evaluate("""() => {
            const wrappers = document.querySelectorAll('.x-btn');
            for (const w of wrappers) {
                if (w.offsetParent === null) continue;
                const textEl = w.querySelector('.x-btn-text');
                if (!textEl) continue;
                if ((textEl.textContent || '').trim() === 'Release') {
                    const cmp = Ext && Ext.getCmp && Ext.getCmp(w.id);
                    if (cmp) {
                        cmp.setDisabled(false);
                        cmp.enable();
                        cmp.disabled = false;
                        if (typeof cmp.handler === 'function') {
                            const scope = cmp.scope || cmp;
                            cmp.handler.call(scope, cmp);
                            return true;
                        }
                    }
                }
            }
            return false;
        }""")
        if not enabled:
            error("Could not click Release button")
            return False
        log("Release clicked via force-enable")

    step("Confirming release dialog")
    page.wait_for_timeout(1000)
    # Click "Yes" in the confirmation popup (No / Yes)
    clicked = page.evaluate("""() => {
        const wins = document.querySelectorAll('.x-window');
        for (const w of wins) {
            if (w.offsetParent === null) continue;
            if (w.classList.contains('syno-app-mailplus-server')) continue;
            const txt = w.textContent || '';
            if (txt.includes('Yes') && txt.includes('No')) {
                // Find the "Yes" button
                const btns = w.querySelectorAll('.x-btn');
                for (const btn of btns) {
                    const t = (btn.textContent || '').trim();
                    if (t === 'Yes' || t === 'y') {
                        const cmp = Ext && Ext.getCmp && Ext.getCmp(btn.id);
                        if (cmp && typeof cmp.handler === 'function' && !cmp.disabled) {
                            cmp.handler.call(cmp.scope || cmp, cmp);
                            return 'Ext handler';
                        }
                        if (cmp && typeof cmp.fireEvent === 'function') {
                            cmp.fireEvent('click', cmp);
                            return 'fireEvent';
                        }
                        btn.click();
                        return 'DOM click';
                    }
                }
            }
        }
        return false;
    }""")
    if clicked:
        log(f"Confirmation clicked: {clicked}")
    else:
        log("No confirmation dialog found, may have been auto-dismissed")

    page.wait_for_timeout(1500)
    dismiss_system_dialogs(page)

    screenshot(page, "06_released", session_dir)
    subj_preview = (subject[:80] + '...') if subject and len(subject) > 80 else (subject or '')
    log(f"SUCCESS: Released '{subj_preview}' from {sender}")
    return True


def main():
    action = ""
    sender_raw = ""
    subject = ""

    # If first arg is a JSON file path, read args from file (VBA mode)
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        with open(sys.argv[1], encoding="utf-8-sig") as f:
            args = json.load(f)
        action = args.get("action", "")
        sender_raw = args.get("sender", "")
        subject = args.get("subject", "")
    else:
        action = sys.argv[1] if len(sys.argv) > 1 else ""
        sender_raw = sys.argv[2] if len(sys.argv) > 2 else ""
        subject = sys.argv[3] if len(sys.argv) > 3 else ""

    if action not in ("Block", "Release", "Spam"):
        print(f"Usage: python mailplus_automation.py <Action> [SenderEmail] [Subject]")
        print(f"       python mailplus_automation.py <path_to_args.json>")
        print(f"Actions: Block, Release, Spam")
        sys.exit(1)

    cfg = load_config()

    session_dir = os.path.join(
        Path(__file__).parent,
        "logs",
        f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    os.makedirs(session_dir, exist_ok=True)

    log("=" * 50)
    log(f"Action: {action}")
    if sender_raw:
        log(f"Sender: {sender_raw}")
    if subject:
        log(f"Subject: {subject}")
    log("=" * 50)

    if action == "Spam":
        log("Spam handled directly in Outlook VBA (forward as attachment)")
        sys.exit(0)

    headless = cfg.get("browser", {}).get("headless", False)
    ignore_ssl = cfg.get("dsm", {}).get("ignoreSslErrors", True)

    with sync_playwright() as p:
        browser_args = {"headless": headless, "slow_mo": 100}
        if ignore_ssl:
            browser_args["args"] = ["--ignore-certificate-errors"]

        browser = p.chromium.launch(**browser_args)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        state = load_session(context)
        if state:
            try:
                page.goto(cfg["dsm"]["url"], wait_until="domcontentloaded")
                # Wait for either desktop (valid session) or login form (expired)
                try:
                    page.wait_for_selector("#sds-desktop, #dsm-user-fieldset", timeout=15000)
                except PwTimeout:
                    log("Neither desktop nor login appeared")
                if page.query_selector("#sds-desktop"):
                    log("Session valid - skipping login")
                    restore_local_storage(page, state)
                    dismiss_system_dialogs(page)
                    screenshot(page, "01_session_restored", session_dir)
                else:
                    log("Session expired - re-logging in")
                    page.goto(cfg["dsm"]["url"], wait_until="domcontentloaded")
                    state = None
            except Exception as e:
                log(f"Session load failed: {e}")
                state = None

        if not state:
            if not login_dsm(page, cfg, session_dir):
                sys.exit(1)
            save_session(context)
            page.wait_for_timeout(500)

        success = False
        try:
            if action == "Block":
                if not sender_raw:
                    error("Sender email required")
                    sys.exit(1)
                success = block_sender(page, cfg, sender_raw, session_dir)
            elif action == "Release":
                sender = sender_raw
                success = release_quarantine(page, cfg, sender, subject, session_dir)

        except Exception as e:
            error(f"Fatal error: {e}")
            screenshot(page, "99_error", session_dir)
            success = False
        finally:
            browser.close()

        if success:
            log("=" * 50)
            log("ACTION COMPLETED SUCCESSFULLY")
            log("=" * 50)
            sys.exit(0)
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()
