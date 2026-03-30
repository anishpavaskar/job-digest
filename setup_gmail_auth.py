"""One-time Gmail OAuth setup."""

from __future__ import annotations

from emailer import authorize_gmail
from logging_config import get_logger

log = get_logger("setup_gmail_auth")


def main() -> None:
    token_path = authorize_gmail()
    log.info("Gmail token saved to %s", token_path)


if __name__ == "__main__":
    main()
