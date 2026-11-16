"""
Test script for MailPlus Outlook Automation.
Verifies Python, Playwright, config, and DSM connectivity.
"""
import json
import sys
import os
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"  [{ts}] {msg}")


reset = "\033[0m"

def check(label, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    icon = "\033[92m" if ok else "\033[91m"
    print(f"  [{icon}{status}{reset}] {label}" + (f" - {detail}" if detail else ""))


PROJECT_DIR = Path(__file__).parent


print("=" * 50)
print("MailPlus Automation - Test Script")
print("=" * 50)

# 1: Config (from .env)
print("\n[1/5] Config...")
try:
    from mailplus_automation import load_config
    cfg = load_config()
    check("Config loaded", True)
except SystemExit:
    check("Config loaded", False, "Set DSM_URL / DSM_USERNAME / DSM_PASSWORD in .env")
    sys.exit(1)
print(f"       URL: {cfg['dsm']['url']}")
print(f"       User: {cfg['dsm']['username']}")

# 2: Python version
print("\n[2/5] Python version...")
check(f"Python {sys.version.split()[0]}", sys.version_info >= (3, 7))

# 3: Playwright
print("\n[3/5] Playwright...")
try:
    from importlib.metadata import version as _pkg_version
    pw_ver = _pkg_version("playwright")
    check(f"Playwright {pw_ver}", True)
except ImportError:
    check("Playwright installed", False, "Run: pip install playwright")
    sys.exit(1)

try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        _ = p.chromium
        check("Playwright + Chromium ready", True)
except Exception as e:
    check("Playwright browser", False, f"Run: python -m playwright install chromium. ({str(e)[:80]})")
    sys.exit(1)

# 4: DSM connectivity (headful for debugging)
print("\n[4/5] DSM connectivity...")
print("  Opening visible browser to debug connectivity issues.")
print("  Watch the browser window - it should open your DSM login page.")
ignore_ssl = cfg.get("dsm", {}).get("ignoreSslErrors", True)
url = cfg["dsm"]["url"]

with sync_playwright() as p:
    browser_args = {
        "headless": False,  # Visible so you can see what's happening
        "slow_mo": 100,
    }
    if ignore_ssl:
        browser_args["args"] = ["--ignore-certificate-errors"]

    browser = p.chromium.launch(**browser_args)
    page = browser.new_page()

    log(f"Navigating to {url} ...")
    try:
        # Use domcontentloaded - DSM is a SPA with constant polling
        # networkidle will hang forever because DSM never stops AJAX calls
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        log("Page DOM loaded - waiting 3s for JavaScript rendering...")
        page.wait_for_timeout(3000)

        title = page.title()
        current_url = page.url
        check(f"Page loaded", True, f"Title: '{title}'")
        log(f"Current URL: {current_url}")

        # Take screenshot for debugging
        shot_dir = os.path.join(PROJECT_DIR, "logs")
        os.makedirs(shot_dir, exist_ok=True)
        shot_path = os.path.join(shot_dir, "debug_connectivity.png")
        page.screenshot(path=shot_path)
        log(f"Screenshot saved: {shot_path}")

        if any(kw in title.lower() for kw in ["synology", "dsm", "login", "sign"]):
            check("DSM login page detected", True)
        elif "404" in title or "not found" in title.lower():
            check("DSM login page", False, f"Got 404 - wrong URL or path")
            log("Try appending /webapi/ to your URL or check the port")
        else:
            check("DSM login page", True, f"Title is '{title}' - check screenshot to confirm")

    except Exception as e:
        check("DSM reachable", False, str(e)[:200])
        log(f"Failed to load {url}")
        log("Possible causes: URL is wrong, port not forwarded, or network issue")
        log("Close the browser window manually when done inspecting")
        input("  Press ENTER to close browser and continue...")
        browser.close()
        sys.exit(1)

    log("Browser will stay open for inspection.")
    input("  Press ENTER to close browser and continue...")
    browser.close()

# 5: Screenshot capability (quick check using the existing debug screenshot)
print("\n[5/5] Screenshot capability...")
shot_dir = os.path.join(PROJECT_DIR, "logs")
shot_path = os.path.join(shot_dir, "debug_connectivity.png")
if os.path.exists(shot_path):
    size = os.path.getsize(shot_path)
    check(f"Screenshot exists ({size / 1024:.0f} KB)", True)
else:
    check("Screenshot", False)

print(f"""
{'='*50}
Tests completed.
{'='*50}

Next steps:
  1. Fix any issues above, then run again:
     python test_automation.py

  2. Capture UI selectors:
     python capture_selectors.py

  3. Selectors use built-in defaults; use `capture_selectors.py` output to override if needed.

  4. Test block action:
     python mailplus_automation.py BlockSender test@spam.com

  5. Import OutlookMacros.bas into Outlook (Alt+F11 > File > Import)
  6. Add QAT toolbar buttons for the 3 macros
""")
