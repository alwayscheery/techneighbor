"""Public demo on Render + persistent PostgreSQL. No local data or issuer keys."""
import os
import re
import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from .settings import *

HOSTED_APP = True
DEBUG = False
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
if len(SECRET_KEY) < 50:
    raise ImproperlyConfigured('Set DJANGO_SECRET_KEY to a randomly generated value of at least 50 characters.')
url = os.environ.get('DATABASE_URL', '')
if not url.startswith(('postgres://', 'postgresql://')):
    raise ImproperlyConfigured('Hosted deployments require a persistent PostgreSQL DATABASE_URL.')
DATABASES = {'default': dj_database_url.parse(url, conn_max_age=0, ssl_require=True)}
hosts = [host.strip() for host in os.environ.get('TECHNEIGHBOR_HOSTS', '').split(',') if host.strip()]
render_host = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '')
if render_host:
    hosts.append(render_host)
if not hosts or any(not re.fullmatch(r'[A-Za-z0-9.-]+', host) for host in hosts):
    raise ImproperlyConfigured('Set the exact public hostname; wildcard hosts are not supported.')
ALLOWED_HOSTS = list(dict.fromkeys(hosts))
CSRF_TRUSTED_ORIGINS = ['https://' + host for host in ALLOWED_HOSTS]
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r'^healthz/$']
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_REFERRER_POLICY = 'same-origin'
MIDDLEWARE = list(MIDDLEWARE)
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
MIDDLEWARE.append('booking.hosted.HostedDemoMiddleware')
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.db.DatabaseCache', 'LOCATION': 'hosted_cache', 'TIMEOUT': 3600}}
VOICE_CACHE_ONLY = True
PHOTO_UPLOAD_TOTAL_LIMIT = 100
