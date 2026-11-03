"""Outbound failure alerts.

Posts a Slack/Discord-compatible {"text": ...} JSON payload to
config.ALERT_WEBHOOK_URL whenever a scheduled job fails, skips, or comes
back empty. If no webhook is configured, falls back to a print so the
event at least shows up in `fly logs`.

Configure with: fly secrets set ALERT_WEBHOOK_URL=https://hooks.slack.com/...
(or any endpoint that accepts a JSON body with a "text" field — Slack
incoming webhooks, Discord webhooks via /slack alias, ntfy, etc.)
"""
from __future__ import annotations

import requests

import config


def send_alert(title: str, detail: str = "") -> None:
    """Best-effort alert — never raises, so a broken webhook can't take down a job."""
    text = f"⚠️ PickAParlay — {title}"
    if detail:
        text += f"\n{detail}"

    if not config.ALERT_WEBHOOK_URL:
        print(f"[alert] (no ALERT_WEBHOOK_URL configured) {text}")
        return

    try:
        requests.post(config.ALERT_WEBHOOK_URL, json={"text": text}, timeout=10)
    except requests.RequestException as exc:
        print(f"[alert] Failed to deliver alert ({exc}). Original message: {text}")
