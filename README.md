# MailPlus Outlook Automation

One-click Synology MailPlus quarantine and block-list management from Outlook.

With three toolbar buttons you can, from inside Outlook:

- **Block Sender** — add the sender of the selected email to the MailPlus block list
- **Release from Quarantine** — release the sender's quarantined messages from the MCP Quarantine
- **Mark as Spam** — forward the selected email as an attachment to your spam-report address

## Architecture

```
Outlook VBA (3 toolbar buttons on Quick Access Toolbar)
    │
    ▼
Python + Playwright (mailplus_automation.py)
    │
    ▼
Chrome browser → Synology DSM / MailPlus Server GUI
```

## Files

| File | Purpose |
|------|---------|
| `mailplus_automation.py` | Main script — drives Chrome via Playwright |
| `setup.bat` | One-shot setup: creates `.venv`, installs Playwright, sets `MAILPLUS_HOME` |
| `capture_selectors.py` | Helper to capture UI selectors from your DSM version |
| `test_automation.py` | Verifies Python, Playwright, and DSM connectivity |
| `OutlookMacros.bas` | VBA macros — import into Outlook for toolbar buttons |
| `.env.example` | Template for `.env` (copied automatically by `setup.bat`) |

## Setup

### 1. Run the setup script

Double-click `setup.bat` (or run it from a terminal). It will:

- create the `.venv` virtual environment
- install Playwright and the Chromium browser
- create `.env` from `.env.example` if it does not exist
- set the `MAILPLUS_HOME` environment variable to this project folder

### 2. Fill in your credentials

Edit `.env` and set `DSM_URL`, `DSM_USERNAME`, `DSM_PASSWORD`, and
`SPAM_REPORT_EMAIL`. **`.env` is gitignored — never commit it.**

### 3. Restart Outlook

`MAILPLUS_HOME` is read when Outlook starts, so close and reopen Outlook
after running setup.

### 4. Test (optional)

```powershell
.venv\Scripts\python test_automation.py
```

### 5. Capture UI selectors (optional, one-time)

```powershell
.venv\Scripts\python capture_selectors.py
```

This opens Chrome and walks you through several phases of the DSM UI,
generating HTML reports with click-to-copy selectors. Custom selectors can
be overridden by editing the `selectors` dict in `mailplus_automation.py`.

### 6. Import VBA macros into Outlook

1. `Alt+F11` to open the VBA editor
2. **File > Import File** → select `OutlookMacros.bas`
3. Close the editor

### 7. Add buttons to Quick Access Toolbar

1. Right-click the QAT > **Customize Quick Access Toolbar**
2. Choose commands from: **Macros**
3. Add: `Spam`, `Block`, `Release`
4. Click **Modify** to assign icons, then **OK**

### 8. Use it

Select an email in Outlook → click **Block** → Chrome opens, logs into DSM, and creates the block rule.

### Manual setup (alternative to `setup.bat`)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install playwright
.venv\Scripts\python -m playwright install chromium
copy .env.example .env
setx MAILPLUS_HOME "C:\path\to\outlook-automation"
```

## Troubleshooting

- **Playwright not installed**: `.venv\Scripts\python -m pip install playwright`
- **Browser not found**: `.venv\Scripts\python -m playwright install chromium`
- **Selectors wrong**: Run `.venv\Scripts\python capture_selectors.py` to find correct ones
- **SSL errors**: default `ignoreSslErrors` is true; override in an optional `.env`
- **"MAILPLUS_HOME is not set"**: run `setup.bat` (or `setx MAILPLUS_HOME "C:\path\to\outlook-automation"`), then reopen Outlook
- **Logs**: Stored in `.\logs\session_*\`

## Notes

- The script saves a `session.json` cookie file after a successful login so subsequent runs skip the login step. Delete it if you have login issues.
- All interactions are DOM/JavaScript based, so the script works in headless mode.
- If the session expires, a full two-step login (username → Next → password → Enter) happens automatically.