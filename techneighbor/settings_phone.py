"""Isolated, temporary phone demo. Never expose the coordinator app through it."""
import os
import secrets
from .settings import *

DEBUG = False
PUBLIC_PHONE_DEMO = True
phone_host = os.environ.get('TECHNEIGHBOR_PHONE_HOST', '')
ALLOWED_HOSTS = ['localhost', '127.0.0.1'] + ([phone_host] if phone_host else [])
CSRF_TRUSTED_ORIGINS = [f'https://{phone_host}'] if phone_host else []
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_NAME = 'techneighbor_phone_session'
CSRF_COOKIE_NAME = 'techneighbor_phone_csrf'
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SECURE_REFERRER_POLICY = 'same-origin'
MIDDLEWARE = ['booking.phone_demo.PhoneDemoMiddleware'] + MIDDLEWARE
MIDDLEWARE.insert(MIDDLEWARE.index('django.contrib.auth.middleware.AuthenticationMiddleware') + 1,
                  'booking.phone_demo.AnonymousDemoMiddleware')
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3',
                       'NAME': BASE_DIR / '.private' / 'phone-demo.sqlite3'}}
phone_secret_file = BASE_DIR / '.private' / 'phone-demo-secret'
phone_secret_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
if not phone_secret_file.exists():
    try:
        fd = os.open(phone_secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write(secrets.token_urlsafe(48))
    except FileExistsError:
        pass
SECRET_KEY = phone_secret_file.read_text().strip()
