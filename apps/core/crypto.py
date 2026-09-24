"""Symmetric encryption for secrets stored in the database (e.g. SMTP passwords).

The key comes from CREDENTIALS_KEY (a Fernet key) when set; otherwise it is derived
from SECRET_KEY. Either way, changing the key makes stored secrets unreadable and
they must be re-entered on the dashboard.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet():
    key = settings.CREDENTIALS_KEY
    if not key:
        digest = hashlib.sha256(b"wikischolar-credentials:" + settings.SECRET_KEY.encode()).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt(plain):
    return _fernet().encrypt(plain.encode()).decode() if plain else ""


def decrypt(token):
    """Returns "" when the token is empty or was encrypted with a different key."""
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return ""
