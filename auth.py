from __future__ import annotations

import os

from fastapi import HTTPException, Request

from store import Store

EMAIL_HEADER = os.getenv("AUTH_EMAIL_HEADER", "Remote-Email")
NAME_HEADER = os.getenv("AUTH_NAME_HEADER", "Remote-Name")
USER_HEADER = os.getenv("AUTH_USER_HEADER", "Remote-User")


def _header(request: Request, name: str) -> str | None:
    value = request.headers.get(name)
    if value is None:
        return None
    # Starlette purkaa headerit latin-1:nä, mutta Authelia/Caddy lähettävät
    # nimet UTF-8-tavuina. Palautetaan tavut ja tulkitaan UTF-8:na, jotta
    # ä/ö/å eivät näy mojibakena.
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def get_current_user(request: Request) -> dict:
    email = _header(request, EMAIL_HEADER)
    if not email:
        raise HTTPException(status_code=401, detail="Missing auth header")
    display_name = (
        _header(request, NAME_HEADER)
        or _header(request, USER_HEADER)
        or email.split("@")[0]
    )
    store: Store = request.app.state.store
    return store.get_or_create_user(email, display_name)
