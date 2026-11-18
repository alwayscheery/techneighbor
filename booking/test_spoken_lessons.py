from unittest.mock import Mock, patch
from pathlib import Path
from tempfile import TemporaryDirectory
from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse
from django.http import HttpResponse
from booking.phone_demo import PhoneDemoMiddleware
from booking.voice import PROMPTS
from booking.integrations import write_private


class SpokenLessonTests(TestCase):
    def test_all_lessons_have_transcripts_and_accessible_controls(self):
        for slug, key in [('video-calls', 'lesson_calls'), ('sharing-photos', 'lesson_photos'), ('staying-safe', 'lesson_safety')]:
            page = self.client.get(reverse('lesson', args=[slug]))
            self.assertContains(page, 'Listen or replay')
            self.assertContains(page, PROMPTS[key])
            self.assertContains(page, 'Slower')
            self.assertContains(page, 'Nothing plays automatically.')
            self.assertContains(page, 'csrfmiddlewaretoken')
        self.assertEqual(self.client.get('/learn/not-a-lesson/').status_code, 404)

    def test_community_help_is_available_without_a_voice_connection(self):
        for name in ['community_hub', 'community_albums', 'community_upload']:
            page = self.client.get(reverse(name))
            self.assertContains(page, 'Listen or replay')
            self.assertContains(page, 'Your photos, captions, names, and form entries are never sent.')
            self.assertEqual(page.content.count(b'id="guide-player"'), 1)

    def test_public_demo_can_read_lessons_but_not_write_to_them(self):
        factory = RequestFactory()
        middleware = PhoneDemoMiddleware(lambda request: HttpResponse())
        for path in ['/learn/', '/learn/video-calls/']:
            self.assertEqual(middleware(factory.get(path)).status_code, 200)
            self.assertEqual(middleware(factory.post(path)).status_code, 404)

    def test_new_guides_send_only_fixed_text_and_reuse_cached_audio(self):
        with TemporaryDirectory() as folder, override_settings(BASE_DIR=Path(folder)):
            write_private('elevenlabs.json', {'api_key': 'fake-key', 'voice_id': 'JBFqnCBsd6RMkjVDRZzb'})
            response = Mock(status_code=200, headers={'Content-Type': 'audio/mpeg'}, content=b'ID3-demo')
            with patch('booking.voice.requests.post', return_value=response) as provider:
                for key in ['community', 'joining', 'albums', 'upload', 'lesson_calls', 'lesson_photos', 'lesson_safety']:
                    payload = {'prompt': key, 'caption': 'PRIVATE CAPTION', 'name': 'PRIVATE NAME'}
                    self.assertEqual(self.client.post(reverse('voice_audio'), payload).status_code, 200)
                    self.assertEqual(provider.call_args.kwargs['json']['text'], PROMPTS[key])
                    self.assertEqual(self.client.post(reverse('voice_audio'), payload).status_code, 200)
                self.assertEqual(provider.call_count, 7)
