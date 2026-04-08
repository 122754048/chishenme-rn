import hashlib
from datetime import datetime, timedelta
from jose import jwt, JWTError

from .config import settings


def hash_password(raw: str) -> str:
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def verify_password(raw: str, hashed: str) -> bool:
    return hash_password(raw) == hashed


def create_access_token(user_id: str) -> str:
    expire_at = datetime.utcnow() + timedelta(minutes=settings.jwt_exp_minutes)
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
