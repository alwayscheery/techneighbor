import json
import os
import uuid
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from booking.models import Booking, ServiceCredential, SessionSlot


class Command(BaseCommand):
    help = 'Initialize a hosted demo with fictional records and an environment-configured coordinator.'

    def handle(self, *args, **options):
        if not getattr(settings, 'HOSTED_APP', False):
            raise CommandError('Use settings_hosted for this command.')
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', '')
        username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'coordinator')
        User = get_user_model()
        user = User.objects.filter(username=username).first()
        if not user:
            if len(password) < 16:
                raise CommandError('Configure a private coordinator password of at least 16 characters.')
            validate_password(password)
            User.objects.create_user(username=username, password=password, is_staff=True, is_superuser=False)
        call_command('setup_demo', no_coordinator=True, stdout=self.stdout)
        call_command('setup_community', stdout=self.stdout)
        call_command('setup_neighbors', stdout=self.stdout)
        proof = json.loads((settings.BASE_DIR / 'contracts' / 'sample-proof.json').read_text())
        public_id = uuid.UUID(hex=proof['credential_id'][2:][-32:])
        if not ServiceCredential.objects.filter(public_id=public_id).exists():
            slot, _ = SessionSlot.objects.get_or_create(starts_at=timezone.now()-timedelta(days=2))
            booking = Booking.objects.create(slot=slot, name='Fictional demo participant', topic='video', status='completed', is_sample=True)
            ServiceCredential.objects.create(booking=booking, public_id=public_id,
                volunteer_alias='Demo volunteer', volunteer_wallet=proof['volunteer_wallet'],
                issuer_wallet=proof['issuer_wallet'], contract_address=proof['contract_address'],
                chain_id=proof['chain_id'], status='issued', issue_tx=proof['issue_transaction'])
        self.stdout.write('Hosted demo initialized. Private local records and signing keys were not imported.')
