"""
Selector Capture Helper for Synology MailPlus / DSM.

Opens Chrome, walks you through each page, and generates HTML reports
with every visible element's CSS selector and XPath.
"""
import json
import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

from mailplus_automation import load_config


def dump_elements(page, label, report_dir):
    """Extract all visible interactable elements and write HTML report."""
    js = """
    () => {
        const results = [];
        const tags = ['button', 'a', 'input', 'select', 'textarea', 'label', 'span', 'div', 'li'];
        const seen = new Set();

        tags.forEach(tag => {
            document.querySelectorAll(tag).forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) return;

                const text = (el.textContent || '').trim().substring(0, 120);
                const tagName = el.tagName.toLowerCase();
                const attrs = {};
                ['id', 'name', 'type', 'placeholder', 'value', 'href', 'class',
                 'role', 'aria-label', 'data-app-id', 'data-testid'].forEach(a => {
                    const v = el.getAttribute(a);
                    if (v) attrs[a] = v;
                });

                // CSS selector
                let cssSel = '';
                if (el.id) {
                    cssSel = '#' + el.id;
                } else {
                    const path = [];
                    for (let cur = el; cur && cur !== document.body && cur !== document.documentElement; cur = cur.parentElement) {
                        let seg = cur.tagName.toLowerCase();
                        if (cur.id) { seg = '#' + cur.id; path.unshift(seg); break; }
                        if (cur.className && typeof cur.className === 'string') {
                            const cls = cur.className.trim().split(/\\s+/).filter(c => c && c !== 'active' && c !== 'hover').join('.');
                            if (cls) seg += '.' + cls;
                        }
                        const parent = cur.parentElement;
                        if (parent) {
                            const sameTag = Array.from(parent.children).filter(c => c.tagName === cur.tagName);
                            if (sameTag.length > 1) {
                                const idx = sameTag.indexOf(cur) + 1;
                                seg += ':nth-of-type(' + idx + ')';
                            }
                        }
                        path.unshift(seg);
                    }
                    cssSel = path.join(' > ');
                }

                // XPath
                let xpath = '';
                for (let cur = el; cur && cur.nodeType === 1; cur = cur.parentElement) {
                    let seg = cur.tagName.toLowerCase();
                    const parent = cur.parentElement;
                    if (parent) {
                        const sameTag = Array.from(parent.children).filter(c => c.tagName === cur.tagName);
                        if (sameTag.length > 1) {
                            const idx = sameTag.indexOf(cur) + 1;
                            seg += '[' + idx + ']';
                        }
                    }
                    xpath = '/' + seg + xpath;
                }

                const key = (text || '') + '|' + cssSel;
                if (!seen.has(key)) {
                    seen.add(key);
                    results.push({
                        tag: tagName,
                        text: text.substring(0, 100),
                        css: cssSel,
                        xpath: xpath,
                        attrs: JSON.stringify(attrs),
                        placeholder: attrs.placeholder || ''
                    });
                }
            });
        });
        return results;
    }
    """
    elements = page.evaluate(js)

    def esc(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    rows_login = []
    rows_buttons = []
    rows_inputs = []
    rows_all = []

    for el in elements:
        tag = el["tag"]
        display_text = esc(el["text"] or (f"[{el['placeholder']}]" if el["placeholder"] else ""))
        css = esc(el["css"])
        xp = esc(el["xpath"])

        row = f"""<tr class="row" data-tag="{tag}" data-text="{esc(el['text'])}">
<td class="tag-{tag}">{tag}</td>
<td>{display_text}</td>
<td class="selector">{css}</td>
<td class="xpath">{xp}</td>
<td><button class="copy-btn" onclick="copy('{css}', this)">CSS</button>
<button class="copy-btn" onclick="copy('{xp}', this)">XPath</button></td>
</tr>"""

        rows_all.append(row)
        if tag in ("input", "select", "textarea"):
            rows_inputs.append(row)
        if tag in ("button",) or (tag == "a" and el["text"]):
            rows_buttons.append(row)

        txt = (el["text"] + " " + el["placeholder"]).lower()
        if any(kw in txt for kw in ["login", "sign in", "user", "pass", "submit"]):
            rows_login.append(row)

    def write_section(title, rows_data):
        if not rows_data:
            return ""
        return f"<h2 id='{title.lower()}'>{title} ({len(rows_data)})</h2>\n<table><tr><th>Tag</th><th>Text</th><th>CSS Selector</th><th>XPath</th><th>Copy</th></tr><tbody>{''.join(rows_data)}</tbody></table>\n"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Selectors - {label}</title>
<style>
body {{ font-family: 'Segoe UI', sans-serif; margin: 20px; background: #1e1e1e; color: #d4d4d4; }}
h1 {{ color: #569cd6; }}
h2 {{ color: #569cd6; font-size: 14px; margin-top: 30px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 11px; margin-bottom: 10px; }}
th {{ background: #2d2d2d; color: #569cd6; padding: 6px; text-align: left; position: sticky; top: 0; }}
td {{ padding: 4px 6px; border-bottom: 1px solid #3e3e3e; word-break: break-all; }}
tr:hover {{ background: #2a2d2e; }}
.tag-button {{ color: #c586c0; }} .tag-input {{ color: #dcdcaa; }}
.tag-select {{ color: #4ec9b0; }} .tag-a {{ color: #569cd6; }}
.selector {{ color: #ce9178; font-family: Consolas, monospace; font-size: 10px; }}
.xpath {{ color: #6a9955; font-family: Consolas, monospace; font-size: 10px; }}
.copy-btn {{ cursor: pointer; padding: 2px 6px; background: #0e639c; color: #fff; border: none; border-radius: 3px; font-size: 9px; }}
.copy-btn:hover {{ background: #1177bb; }}
</style></head><body>
<h1>Page Elements: {label}</h1>
{write_section("Login Relevant", rows_login)}
{write_section("Buttons", rows_buttons)}
{write_section("Inputs", rows_inputs)}
{write_section("All Elements", rows_all)}
<script>
function copy(text, btn) {{
    navigator.clipboard.writeText(text).then(() => {{
        btn.textContent = 'OK!';
        setTimeout(() => btn.textContent = btn.innerText.includes('XPath') ? 'XPath' : 'CSS', 1500);
    }});
}}
</script></body></html>"""

    report_path = os.path.join(report_dir, f"selectors_{label}.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Report: {report_path}")
    os.startfile(report_path)


def main():
    cfg = load_config()

    report_dir = os.path.join(Path(__file__).parent, "selector-reports")
    os.makedirs(report_dir, exist_ok=True)

    ignore_ssl = cfg.get("dsm", {}).get("ignoreSslErrors", True)
    browser_args = {"headless": False, "slow_mo": 100}
    if ignore_ssl:
        browser_args["args"] = ["--ignore-certificate-errors"]

    with sync_playwright() as p:
        browser = p.chromium.launch(**browser_args)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        try:
            # Phase 1: DSM initial login page (username only)
            print("\n=== Phase 1: DSM Login Page (Username) ===")
            print(f"Opening {cfg['dsm']['url']} ...")
            page.goto(cfg["dsm"]["url"], wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            print("Login page loaded. Capturing username form elements...")
            dump_elements(page, "01_login_page", report_dir)

            # Phase 2: DSM password page (after entering username)
            print("\n=== Phase 2: DSM Login Page (Password) ===")
            print("Enter your username in the browser and click Next/Sign In.")
            print("STOP at the password screen (do NOT enter password yet).")
            input("Press ENTER when the password field is visible...")
            page.wait_for_timeout(2000)
            dump_elements(page, "02_password_page", report_dir)
            print("  -> Password page saved. Now complete login.")

            # Phase 3: Desktop (after login)
            print("\n=== Phase 3: DSM Desktop ===")
            input("Log in completely in the browser, then press ENTER to capture desktop...")
            page.wait_for_timeout(2000)
            dump_elements(page, "03_desktop", report_dir)

            # Phase 4: MailPlus Server
            print("\n=== Phase 4: MailPlus Server ===")
            print("Now navigate to MailPlus Server admin (click Main Menu > MailPlus Server)")
            print(f"Or go to: {cfg['dsm']['url']}/#/apps/MailPlus-Server/")
            input("Press ENTER when MailPlus Server admin is displayed...")
            page.wait_for_timeout(3000)
            dump_elements(page, "04_mailplus_server", report_dir)

            # Phase 5: Block/Allow List
            print("\n=== Phase 5: Block/Allow List ===")
            print("Navigate to: Mail Delivery > Security > Block/Allow List")
            input("Press ENTER when Block/Allow List is visible...")
            page.wait_for_timeout(2000)
            dump_elements(page, "05_block_allow_list", report_dir)

            # Phase 6: Create dialog
            print("\n=== Phase 6: Create Rule Dialog ===")
            print("Click the Create button to open the rule dialog")
            input("Press ENTER when the Create dialog is open...")
            page.wait_for_timeout(1000)
            dump_elements(page, "06_create_rule_dialog", report_dir)

            # Phase 7: MCP Quarantine
            print("\n=== Phase 7: MCP Quarantine ===")
            print("Navigate to the MCP Quarantine page")
            resp = input("Press ENTER when ready, or 's' to skip: ")
            if resp.lower() != "s":
                page.wait_for_timeout(2000)
                dump_elements(page, "07_mcp_quarantine", report_dir)

            print(f"\n{'='*50}")
            print("Selector capture complete!")
            print(f"{'='*50}")
            print(f"\nReports in: {report_dir}")
            print("\nLook for these elements and paste their CSS selectors into the `selectors` dict in mailplus_automation.py:")
            print("  loginUsername       -> username input")
            print("  loginPassword       -> password input")
            print("  loginSubmitButton   -> Sign In button")
            print("  sidebarBlockAllowList -> Block/Allow List nav item")
            print("  blockListCreateButton -> Create button")
            print("  blockRuleNameInput  -> rule name input")
            print("  blockRuleTypeSelect -> type dropdown")
            print("  blockRuleValueInput -> sender value input")
            print("  blockRuleOkButton   -> OK button")
            print("  quarantineMenuItem  -> MCP Quarantine nav item")
            print("  quarantineSearchInput -> search field")
            print("  quarantineFirstItem -> first result row")
            print("  quarantineReleaseButton -> Release button")

        except KeyboardInterrupt:
            print("\nAborted")
        finally:
            browser.close()

    input("\nPress ENTER to exit...")


if __name__ == "__main__":
    main()
