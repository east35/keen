#!/usr/bin/env python3
"""
kindle-send: Extract web articles and send to Kindle via email.

Usage:
    python kindle_send.py <url>

First run: Set environment variables:
    export KINDLE_EMAIL=your_kindle@kindle.com
    export SMTP_EMAIL=your_gmail@gmail.com
    export SMTP_PASSWORD=your_app_password
"""

import html as html_mod
import os
import re
import smtplib
import ssl
import sys
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from datetime import datetime

try:
    import trafilatura
except ImportError:
    print("Missing dependency. Run: pip install trafilatura")
    sys.exit(1)

# Configuration - set these as environment variables or edit directly
KINDLE_EMAIL = os.environ.get("KINDLE_EMAIL", "")
SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))


def extract_article(url: str) -> tuple[str, str, str]:
    """Extract article content, title, and author from URL."""
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise ValueError(f"Could not fetch URL: {url}")
    
    # Get metadata
    metadata = trafilatura.extract_metadata(downloaded)
    title = metadata.title if metadata and metadata.title else "Article"
    author = metadata.author if metadata and metadata.author else ""
    
    # Extract main content as HTML (no images - Kindle email doesn't support external images)
    content = trafilatura.extract(
        downloaded,
        include_links=True,
        include_images=False,
        include_formatting=True,
        output_format="html",
    )
    
    if not content:
        raise ValueError("Could not extract article content")
    
    # Remove duplicate title (trafilatura includes h1)
    content = re.sub(r'<h1>[^<]*</h1>\s*', '', content, count=1)
    
    return content, title, author


def wrap_html(content: str, title: str, author: str, url: str) -> str:
    """Wrap extracted content in a clean HTML document."""
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
        h1 {{
            line-height: 1.2;
            margin-bottom: 0.25em;
        }}
        .meta {{
            color: #666;
            font-size: 0.9em;
            margin-bottom: 2em;
            border-bottom: 1px solid #ccc;
            padding-bottom: 1em;
        }}
        .author {{
            margin: 0.25em 0;
        }}
        .source {{
            font-size: 0.85em;
            word-break: break-all;
        }}
        p {{
            margin: 1em 0;
        }}
        blockquote {{
            border-left: 3px solid #ccc;
            margin-left: 0;
            padding-left: 1em;
            color: #555;
        }}
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


def sanitize_filename(title: str) -> str:
    """Remove characters that may cause issues in email attachments."""
    # Replace problematic characters with safe alternatives
    sanitized = re.sub(r'[<>:"/\\|?*]', '', title)
    sanitized = sanitized.replace("'", "").replace("'", "")
    # Limit length to avoid issues
    return sanitized[:100].strip()


def send_to_kindle(html: str, title: str) -> None:
    """Send HTML document to Kindle via email."""
    if not all([KINDLE_EMAIL, SMTP_EMAIL, SMTP_PASSWORD]):
        print("\nError: Missing email configuration.")
        print("Set environment variables:")
        print("  export KINDLE_EMAIL=your_kindle@kindle.com")
        print("  export SMTP_EMAIL=your_gmail@gmail.com")
        print("  export SMTP_PASSWORD=your_app_password")
        print("\nTo get a Gmail app password:")
        print("  1. Enable 2FA on your Google account")
        print("  2. Go to myaccount.google.com → Security → App passwords")
        print("  3. Generate a password for 'Mail'")
        sys.exit(1)
    
    filename = sanitize_filename(title)
    
    msg = MIMEMultipart()
    msg["From"] = SMTP_EMAIL
    msg["To"] = KINDLE_EMAIL
    msg["Subject"] = f"[Article] {title}"
    
    # Attach HTML file - Kindle will convert it
    attachment = MIMEApplication(html.encode("utf-8"), Name=f"{filename}.html")
    attachment["Content-Disposition"] = f'attachment; filename="{filename}.html"'
    msg.attach(attachment)
    
    ctx = ssl.create_default_context()
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.ehlo()
        server.starttls(context=ctx)
        server.ehlo()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)


def main():
    if len(sys.argv) != 2:
        print("Usage: python kindle_send.py <url>")
        print("       kindle-send <url>")
        sys.exit(1)
    
    url = sys.argv[1]
    
    print(f"Fetching: {url}")
    content, title, author = extract_article(url)
    print(f"Extracted: {title}")
    
    html = wrap_html(content, title, author, url)
    
    print(f"Sending to: {KINDLE_EMAIL}")
    send_to_kindle(html, title)
    print("✓ Sent successfully")


if __name__ == "__main__":
    main()
