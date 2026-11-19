import hashlib
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from booking.integrations import elevenlabs_settings
from booking.models import HostedGuideAudio
from booking.voice import PROMPTS


class Command(BaseCommand):
    help = 'Copy existing fixed ElevenLabs guide clips into the hosted database. Never calls ElevenLabs.'

    def add_arguments(self, parser):
        parser.add_argument('--directory', required=True)

    def handle(self, *args, **options):
        if not getattr(settings, 'HOSTED_APP', False):
            raise CommandError('Use settings_hosted and the hosted database for this import.')
        voice = elevenlabs_settings()['voice_id']
        count = 0
        for prompt, text in PROMPTS.items():
            key = hashlib.sha256((voice + '|eleven_multilingual_v2|' + text).encode()).hexdigest()
            path = Path(options['directory']) / (key + '.mp3')
            if path.exists():
                HostedGuideAudio.objects.update_or_create(cache_key=key, defaults={'prompt': prompt, 'audio_data': path.read_bytes()})
                count += 1
        self.stdout.write(f'Imported {count} fixed guide clips. No API keys or personal recordings were copied.')
