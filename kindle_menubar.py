#!/usr/bin/env python3
"""
Kindle Send - macOS Menu Bar App
Send web articles to your Kindle with one click.
"""

import rumps
import threading
import smtplib
import re
import os
import json
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime
from pathlib import Path

import trafilatura
import requests

# Config file location
CONFIG_DIR = Path.home() / "Library" / "Application Support" / "KindleSend"
CONFIG_FILE = CONFIG_DIR / "config.json"


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


def get_icon_path() -> str:
    """Get path to menu bar icon."""
    import sys
    # Try multiple locations
    candidates = [
        Path(__file__).parent / "iconTemplate.png",  # Dev mode
    ]
    if getattr(sys, 'frozen', False):
        # Running as compiled app - check Resources folder
        bundle_dir = Path(sys.executable).parent.parent / "Resources"
        candidates.insert(0, bundle_dir / "iconTemplate.png")
    
    for icon in candidates:
        if icon.exists():
            return str(icon)
    return None


class KindleSendApp(rumps.App):
    def __init__(self):
        # Use template icon for light/dark mode support
        icon_path = get_icon_path()
        if icon_path:
            super().__init__("", icon=icon_path, template=True, quit_button=None)
        else:
            # Fallback to text
            super().__init__("K", quit_button=None)
        self.config = load_config()

        self.menu = [
            rumps.MenuItem("Send Article to Kindle", callback=self.send_article),
            rumps.MenuItem("Send from Clipboard", callback=self.send_from_clipboard),
            None,  # Separator
            rumps.MenuItem("Settings...", callback=self.open_settings),
            rumps.MenuItem("Quit", callback=rumps.quit_application),
        ]

    @rumps.clicked("Send Article to Kindle")
    def send_article(self, _):
        window = rumps.Window(
            message="Paste the article URL:",
            title="Send to Kindle",
            default_text="",
            ok="Send",
            cancel="Cancel",
            dimensions=(400, 24),
        )
        response = window.run()
        if response.clicked and response.text.strip():
            self.process_url(response.text.strip())

    @rumps.clicked("Send from Clipboard")
    def send_from_clipboard(self, _):
        try:
            import AppKit
            pb = AppKit.NSPasteboard.generalPasteboard()
            url = pb.stringForType_(AppKit.NSStringPboardType)
            if url and url.startswith(("http://", "https://")):
                self.process_url(url.strip())
            else:
                rumps.notification("Kindle Send", "", "No valid URL in clipboard")
        except Exception as e:
            rumps.notification("Kindle Send", "Error", str(e))

    @rumps.clicked("Settings...")
    def open_settings(self, _):
        """Open settings dialog."""
        # Kindle email
        window = rumps.Window(
            message="Enter your Kindle email address:\n(e.g., yourname@kindle.com)",
            title="Kindle Send Settings",
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
            title="Kindle Send Settings",
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
            title="Kindle Send Settings",
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
        rumps.notification("Kindle Send", "Settings saved", "")

    def process_url(self, url: str):
        """Process URL in background thread."""
        rumps.notification("Kindle Send", "", f"Fetching article...")
        thread = threading.Thread(target=self._send_article_thread, args=(url,))
        thread.daemon = True
        thread.start()

    def _send_article_thread(self, url: str):
        """Background thread for fetching and sending."""
        try:
            # Fetch with trafilatura, fallback to requests if needed
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                # Fallback: try with requests
                try:
                    response = requests.get(url, timeout=30, headers={
                        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
                    })
                    response.raise_for_status()
                    downloaded = response.text
                except Exception as req_err:
                    rumps.notification("Kindle Send", "Error", f"Could not fetch: {str(req_err)[:50]}")
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
            )

            if not content:
                rumps.notification("Kindle Send", "Error", "Could not extract content")
                return

            # Remove duplicate title (trafilatura includes h1)
            content = re.sub(r'<h1>[^<]*</h1>\s*', '', content, count=1)

            # Build HTML
            html = self._wrap_html(content, title, author, url)

            # Send to Kindle
            self._send_email(html, title)
            rumps.notification("Kindle Send", "✓ Sent!", title[:50])

        except Exception as e:
            rumps.notification("Kindle Send", "Error", str(e)[:100])

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
        sanitized = re.sub(r'[<>:"/\\|?*]', '', title)
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
            raise ValueError("Missing email configuration. Go to Settings to configure.")

        filename = self._sanitize_filename(title)

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
            server.send_message(msg)


if __name__ == "__main__":
    KindleSendApp().run()
