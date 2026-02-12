# Keen

![Keen splash](docs/splash.png)

A macOS menu bar app to send web articles to your Kindle.

## Features

- **Menu bar app** — Lives in your menu bar, always ready
- **One-click sending** — Paste a URL or send from clipboard
- **Clean formatting** — Articles extracted and formatted for Kindle
- **Settings UI** — Configure credentials through the app
- **Secure storage** — SMTP password stored in macOS Keychain, not on disk

## Installation

If you downloaded the DMG:

- Open `Keen.dmg`
- Drag `Keen.app` to Applications
- Read `README_FIRST.txt` in the DMG for first-launch steps (Gatekeeper)

### Option 1: Build from source

```bash
git clone https://github.com/east35/keen.git
cd keen
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Build the app bundle from spec
bash scripts/build_macos.sh

# Install to Applications
cp -R "dist/Keen.app" /Applications/
```

### Option 2: Run in dev mode

```bash
source venv/bin/activate
python kindle_menubar.py
```

Note: In dev mode, macOS notifications are attributed to `Python` (interpreter process). To get the proper app name/icon in notifications and the app menu, run the packaged `dist/Keen.app`.

## Icons

Keen tracks its app icon and menu bar template icons in the repo and bundles them into the built `.app` via `Keen.spec`.

Verify icons are present and bundled:

```bash
python scripts/verify_icons.py --app dist/Keen.app
```

## Diagnostics & Logs

Keen writes logs to:

`~/Library/Logs/Keen/keen.log`

Follow logs while testing:

```bash
tail -f ~/Library/Logs/Keen/keen.log
```

Run GUI from source with logs:

```bash
cd keen
source venv/bin/activate
python kindle_menubar.py
```

Run packaged app from Terminal (shows stdout/stderr too):

```bash
cd keen
open dist/Keen.app
# or run the binary directly:
./dist/Keen.app/Contents/MacOS/Keen
```

Quick extraction smoke test (no GUI):

```bash
cd keen
source venv/bin/activate
python -m keen.diagnose "https://example.com/article"
```

Clipboard path test:

```bash
pbcopy < <(printf '%s' 'https://example.com/article')
```

Then click **Keen → Send from Clipboard**.

Paste URL path test:

1. Click **Keen → Send Article to Kindle**
2. Paste a valid `https://...` URL and click **Send**

Expected notifications:

- `Starting...` when action begins
- `Sent ✅` on success
- `Error ...` on failure
- `Invalid URL` or `Canceled` for invalid/canceled input

## Setup

### 1. Get your Kindle email address

Find it on your Kindle: **Settings → Your Account → Send-to-Kindle Email**

Or at: [amazon.com/myk](https://amazon.com/myk) → Preferences → Personal Document Settings

It looks like: `yourname_abc123@kindle.com`

### 2. Authorize your sending email

In the same Amazon settings page, scroll to **Approved Personal Document E-mail List** and add your Gmail address.

### 3. Get a Gmail app password

1. Enable 2FA on your Google account (if not already)
2. Go to: https://myaccount.google.com/apppasswords
3. Generate a password for "Mail"
4. Copy the 16-character password

### 4. Configure the app

1. Click the **Keen** icon in your menu bar
2. Select **Settings...**
3. Enter your Kindle email, Gmail, and app password

Email addresses and server settings are saved to `~/Library/Application Support/KindleSend/config.json`. Your SMTP app password is stored securely in the **macOS Keychain** (via the `keyring` library) and is never written to disk in plaintext.

> **Migration note:** If you previously used an older version that stored the password in `config.json`, Keen will automatically move it to the Keychain on first launch and remove it from the config file.

## Usage

1. Copy an article URL to your clipboard
2. Click the **Keen** icon in your menu bar
3. Select **Send from Clipboard** or **Send Article to Kindle**
4. Article arrives on your Kindle in 1-2 minutes

## CLI Usage

You can also use the command-line script:

```bash
export KINDLE_EMAIL="yourname@kindle.com"
export SMTP_EMAIL="you@gmail.com"
export SMTP_PASSWORD="xxxx xxxx xxxx xxxx"

python kindle_send.py "https://example.com/article"
```

> The CLI reads credentials from environment variables only. It does not use the Keychain.

## Notes

- Articles typically arrive within 1-2 minutes
- Your Kindle needs Wi-Fi to sync
- Images are disabled (Kindle email doesn't support external images)
- Works with most article sites; may struggle with heavy JavaScript sites
