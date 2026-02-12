#!/usr/bin/env python3
"""
Keen - macOS Menu Bar App
Send web articles to your Kindle with one click.
"""

import html as html_mod
import ipaddress
import json
import logging
import os
import re
import smtplib
import socket
import subprocess
import ssl
import threading
import traceback
from configparser import ConfigParser
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import keyring
import requests
import rumps
import trafilatura

# Config file location
CONFIG_DIR = Path.home() / "Library" / "Application Support" / "KindleSend"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_DIR = Path.home() / "Library" / "Logs" / "Keen"
LOG_FILE = LOG_DIR / "keen.log"
APP_NAME = "Keen"
KEYRING_SERVICE = "keen-sender"

# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------


def redact_url(url: str) -> str:
    """Strip querystring and fragment from a URL for safe logging."""
    try:
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    except Exception:
        return "<unparseable-url>"


def mask_email(email: str) -> str:
    """Mask the local part of an email for safe logging (e.g. j***@domain.com)."""
    if not email or "@" not in email:
        return "<no-email>"
    local, domain = email.rsplit("@", 1)
    if len(local) <= 1:
        masked = "*"
    else:
        masked = local[0] + "***"
    return f"{masked}@{domain}"


def _is_public_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True only if *addr* is a globally routable, non-reserved IP."""
    return addr.is_global and not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def check_url_ssrf(url: str) -> str | None:
    """Validate that *url* resolves only to public IPs.

    Returns None on success or an error message string on failure.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return "URL has no hostname"

    # Reject bare IP addresses in private ranges
    try:
        literal = ipaddress.ip_address(hostname)
        if not _is_public_ip(literal):
            return "URL points to a non-public IP address"
    except ValueError:
        pass  # hostname is a DNS name, resolve below

    # Resolve DNS and check every returned address
    try:
        addrinfos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return "DNS resolution failed for URL hostname"

    if not addrinfos:
        return "DNS resolution returned no results"

    for family, _type, _proto, _canon, sockaddr in addrinfos:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return f"Unparseable resolved IP: {ip_str}"
        if not _is_public_ip(addr):
            return "URL resolves to a non-public IP address"

    return None


def get_smtp_password(smtp_email: str) -> str:
    """Retrieve SMTP password from OS keychain."""
    if not smtp_email:
        return ""
    try:
        pw = keyring.get_password(KEYRING_SERVICE, smtp_email)
        return pw or ""
    except Exception:
        return ""


def set_smtp_password(smtp_email: str, password: str):
    """Store SMTP password in OS keychain."""
    keyring.set_password(KEYRING_SERVICE, smtp_email, password)


def migrate_password_to_keyring(config: dict, logger: logging.Logger | None = None):
    """If config.json still contains an smtp_password, move it to keyring and remove it."""
    password = config.get("smtp_password", "")
    smtp_email = config.get("smtp_email", "")
    if password and smtp_email:
        try:
            set_smtp_password(smtp_email, password)
            config.pop("smtp_password", None)
            save_config(config)
            if logger:
                logger.info("migrated smtp password from config.json to OS keychain")
        except Exception:
            if logger:
                logger.exception("failed to migrate smtp password to keychain")


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

    # Additional banner path: macOS may suppress rumps notifications depending on
    # app identity/notification settings. Use AppleScript as a best-effort fallback.
    if os.environ.get("KEEN_OSASCRIPT_NOTIFY", "1") == "1":
        try:
            safe_title = (title or "")[:200]
            safe_subtitle = (subtitle or "")[:200]
            safe_message = (message or "")[:500]

            def _esc(s: str) -> str:
                return s.replace("\\", "\\\\").replace('"', '\\"')

            script = (
                f'display notification "{_esc(safe_message)}" '
                f'with title "{_esc(safe_title)}" '
                f'subtitle "{_esc(safe_subtitle)}"'
            )
            subprocess.run(
                ["/usr/bin/osascript", "-e", script],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            logger.exception("failed to display osascript notification")


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
    """Load configuration from file or environment.

    Note: SMTP password is *not* stored in config.json; it lives in the
    OS keychain via the ``keyring`` library.  If an old config still
    contains ``smtp_password`` it will be migrated on first access.
    """
    config = {
        "kindle_email": os.environ.get("KINDLE_EMAIL", ""),
        "smtp_email": os.environ.get("SMTP_EMAIL", ""),
        "smtp_server": os.environ.get("SMTP_SERVER", "smtp.gmail.com"),
        "smtp_port": int(os.environ.get("SMTP_PORT", "587")),
    }
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                saved = json.load(f)
                config.update(saved)
        except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
            get_logger().warning("failed to load config file: %s", type(exc).__name__)

    # Migrate legacy plaintext password to OS keychain
    migrate_password_to_keyring(config)

    # Never keep password in the in-memory config dict
    config.pop("smtp_password", None)
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
        self._title_reset_timer: threading.Timer | None = None
        self._last_status: str = ""
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

    def _set_status(self, symbol: str, message: str = "", reset_after_s: float = 5.0):
        """Fallback status indicator when macOS notifications are suppressed.

        We keep the menu bar icon unchanged, but temporarily set the title to a small
        symbol so there is always some visible feedback.
        """
        self._last_status = message or self._last_status

        try:
            if self._title_reset_timer:
                self._title_reset_timer.cancel()
        except Exception:
            pass

        try:
            self.title = symbol
        except Exception:
            return

        def _reset():
            try:
                self.title = ""
            except Exception:
                pass

        if reset_after_s and reset_after_s > 0:
            self._title_reset_timer = threading.Timer(reset_after_s, _reset)
            self._title_reset_timer.daemon = True
            self._title_reset_timer.start()

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
            self.logger.warning("invalid url action=paste_url url=<redacted>")
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
                self.logger.info("clipboard url detected url=%s", redact_url(cleaned_url))
                self.process_url(cleaned_url, action="clipboard")
            else:
                notify(APP_NAME, "Invalid URL", "No valid http(s) URL in clipboard")
                self.logger.warning("invalid clipboard url value=<redacted>")
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

        # SMTP password — never prefill; blank = keep existing
        has_existing = bool(get_smtp_password(self.config.get("smtp_email", "")))
        hint = "Leave blank to keep current password" if has_existing else ""
        window = rumps.Window(
            message=f"Enter your Gmail app password:\n(Get one at myaccount.google.com/apppasswords)\n{hint}",
            title=f"{APP_NAME} Settings",
            default_text="",
            ok="Save",
            cancel="Cancel",
            dimensions=(350, 24),
        )
        response = window.run()
        if not response.clicked:
            return
        new_password = response.text.strip()
        if new_password:
            set_smtp_password(self.config["smtp_email"], new_password)

        # Save config (password is NOT in config dict)
        save_config(self.config)
        notify(APP_NAME, "Settings saved", "")

    def process_url(self, url: str, action: str):
        """Process URL in background thread."""
        # SSRF check: block private/reserved/link-local IPs
        ssrf_err = check_url_ssrf(url)
        if ssrf_err:
            self.logger.warning("SSRF blocked action=%s reason=%s", action, ssrf_err)
            self._set_status("!", "Blocked URL", reset_after_s=8.0)
            notify(APP_NAME, "Blocked", "URL target is not allowed")
            return

        self._set_status("…", "Sending…", reset_after_s=0)
        notify(APP_NAME, "Starting...", "Preparing article for Kindle")
        self.logger.info("processing started action=%s url=%s", action, redact_url(url))
        thread = threading.Thread(target=self._send_article_thread, args=(url, action))
        thread.daemon = True
        thread.start()

    def _send_article_thread(self, url: str, action: str):
        """Background thread for fetching and sending."""
        try:
            self.logger.info("extraction start action=%s url=%s", action, redact_url(url))
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
                    self.logger.exception("fetch failed action=%s url=%s", action, redact_url(url))
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
                    "empty extraction result action=%s url=%s", action, redact_url(url)
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
            self._set_status("✓", "Sent", reset_after_s=6.0)
            notify(APP_NAME, "Sent ✅", title[:60])

        except Exception as e:
            self.logger.error("processing failed action=%s url=%s", action, redact_url(url))
            self.logger.error("traceback:\n%s", traceback.format_exc())
            self._set_status("!", "Error", reset_after_s=10.0)
            notify(APP_NAME, "Error", str(e)[:120])

    def _wrap_html(self, content: str, title: str, author: str, url: str) -> str:
        """Wrap content in clean HTML document."""
        date = datetime.now().strftime("%B %d, %Y")
        esc_title = html_mod.escape(title)
        esc_author = html_mod.escape(author)
        esc_url = html_mod.escape(url)
        author_line = f"<p class='author'>By {esc_author}</p>" if author else ""

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{esc_title}</title>
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
    <h1>{esc_title}</h1>
    <div class="meta">
        {author_line}
        <p class="source">Source: {esc_url}</p>
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
        smtp_password = get_smtp_password(smtp_email)
        smtp_server = self.config.get("smtp_server", "smtp.gmail.com")
        smtp_port = self.config.get("smtp_port", 587)

        if not all([kindle_email, smtp_email, smtp_password]):
            raise ValueError(
                "Missing email configuration. Go to Settings to configure."
            )

        filename = self._sanitize_filename(title)
        self.logger.info(
            "email send start to=%s from=%s smtp_server=%r smtp_port=%r title=%r",
            mask_email(kindle_email),
            mask_email(smtp_email),
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

        ctx = ssl.create_default_context()
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.ehlo()
            server.login(smtp_email, smtp_password)
            response = server.send_message(msg)
            self.logger.info(
                "email send end title=%r smtp_response=%r", title, response
            )


def _set_app_icon():
    """Set the NSApplication icon before any UI is shown."""
    try:
        import AppKit
        app_icon = resource_path("assets/app-icon.png")
        if not app_icon.exists():
            app_icon = resource_path("app-icon.png")
        if app_icon.exists():
            image = AppKit.NSImage.alloc().initWithContentsOfFile_(str(app_icon.resolve()))
            if image:
                app = AppKit.NSApplication.sharedApplication()
                app.setApplicationIconImage_(image)
    except Exception:
        pass


if __name__ == "__main__":
    _set_app_icon()
    KindleSendApp().run()
