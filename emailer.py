"""Gmail digest sender."""

from __future__ import annotations

import base64
import os
from datetime import datetime
from email.mime.text import MIMEText
from html import escape
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import DIGEST_URL, GMAIL_CREDENTIALS_PATH, GMAIL_FROM, GMAIL_TO, TOP_N_EMAIL, VERCEL_URL
from logging_config import get_logger

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
ENV_SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]
PROJECT_ROOT = Path(__file__).resolve().parent
TOKEN_PATH = PROJECT_ROOT / "token.json"
TOKEN_URI = "https://oauth2.googleapis.com/token"
log = get_logger("emailer")


def _resolve_credentials_path() -> Path:
    candidate = Path(GMAIL_CREDENTIALS_PATH)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate


def _save_credentials(creds: Credentials) -> None:
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")


def _load_env_credentials() -> Credentials | None:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN", "").strip()
    if not client_id or not client_secret or not refresh_token:
        return None

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=ENV_SCOPES,
    )
    creds.refresh(Request())
    return creds


def _has_env_google_auth() -> bool:
    return all(
        [
            os.getenv("GOOGLE_CLIENT_ID", "").strip(),
            os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
            os.getenv("GOOGLE_REFRESH_TOKEN", "").strip(),
        ]
    )


def _load_credentials(interactive: bool = True) -> Credentials:
    creds: Credentials | None = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_credentials(creds)
        return creds

    if creds and creds.valid:
        return creds

    env_creds = _load_env_credentials()
    if env_creds is not None:
        return env_creds

    if not interactive:
        raise RuntimeError(f"Gmail token missing or invalid. Run setup_gmail_auth.py to create {TOKEN_PATH}.")

    credentials_path = _resolve_credentials_path()
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(port=0)
    _save_credentials(creds)
    return creds


def authorize_gmail() -> Path:
    _load_credentials(interactive=True)
    return TOKEN_PATH


def _gmail_service(interactive: bool = False):
    creds = _load_credentials(interactive=interactive)
    return build("gmail", "v1", credentials=creds)


def _send_html_message(subject: str, html_body: str, interactive: bool = False) -> None:
    if not GMAIL_TO:
        log.info("Skipping email send because GMAIL_TO is not configured")
        return

    credentials_path = _resolve_credentials_path()
    has_env_google_auth = _has_env_google_auth()
    if not credentials_path.exists() and not has_env_google_auth:
        log.warning(
            "Skipping email send because Gmail credentials were not found at %s and env-based Gmail auth is not configured",
            credentials_path,
        )
        return

    service = _gmail_service(interactive=interactive)

    message = MIMEText(html_body, "html")
    message["to"] = GMAIL_TO
    message["from"] = GMAIL_FROM or GMAIL_TO
    message["subject"] = subject

    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": encoded}).execute()


def _top_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(jobs, key=lambda job: job.get("score", 0), reverse=True)
    return ranked[:TOP_N_EMAIL]


def _digest_url() -> str:
    return VERCEL_URL or DIGEST_URL


def _render_email_html(jobs: list[dict[str, Any]], digest_url: str) -> str:
    rows = []
    for job in jobs:
        score = escape(str(job.get("score", 0)))
        title = escape(str(job.get("title", "")))
        company = escape(str(job.get("company", "")))
        location = escape(str(job.get("location", "")))
        url = escape(str(job.get("url", "")), quote=True)
        rows.append(
            f"""
            <tr>
              <td style="padding:14px 12px;border-bottom:1px solid #333333;vertical-align:top;width:84px;text-align:center;">
                <div style="display:inline-block;min-width:52px;padding:8px 10px;border:1px solid #333333;color:#ffffff;background:#000000;font-size:22px;font-weight:700;letter-spacing:0.04em;">
                  {score}
                </div>
              </td>
              <td style="padding:14px 12px;border-bottom:1px solid #333333;vertical-align:top;color:#ffffff;">
                <div style="font-size:15px;font-weight:700;line-height:1.45;">{title}</div>
                <div style="font-size:13px;line-height:1.6;color:#ffffff;opacity:0.78;">{company} | {location or 'Location Unknown'}</div>
              </td>
              <td style="padding:14px 12px;border-bottom:1px solid #333333;vertical-align:top;text-align:right;white-space:nowrap;">
                <a href="{url}" style="color:#ffffff;text-decoration:none;font-size:13px;font-weight:700;">APPLY →</a>
              </td>
            </tr>
            """
        )

    footer_link = ""
    if digest_url:
        footer_link = (
            f'<div style="margin-top:20px;font-size:13px;">'
            f'<a href="{escape(digest_url, quote=True)}" style="color:#ffffff;text-decoration:none;">View full digest →</a>'
            f"</div>"
        )

    return f"""<!doctype html>
<html lang="en">
  <body style="margin:0;padding:0;background:#000000;color:#ffffff;font-family:'JetBrains Mono',Consolas,Menlo,monospace;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#000000;">
      <tr>
        <td align="center" style="padding:24px 16px;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:880px;border-collapse:collapse;background:#000000;color:#ffffff;">
            <tr>
              <td style="padding:8px 0 20px 0;border-top:1px solid #333333;border-bottom:1px solid #333333;">
                <div style="font-size:30px;font-weight:800;letter-spacing:0.26em;text-transform:uppercase;">Job Digest</div>
                <div style="margin-top:10px;font-size:12px;letter-spacing:0.08em;text-transform:uppercase;opacity:0.72;">
                  {escape(datetime.now().strftime('%Y-%m-%d'))} | {len(jobs)} matches
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding-top:10px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">
                  {''.join(rows)}
                </table>
                {footer_link}
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def send_digest(jobs: list[dict[str, Any]], html_page_path: str) -> None:
    selected_jobs = _top_jobs(jobs)
    if not selected_jobs:
        log.info("Skipping email send because there are no jobs to email")
        return

    digest_path = Path(html_page_path)
    if not digest_path.is_absolute():
        digest_path = PROJECT_ROOT / digest_path

    if not digest_path.exists():
        log.warning("Digest HTML path does not exist yet: %s", digest_path)

    html_body = _render_email_html(selected_jobs, _digest_url())
    subject = f"Job Digest — {datetime.now().date().isoformat()} — {len(selected_jobs)} matches"
    _send_html_message(subject, html_body, interactive=False)
    log.info("Sent digest to %s", GMAIL_TO)


def send_html_email(subject: str, html_body: str) -> None:
    _send_html_message(subject, html_body, interactive=False)
