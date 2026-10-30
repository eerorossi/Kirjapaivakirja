def auth(email: str, name: str | None = None) -> list[tuple[bytes, bytes]]:
    """Authelian headerit. Nimi lähetetään UTF-8-tavuina kuten oikeasti."""
    headers = [(b"remote-email", email.encode())]
    if name:
        headers.append((b"remote-name", name.encode("utf-8")))
    return headers
