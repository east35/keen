# kindle-send

Send web articles to your Kindle from the command line.

## Setup (5 minutes)

### 1. Install

```bash
pip install trafilatura
```

### 2. Get your Kindle email address

Find it on your Kindle: Settings → Your Account → Send-to-Kindle Email

Or at: amazon.com/myk → Preferences → Personal Document Settings

It looks like: `yourname_abc123@kindle.com`

### 3. Authorize your sending email

In the same Amazon settings page, scroll to "Approved Personal Document E-mail List" and add your Gmail address.

### 4. Get a Gmail app password

1. Enable 2FA on your Google account (if not already)
2. Go to: https://myaccount.google.com/apppasswords
3. Generate a password for "Mail"
4. Copy the 16-character password (spaces don't matter)

### 5. Set environment variables

Add to your `~/.bashrc` or `~/.zshrc`:

```bash
export KINDLE_EMAIL="yourname_abc123@kindle.com"
export SMTP_EMAIL="you@gmail.com"
export SMTP_PASSWORD="xxxx xxxx xxxx xxxx"
```

Then reload: `source ~/.bashrc`

## Usage

```bash
python kindle_send.py "https://example.com/interesting-article"
```

### Optional: Make it a command

```bash
chmod +x kindle_send.py
sudo ln -s $(pwd)/kindle_send.py /usr/local/bin/kindle-send

# Now you can just run:
kindle-send "https://example.com/article"
```

## Notes

- Articles typically arrive within 1-2 minutes
- Your Kindle needs Wi-Fi to sync
- Images are disabled by default (they bloat the file and render poorly)
- Works with most article sites; may struggle with heavy JavaScript sites
