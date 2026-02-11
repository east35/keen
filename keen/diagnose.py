#!/usr/bin/env python3
"""Diagnostics CLI for Keen extraction pipeline."""

import argparse
import logging
import traceback
from configparser import ConfigParser
from pathlib import Path

import trafilatura

LOG_DIR = Path.home() / "Library" / "Logs" / "Keen"
LOG_FILE = LOG_DIR / "keen.log"

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


def get_logger() -> logging.Logger:
    """Set up diagnostics logger."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("keen.diagnose")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s")
        )
        logger.addHandler(handler)
    return logger


def build_trafilatura_config(logger: logging.Logger) -> ConfigParser:
    """Build extraction config with guaranteed safe defaults."""
    config = ConfigParser()
    config.read_dict({"DEFAULT": TRAFILATURA_DEFAULTS})
    try:
        settings_file = Path(trafilatura.settings.__file__).with_name("settings.cfg")
        if settings_file.exists():
            config.read(settings_file)
    except Exception:
        logger.exception("failed to load trafilatura settings file, using fallbacks")

    for key, value in TRAFILATURA_DEFAULTS.items():
        if not config.has_option("DEFAULT", key):
            config.set("DEFAULT", key, value)
    return config


def run(url: str) -> int:
    """Run a diagnostic extraction and return process exit code."""
    logger = get_logger()
    config = build_trafilatura_config(logger)
    logger.info("diagnostics start url=%r", url)
    print(f"Testing extraction for: {url}")
    try:
        downloaded = trafilatura.fetch_url(url, config=config)
        if not downloaded:
            logger.error("diagnostics fetch failed url=%r", url)
            print("Fetch failed")
            return 2

        metadata = trafilatura.extract_metadata(downloaded)
        title = metadata.title if metadata and metadata.title else "Article"
        extracted = trafilatura.extract(downloaded, output_format="txt", config=config)
        extracted_len = len(extracted or "")
        logger.info("diagnostics end title=%r extracted_chars=%s", title, extracted_len)
        print(f"Title: {title}")
        print(f"Extracted chars: {extracted_len}")
        return 0
    except Exception:
        logger.error("diagnostics failed url=%r", url)
        logger.error("traceback:\n%s", traceback.format_exc())
        print("Diagnostics failed. See ~/Library/Logs/Keen/keen.log")
        return 1


def main():
    parser = argparse.ArgumentParser(description="Keen extraction diagnostics")
    parser.add_argument("url", help="URL to test extraction against")
    args = parser.parse_args()
    raise SystemExit(run(args.url))


if __name__ == "__main__":
    main()
