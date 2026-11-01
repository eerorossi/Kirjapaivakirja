#!/usr/bin/env python3
"""Lähetä testiviesti samoilla MAIL_*-asetuksilla kuin sovellus (releen toiminnan tarkistus).

    docker compose exec -T kirjapaivakirja python scripts/send_test_mail.py oma@osoite.fi
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from notifier import MailConfig, SmtpMailer  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2 or "@" not in argv[1]:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        config = MailConfig.from_env()
    except ValueError as exc:
        print(f"Virhe asetuksissa: {exc}", file=sys.stderr)
        return 1
    if config is None:
        print("MAIL_HOST ei ole asetettu: sähköposti ei ole käytössä.", file=sys.stderr)
        return 1
    try:
        SmtpMailer(config).send(argv[1], "Kirjapäiväkirja: testiviesti", "Jos luet tämän, sähköpostin lähetys toimii.\n")
    except Exception as exc:  # noqa: BLE001
        print(f"Lähetys epäonnistui ({config.host}:{config.port}): {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"Testiviesti lähetetty releeseen {config.host}:{config.port} -> {argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
