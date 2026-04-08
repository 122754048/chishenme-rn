import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta
from jose import jwt, JWTError

from .config import settings


def hash_password(raw: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac('sha256', raw.encode('utf-8'), salt, 260_000)
    return f'pbkdf2_sha256$260000${salt.hex()}${digest.hex()}'


def verify_password(raw: str, hashed: str) -> bool:
    parts = hashed.split('$')
    if len(parts) == 4 and parts[0] == 'pbkdf2_sha256':
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected = bytes.fromhex(parts[3])
        actual = hashlib.pbkdf2_hmac('sha256', raw.encode('utf-8'), salt, iterations)
        return hmac.compare_digest(actual, expected)

    legacy_digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    return hmac.compare_digest(legacy_digest, hashed)


def create_access_token(user_id: str) -> str:
    expire_at = datetime.now(UTC) + timedelta(minutes=settings.jwt_exp_minutes)
    return jwt.encode({'sub': user_id, 'exp': expire_at}, settings.jwt_secret, algorithm=settings.jwt_algo)


def decode_access_token(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algo])
        sub = payload.get('sub')
        if not sub:
            raise ValueError('token subject missing')
        return str(sub)
    except JWTError as exc:
        raise ValueError('invalid token') from exc
