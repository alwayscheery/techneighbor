"""Server-side care encryption. The service can decrypt; this is not E2E encryption."""
import base64
import json
from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import HKDF
from Crypto.Random import get_random_bytes
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder


class CareDataError(Exception):
    pass


def key_for(circle_id, secret):
    return HKDF(secret.encode(), 32, salt=str(circle_id).encode(), hashmod=SHA256,
                context=b'TechNeighbor/private-care/v1')


def seal(circle_id, context, fields):
    cipher = AES.new(key_for(circle_id, settings.SECRET_KEY), AES.MODE_GCM, nonce=get_random_bytes(12))
    cipher.update(('care:v1:' + context).encode())
    data = json.dumps(fields, cls=DjangoJSONEncoder, separators=(',', ':')).encode()
    ciphertext, tag = cipher.encrypt_and_digest(data)
    return 'v1.' + base64.urlsafe_b64encode(cipher.nonce + tag + ciphertext).decode()


def unseal(circle_id, context, token):
    try:
        if not token.startswith('v1.') or len(token) > 40000:
            raise ValueError
        raw = base64.b64decode(token[3:].encode(), altchars=b'-_', validate=True)
        if len(raw) < 30:
            raise ValueError
        for secret in [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS]:
            try:
                cipher = AES.new(key_for(circle_id, secret), AES.MODE_GCM, nonce=raw[:12])
                cipher.update(('care:v1:' + context).encode())
                fields = json.loads(cipher.decrypt_and_verify(raw[28:], raw[12:28]))
                if isinstance(fields, dict):
                    return fields
            except (ValueError, TypeError, UnicodeError):
                continue
    except (ValueError, TypeError, UnicodeError):
        pass
    raise CareDataError('Saved care information cannot be read right now.') from None
