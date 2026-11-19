import hashlib
import importlib.util
import os
import shutil
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.http import HttpResponse
from django.test import TestCase, RequestFactory, override_settings
from booking.hosted import HostedDemoMiddleware, health
from booking.models import HostedGuideAudio, ServiceCredential
from booking.voice import PROMPTS, VoiceError, audio_for

SOURCE = Path(settings.BASE_DIR)


class HostedDeploymentTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def load_config(self, **env):
        spec = importlib.util.spec_from_file_location('techneighbor._hosted_settings_test', SOURCE / 'techneighbor/settings_hosted.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, env, clear=True):
            spec.loader.exec_module(module)
        return module

    def test_settings_require_persistent_postgres_secret_and_exact_hosts(self):
        base = {'DJANGO_SECRET_KEY': 'hosting-test-secret-' * 5, 'DATABASE_URL': 'postgresql://test:test@localhost/test', 'RENDER_EXTERNAL_HOSTNAME': 'example.onrender.com'}
        config = self.load_config(**base)
        self.assertFalse(config.DEBUG)
        self.assertEqual(list(config.DATABASES), ['default'])
        self.assertEqual(config.DATABASES['default']['ENGINE'], 'django.db.backends.postgresql')
        self.assertEqual(config.DATABASES['default']['OPTIONS']['sslmode'], 'require')
        self.assertEqual(config.ALLOWED_HOSTS, ['example.onrender.com'])
        self.assertTrue(config.SESSION_COOKIE_SECURE)
        self.assertTrue(config.CSRF_COOKIE_SECURE)
        self.assertTrue(config.SECURE_SSL_REDIRECT)
        self.assertTrue(config.VOICE_CACHE_ONLY)
        for change in [{'DJANGO_SECRET_KEY': ''}, {'DATABASE_URL': 'sqlite:///db.sqlite3'}, {'RENDER_EXTERNAL_HOSTNAME': '*'}]:
            with self.assertRaises(ImproperlyConfigured):
                self.load_config(**(base | change))

    def test_hosted_blocks_issuer_keys_and_signing_routes_but_allows_moderation(self):
        middleware = HostedDemoMiddleware(lambda request: HttpResponse('allowed'))
        for path in ['/admin/', '/coordinator/integrations/', '/coordinator/neighbors/maps/', '/coordinator/booking/anything/credential/', '/credentials/anything/revoke/']:
            self.assertEqual(middleware(self.factory.post(path)).status_code, 404)
        for path in ['/coordinator/', '/coordinator/community/', '/coordinator/neighbors/', '/book/']:
            self.assertEqual(middleware(self.factory.get(path)).status_code, 200)

    def test_hosted_signin_is_throttled(self):
        middleware = HostedDemoMiddleware(lambda request: HttpResponse())
        for _ in range(20):
            self.assertEqual(middleware(self.factory.post('/coordinator/sign-in/')).status_code, 200)
        self.assertEqual(middleware(self.factory.post('/coordinator/sign-in/')).status_code, 429)

    def test_health_checks_database_and_returns_no_details_on_error(self):
        self.assertEqual(health(self.factory.get('/healthz/')).status_code, 200)
        with patch('booking.hosted.connection.cursor', side_effect=RuntimeError('PRIVATE CONNECTION STRING')):
            response = health(self.factory.get('/healthz/'))
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b'PRIVATE', response.content)

    def test_hosted_audio_survives_without_filesystem_cache_or_provider_key(self):
        key = hashlib.sha256(('JBFqnCBsd6RMkjVDRZzb|eleven_multilingual_v2|' + PROMPTS['community']).encode()).hexdigest()
        HostedGuideAudio.objects.create(cache_key=key, prompt='community', audio_data=b'ID3-cached-test')
        with TemporaryDirectory() as folder, override_settings(BASE_DIR=Path(folder), HOSTED_APP=True, VOICE_CACHE_ONLY=True):
            with patch('booking.voice.requests.post') as provider:
                self.assertEqual(audio_for('community'), b'ID3-cached-test')
                with self.assertRaises(VoiceError):
                    audio_for('welcome')
                provider.assert_not_called()

    def test_hosted_seed_is_repeatable_and_does_not_generate_or_reset_passwords(self):
        with TemporaryDirectory() as folder:
            root = Path(folder); (root / 'contracts').mkdir()
            shutil.copyfile(SOURCE / 'contracts/sample-proof.json', root / 'contracts/sample-proof.json')
            with override_settings(BASE_DIR=root, HOSTED_APP=True), patch.dict(os.environ, {'DJANGO_SUPERUSER_PASSWORD': 'Test-only-password-9tZkwP!', 'DJANGO_SUPERUSER_USERNAME': 'coordinator'}):
                with patch('booking.management.commands.setup_hosted.call_command'):
                    call_command('setup_hosted', stdout=StringIO())
                    user = get_user_model().objects.get(username='coordinator')
                    password_hash = user.password
                    call_command('setup_hosted', stdout=StringIO())
            user.refresh_from_db()
            self.assertTrue(user.is_staff)
            self.assertFalse(user.is_superuser)
            self.assertEqual(user.password, password_hash)
            self.assertEqual(ServiceCredential.objects.count(), 1)
            self.assertFalse((root / 'LOCAL_ACCESS.txt').exists())
