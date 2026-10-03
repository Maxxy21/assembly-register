import hashlib
import secrets


def new_qr_token() -> str:
    # 128 bits: unguessable, and still short enough for a dense-free QR code.
    return secrets.token_urlsafe(16)


def new_admin_token() -> str:
    return secrets.token_urlsafe(32)


def hash_admin_token(token: str) -> str:
    """Admin tokens are high-entropy random strings, so a plain SHA-256 is
    enough to keep them out of the database without needing a slow KDF."""
    return hashlib.sha256(token.encode()).hexdigest()
