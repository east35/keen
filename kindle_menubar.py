#!/usr/bin/env python3
"""
Keen - macOS Menu Bar App
Send web articles to your Kindle with one click.
"""

import json
import logging
import os
import re
import smtplib
import threading
import traceback
from configparser import ConfigParser
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from urllib.parse import urlparse

import requests
import rumps
import trafilatura

# Config file location
CONFIG_DIR = Path.home() / "Library" / "Application Support" / "KindleSend"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_DIR = Path.home() / "Library" / "Logs" / "Keen"
LOG_FILE = LOG_DIR / "keen.log"
APP_NAME = "Keen"

TRAFILATURA_DEFAULTS = {
    "DOWNLOAD_TIMEOUT": "30",
    "MAX_FILE_SIZE": "20000000",
    "MIN_FILE_SIZE": "10",
    "SLEEP_TIME": "5.0",
    "USER_AGENTS": "",
    "COOKIE": "",
    "MAX_REDIRECTS": "2",
    "MIN_EXTRACTED_SIZE": "250",
    "MIN_EXTRACTED_COMM_SIZE": "1",
    "MIN_OUTPUT_SIZE": "1",
    "MIN_OUTPUT_COMM_SIZE": "1",
    "MAX_TREE_SIZE": "",
    "EXTRACTION_TIMEOUT": "30",
    "MIN_DUPLCHECK_SIZE": "100",
    "MAX_REPETITIONS": "2",
    "EXTENSIVE_DATE_SEARCH": "on",
    "EXTERNAL_URLS": "off",
}

LOGGER = None


def get_logger() -> logging.Logger:
    """Create/reuse file logger for app diagnostics."""
    global LOGGER
    if LOGGER is not None:
        return LOGGER

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("keen")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s")
        )
        logger.addHandler(handler)
    LOGGER = logger
    return logger


def notify(title: str, subtitle: str, message: str):
    """Show a user notification and log it."""
    logger = get_logger()
    logger.info(
        "notification title=%r subtitle=%r message=%r", title, subtitle, message
    )
    try:
        rumps.notification(title, subtitle, message)
    except Exception:
        logger.exception("failed to display macOS notification")


def is_valid_url(url: str) -> bool:
    """Validate HTTP(S) URLs."""
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def build_trafilatura_config() -> ConfigParser:
    """Build extraction config with safe defaults so missing options never crash."""
    config = ConfigParser()
    config.read_dict({"DEFAULT": TRAFILATURA_DEFAULTS})

    try:
        settings_file = Path(trafilatura.settings.__file__).with_name("settings.cfg")
        if settings_file.exists():
            config.read(settings_file)
    except Exception:
        get_logger().exception(
            "failed to load trafilatura settings.cfg, using fallbacks"
        )

    for key, value in TRAFILATURA_DEFAULTS.items():
        if not config.has_option("DEFAULT", key):
            config.set("DEFAULT", key, value)
    return config


def load_config() -> dict:
    """Load configuration from file or environment."""
    config = {
        "kindle_email": os.environ.get("KINDLE_EMAIL", ""),
        "smtp_email": os.environ.get("SMTP_EMAIL", ""),
        "smtp_password": os.environ.get("SMTP_PASSWORD", ""),
        "smtp_server": os.environ.get("SMTP_SERVER", "smtp.gmail.com"),
        "smtp_port": int(os.environ.get("SMTP_PORT", "587")),
    }
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                saved = json.load(f)
                config.update(saved)
        except:
            pass
    return config


def save_config(config: dict):
    """Save configuration to file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def resource_path(name: str) -> Path:
    """Resolve resources in dev and PyInstaller bundle contexts."""
    import sys

    meipass = getattr(sys, "_MEIPASS", None)
    candidates = [
        Path(__file__).parent / name,
    ]
    if meipass:
        candidates.insert(0, Path(meipass) / name)
    if getattr(sys, "frozen", False):
        bundle_dir = Path(sys.executable).parent.parent / "Resources"
        candidates.insert(0, bundle_dir / name)

    for path in candidates:
        if path.exists():
            return path
    return Path(name)


def get_icon_path() -> str:
    """Get path to menu bar template icon."""
    icon = resource_path("iconTemplate.png")
    if icon.exists():
        return str(icon)
    return None


class KindleSendApp(rumps.App):
    def __init__(self):
        # Template icon ensures proper automatic tinting in light/dark mode.
        icon_path = get_icon_path()
        if icon_path:
            super().__init__("", icon=icon_path, template=True, quit_button=None)
        else:
            # Fallback to text
            super().__init__("K", quit_button=None)
        self.logger = get_logger()
        self.config = load_config()
        self.extract_config = build_trafilatura_config()
        self.logger.info("app started")

        self.menu = [
            rumps.MenuItem("Send Article to Kindle", callback=self.send_article),
            rumps.MenuItem("Send from Clipboard", callback=self.send_from_clipboard),
            None,  # Separator
            rumps.MenuItem("Settings...", callback=self.open_settings),
            rumps.MenuItem("Quit", callback=rumps.quit_application),
        ]

    @rumps.clicked("Send Article to Kindle")
    def send_article(self, _):
        self.logger.info("action invoked action=paste_url")
        window = rumps.Window(
            message="Paste the article URL:",
            title="Send to Kindle",
            default_text="",
            ok="Send",
            cancel="Cancel",
            dimensions=(400, 24),
        )
        response = window.run()
        if not response.clicked:
            notify(APP_NAME, "Canceled", "Send canceled")
            self.logger.info("action canceled action=paste_url")
            return

        url = response.text.strip()
        if not url:
            notify(APP_NAME, "Canceled", "No URL entered")
            self.logger.info("action canceled action=paste_url reason=empty_input")
            return

        if not is_valid_url(url):
            notify(APP_NAME, "Invalid URL", "Please enter a valid http(s) URL")
            self.logger.warning("invalid url action=paste_url url=%r", url)
            return

        self.process_url(url, action="paste_url")

    @rumps.clicked("Send from Clipboard")
    def send_from_clipboard(self, _):
        self.logger.info("action invoked action=clipboard")
        try:
            import AppKit

            pb = AppKit.NSPasteboard.generalPasteboard()
            url = pb.stringForType_(AppKit.NSStringPboardType)
            if url and is_valid_url(url.strip()):
                cleaned_url = url.strip()
                self.logger.info("clipboard url detected url=%r", cleaned_url)
                self.process_url(cleaned_url, action="clipboard")
            else:
                notify(APP_NAME, "Invalid URL", "No valid http(s) URL in clipboard")
                self.logger.warning("invalid clipboard url value=%r", url)
        except Exception as e:
            self.logger.exception("clipboard action failed")
            notify(APP_NAME, "Error", str(e))

    @rumps.clicked("Settings...")
    def open_settings(self, _):
        """Open settings dialog."""
        # Kindle email
        window = rumps.Window(
            message="Enter your Kindle email address:\n(e.g., yourname@kindle.com)",
            title=f"{APP_NAME} Settings",
            default_text=self.config.get("kindle_email", ""),
            ok="Next",
            cancel="Cancel",
            dimensions=(350, 24),
        )
        response = window.run()
        if not response.clicked:
            return
        self.config["kindle_email"] = response.text.strip()

        # SMTP email
        window = rumps.Window(
            message="Enter your Gmail address:",
            title=f"{APP_NAME} Settings",
            default_text=self.config.get("smtp_email", ""),
            ok="Next",
            cancel="Cancel",
            dimensions=(350, 24),
        )
        response = window.run()
        if not response.clicked:
            return
        self.config["smtp_email"] = response.text.strip()

        # SMTP password
        window = rumps.Window(
            message="Enter your Gmail app password:\n(Get one at myaccount.google.com/apppasswords)",
            title=f"{APP_NAME} Settings",
            default_text=self.config.get("smtp_password", ""),
            ok="Save",
            cancel="Cancel",
            dimensions=(350, 24),
        )
        response = window.run()
        if not response.clicked:
            return
        self.config["smtp_password"] = response.text.strip()

        # Save config
        save_config(self.config)
        notify(APP_NAME, "Settings saved", "")

    def process_url(self, url: str, action: str):
        """Process URL in background thread."""
        notify(APP_NAME, "Starting...", "Preparing article for Kindle")
        self.logger.info("processing started action=%s url=%r", action, url)
        thread = threading.Thread(target=self._send_article_thread, args=(url, action))
        thread.daemon = True
        thread.start()

    def _send_article_thread(self, url: str, action: str):
        """Background thread for fetching and sending."""
        try:
            self.logger.info("extraction start action=%s url=%r", action, url)
            # Fetch with trafilatura, fallback to requests if needed
            downloaded = trafilatura.fetch_url(url, config=self.extract_config)
            if not downloaded:
                # Fallback: try with requests
                try:
                    response = requests.get(
                        url,
                        timeout=30,
                        headers={
                            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                        },
                    )
                    response.raise_for_status()
                    downloaded = response.text
                    self.logger.info(
                        "fallback fetch succeeded action=%s status=%s",
                        action,
                        response.status_code,
                    )
                except Exception as req_err:
                    self.logger.exception("fetch failed action=%s url=%r", action, url)
                    notify(APP_NAME, "Error", f"Could not fetch: {str(req_err)[:80]}")
                    return

            # Get metadata
            metadata = trafilatura.extract_metadata(downloaded)
            title = metadata.title if metadata and metadata.title else "Article"
            author = metadata.author if metadata and metadata.author else ""

            # Extract content as HTML (no images - Kindle email doesn't support external images)
            content = trafilatura.extract(
                downloaded,
                include_links=True,
                include_images=False,
                include_formatting=True,
                output_format="html",
                config=self.extract_config,
            )

            if not content:
                self.logger.error(
                    "empty extraction result action=%s url=%r", action, url
                )
                notify(APP_NAME, "Error", "Could not extract content")
                return

            self.logger.info(
                "extraction end action=%s title=%r extracted_chars=%s",
                action,
                title,
                len(content),
            )

            # Remove duplicate title (trafilatura includes h1)
            content = re.sub(r"<h1>[^<]*</h1>\s*", "", content, count=1)

            # Build HTML
            self.logger.info("conversion start action=%s title=%r", action, title)
            html = self._wrap_html(content, title, author, url)
            self.logger.info(
                "conversion end action=%s title=%r html_chars=%s",
                action,
                title,
                len(html),
            )

            # Send to Kindle
            self._send_email(html, title)
            notify(APP_NAME, "Sent ✅", title[:60])

        except Exception as e:
            self.logger.error("processing failed action=%s url=%r", action, url)
            self.logger.error("traceback:\n%s", traceback.format_exc())
            notify(APP_NAME, "Error", str(e)[:120])

    def _wrap_html(self, content: str, title: str, author: str, url: str) -> str:
        """Wrap content in clean HTML document."""
        date = datetime.now().strftime("%B %d, %Y")
        author_line = f"<p class='author'>By {author}</p>" if author else ""

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <style>
        body {{
            font-family: Georgia, serif;
            line-height: 1.6;
            max-width: 40em;
            margin: 0 auto;
            padding: 1em;
        }}
        h1 {{ line-height: 1.2; margin-bottom: 0.25em; }}
        .meta {{ color: #666; font-size: 0.9em; margin-bottom: 2em; border-bottom: 1px solid #ccc; padding-bottom: 1em; }}
        .author {{ margin: 0.25em 0; }}
        .source {{ font-size: 0.85em; word-break: break-all; }}
        p {{ margin: 1em 0; }}
        figure {{ margin: 2em 0; }}
        figcaption {{ font-size: 0.9em; color: #666; }}
        blockquote {{ border-left: 3px solid #ccc; margin-left: 0; padding-left: 1em; color: #555; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <div class="meta">
        {author_line}
        <p class="source">Source: {url}</p>
        <p class="date">Saved: {date}</p>
    </div>
    <article>
        {content}
    </article>
</body>
</html>"""

    def _sanitize_filename(self, title: str) -> str:
        """Remove problematic characters from filename."""
        sanitized = re.sub(r'[<>:"/\\|?*]', "", title)
        sanitized = sanitized.replace("'", "").replace("'", "")
        return sanitized[:100].strip()

    def _send_email(self, html: str, title: str):
        """Send HTML to Kindle via email."""
        kindle_email = self.config.get("kindle_email", "")
        smtp_email = self.config.get("smtp_email", "")
        smtp_password = self.config.get("smtp_password", "")
        smtp_server = self.config.get("smtp_server", "smtp.gmail.com")
        smtp_port = self.config.get("smtp_port", 587)

        if not all([kindle_email, smtp_email, smtp_password]):
            raise ValueError(
                "Missing email configuration. Go to Settings to configure."
            )

        filename = self._sanitize_filename(title)
        self.logger.info(
            "email send start to=%r from=%r smtp_server=%r smtp_port=%r title=%r",
            kindle_email,
            smtp_email,
            smtp_server,
            smtp_port,
            title,
        )

        msg = MIMEMultipart()
        msg["From"] = smtp_email
        msg["To"] = kindle_email
        msg["Subject"] = f"[Article] {title}"

        attachment = MIMEApplication(html.encode("utf-8"), Name=f"{filename}.html")
        attachment["Content-Disposition"] = f'attachment; filename="{filename}.html"'
        msg.attach(attachment)

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_email, smtp_password)
            response = server.send_message(msg)
            self.logger.info(
                "email send end title=%r smtp_response=%r", title, response
            )


if __name__ == "__main__":
    KindleSendApp().run()
