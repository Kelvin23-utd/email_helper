#!/usr/bin/env python3
"""Hourly orchestrator for summarizing unread UTD Mail messages."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Sequence
from urllib import error, request

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
TMP_DIR = BASE_DIR / "tmp"
SCRIPT_PATH = BASE_DIR / "export_unread.scpt"
DEFAULT_ENV_PATH = BASE_DIR / ".env"


class ConfigError(RuntimeError):
    """Raised when required configuration is missing."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=str(DEFAULT_ENV_PATH), help="Path to .env file with secrets")
    parser.add_argument("--lookback", type=int, help="Override LOOKBACK_MINUTES from .env", default=None)
    parser.add_argument("--max-emails", type=int, help="Override MAX_EMAILS from .env", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Skip Gemini + Discord calls; just log parsed emails")
    return parser.parse_args()


def load_env(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        values[key.strip()] = raw_value.strip()
    return values


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.utcnow().strftime("%Y%m%d")
    log_path = LOG_DIR / f"run_{timestamp}.log"
    handlers = [logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler(sys.stdout)]
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=handlers)


def ensure_tmp_dir() -> None:
    TMP_DIR.mkdir(parents=True, exist_ok=True)


def resolve_config(args: argparse.Namespace, env_values: Dict[str, str]) -> Dict[str, str]:
    config = dict(env_values)
    if args.lookback is not None:
        config["LOOKBACK_MINUTES"] = str(args.lookback)
    if args.max_emails is not None:
        config["MAX_EMAILS"] = str(args.max_emails)
    required = ["GEMINI_API_KEY", "DISCORD_WEBHOOK"]
    missing = [key for key in required if not config.get(key)]
    if missing and not args.dry_run:
        raise ConfigError(f"Missing required config keys: {', '.join(missing)}")
    config.setdefault("LOOKBACK_MINUTES", "60")
    config.setdefault("MAX_EMAILS", "15")
    config.setdefault("GEMINI_MODEL", "gemini-1.5-flash")
    return config


def run_applescript(lookback: int, max_emails: int, export_path: Path) -> None:
    if not SCRIPT_PATH.exists():
        raise FileNotFoundError(f"AppleScript not found at {SCRIPT_PATH}")
    cmd = [
        "osascript",
        str(SCRIPT_PATH),
        str(lookback),
        str(max_emails),
        str(export_path),
    ]
    logging.info("Running AppleScript export (%s unread max, %s min lookback)", max_emails, lookback)
    subprocess.run(cmd, check=True)


def parse_tsv(tsv_path: Path) -> List[Dict[str, str]]:
    if not tsv_path.exists():
        logging.info("No TSV export found at %s", tsv_path)
        return []
    with tsv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = [row for row in reader if row]
    for row in rows:
        row["received_at"] = row.get("received_at", "")
    rows.sort(key=lambda r: r.get("received_at", ""), reverse=True)
    return rows


def build_prompt(email_row: Dict[str, str]) -> str:
    template = (
        "Summarize the following unread email in under 70 words. "
        "Highlight sender, topic, and any action items. Use single paragraph.\n"
        "Sender: {sender}\nSubject: {subject}\nReceived: {received_at}\nBody:\n{body}\n"
    )
    body = email_row.get("body", "")[:4000]
    return template.format(
        sender=email_row.get("sender", "Unknown"),
        subject=email_row.get("subject", "(no subject)"),
        received_at=email_row.get("received_at", ""),
        body=body,
    )


def gemini_request(api_key: str, model: str, prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=30) as resp:
            response_body = resp.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        logging.error("Gemini HTTPError: %s %s", exc.code, detail)
        raise
    except error.URLError as exc:
        logging.error("Gemini URLError: %s", exc)
        raise
    response_json = json.loads(response_body)
    candidates = response_json.get("candidates") or []
    for cand in candidates:
        content = cand.get("content") or {}
        parts = content.get("parts") or []
        for part in parts:
            text = part.get("text")
            if text:
                return text.strip()
    raise RuntimeError("Gemini response did not contain text")


def summarize_emails(rows: Sequence[Dict[str, str]], config: Dict[str, str], dry_run: bool) -> List[Dict[str, str]]:
    summaries = []
    api_key = config.get("GEMINI_API_KEY", "")
    model = config.get("GEMINI_MODEL", "gemini-1.5-flash")
    for row in rows:
        prompt = build_prompt(row)
        if dry_run:
            summary_text = "[dry-run] " + prompt.splitlines()[0]
        else:
            try:
                summary_text = gemini_request(api_key, model, prompt)
            except Exception as exc:  # noqa: BLE001
                logging.exception("Gemini summarization failed for %s", row.get("subject"))
                continue
        summaries.append({"sender": row.get("sender", "Unknown"), "subject": row.get("subject", "(no subject)"), "summary": summary_text})
    return summaries


def format_discord_payload(summaries: Sequence[Dict[str, str]]) -> Dict[str, str]:
    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"**UTD Mail Digest - {timestamp}**"]
    divider = "-" * 30
    for entry in summaries:
        header = f"**{entry['sender']} — {entry['subject']}**"
        lines.append(header)
        lines.append(entry["summary"].strip())
        lines.append(divider)
    content = "\n".join(lines[:-1] if lines[-1] == divider else lines)
    return {"content": content[:1900]}


def post_to_discord(webhook_url: str, payload: Dict[str, str]) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(webhook_url, data=data, headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=15) as resp:
            resp.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        logging.error("Discord HTTPError: %s %s", exc.code, detail)
        raise
    except error.URLError as exc:
        logging.error("Discord URLError: %s", exc)
        raise


def main() -> int:
    args = parse_args()
    setup_logging()
    ensure_tmp_dir()
    env_values = load_env(Path(args.env))
    config = resolve_config(args, env_values)

    lookback = int(config["LOOKBACK_MINUTES"])
    max_emails = int(config["MAX_EMAILS"])

    fd, tmp_name = tempfile.mkstemp(prefix="mail_export_", suffix=".tsv", dir=TMP_DIR)
    os.close(fd)
    tmp_export = Path(tmp_name)
    try:
        run_applescript(lookback, max_emails, tmp_export)
        emails = parse_tsv(tmp_export)
        if not emails:
            logging.info("No unread emails found in lookback window; exiting.")
            return 0
        logging.info("Read %s unread emails from Apple Mail", len(emails))
        summaries = summarize_emails(emails[:max_emails], config, args.dry_run)
        if not summaries:
            logging.info("No summaries generated; nothing to send.")
            return 0
        if args.dry_run:
            for entry in summaries:
                logging.info("[DRY RUN] %s — %s :: %s", entry["sender"], entry["subject"], entry["summary"])
            return 0
        payload = format_discord_payload(summaries)
        post_to_discord(config["DISCORD_WEBHOOK"], payload)
        logging.info("Posted %s summaries to Discord.", len(summaries))
        return 0
    finally:
        try:
            tmp_export.unlink(missing_ok=True)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConfigError as exc:
        logging.error(str(exc))
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        logging.error("AppleScript failed: %s", exc)
        sys.exit(exc.returncode)
