from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import SimpleTestCase, RequestFactory, override_settings
from .phone_demo import PhoneDemoMiddleware, AnonymousDemoMiddleware
from .integrations import write_private
from .voice import audio_for, VoiceError


class PhoneDemoAccessTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.handler = Mock(return_value=HttpResponse('public demo'))
        self.middleware = PhoneDemoMiddleware(self.handler)

    def test_private_and_unknown_routes_are_not_exposed(self):
        for path in ['/admin/', '/coordinator/', '/coordinator/integrations/',
                     '/coordinator/sign-in/', '/.private/arc.json', '/anything-else/']:
            for method in ['get', 'post']:
                with self.subTest(path=path, method=method):
                    response = self.middleware(getattr(self.factory, method)(path))
                    self.assertEqual(response.status_code, 404)
        self.handler.assert_not_called()

    def test_public_pages_and_booking_writes_are_allowed(self):
        for path in ['/', '/book/', '/credentials/f18e62ba-ad7f-4da4-8ee9-29cb31c6b0e5/']:
            self.assertEqual(self.middleware(self.factory.get(path)).status_code, 200)
        self.assertEqual(self.middleware(self.factory.post('/book/')).status_code, 200)
        self.assertEqual(self.middleware(self.factory.put('/book/')).status_code, 404)

    def test_revocation_is_blocked_even_with_an_existing_staff_cookie(self):
        path = '/credentials/f18e62ba-ad7f-4da4-8ee9-29cb31c6b0e5/revoke/'
        self.assertEqual(self.middleware(self.factory.post(path)).status_code, 404)

    def test_requests_are_always_anonymous(self):
        request = self.factory.get('/')
        request.user = Mock(is_staff=True)
        handler = Mock(return_value=HttpResponse())
        AnonymousDemoMiddleware(handler)(request)
        self.assertIsInstance(request.user, AnonymousUser)
        self.assertFalse(request.user.is_staff)

    def test_public_voice_never_makes_a_provider_request_on_cache_miss(self):
        with TemporaryDirectory() as folder, override_settings(BASE_DIR=Path(folder), PUBLIC_PHONE_DEMO=True):
            write_private('elevenlabs.json', {'api_key': 'not-a-real-key', 'voice_id': 'JBFqnCBsd6RMkjVDRZzb'})
            with patch('booking.voice.requests.post') as provider:
                with self.assertRaises(VoiceError):
                    audio_for('welcome')
                provider.assert_not_called()
