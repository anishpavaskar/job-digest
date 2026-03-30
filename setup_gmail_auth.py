"""One-time Gmail OAuth setup."""

from __future__ import annotations

from emailer import authorize_gmail


def main() -> None:
    token_path = authorize_gmail()
    print(f"Gmail token saved to {token_path}")


if __name__ == "__main__":
    main()
