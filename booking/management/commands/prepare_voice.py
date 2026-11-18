from django.core.management.base import BaseCommand, CommandError
from booking.voice import PROMPTS, VoiceError, audio_for


class Command(BaseCommand):
    help = 'Prepare cached ElevenLabs audio for fixed instructions and lessons only.'

    def add_arguments(self, parser):
        parser.add_argument('prompts', nargs='*')

    def handle(self, *args, **options):
        prompts = options['prompts'] or list(PROMPTS)
        for prompt in prompts:
            if prompt not in PROMPTS:
                raise CommandError('Unknown fixed guide step.')
            try:
                audio = audio_for(prompt)
            except VoiceError as exc:
                raise CommandError(f'{prompt}: {exc}') from exc
            self.stdout.write(f'{prompt}: {len(audio)} audio bytes ready')
