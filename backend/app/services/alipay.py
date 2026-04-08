import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def _format_public_key(raw_key: str) -> str:
    stripped = raw_key.strip().replace('\\n', '\n')
    if 'BEGIN PUBLIC KEY' in stripped:
        return stripped
    compact = ''.join(stripped.split())
    return f'-----BEGIN PUBLIC KEY-----\n{compact}\n-----END PUBLIC KEY-----'


def build_alipay_sign_content(params: dict) -> str:
    pairs = []
    for key, value in params.items():
        if key in {'sign', 'sign_type'} or value in {None, ''}:
            continue
        pairs.append((key, str(value)))
    return '&'.join(f'{key}={value}' for key, value in sorted(pairs))


def verify_alipay_rsa2_signature(params: dict, alipay_public_key: str) -> bool:
    sign = params.get('sign')
    if not sign:
        return False

    try:
        public_key = serialization.load_pem_public_key(_format_public_key(alipay_public_key).encode('utf-8'))
        public_key.verify(
            base64.b64decode(str(sign)),
            build_alipay_sign_content(params).encode('utf-8'),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except (ValueError, TypeError, InvalidSignature):
        return False
