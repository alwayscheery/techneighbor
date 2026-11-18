import json
import uuid
from datetime import datetime, time, timedelta
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from booking.models import Booking, SessionSlot, ServiceCredential


class Command(BaseCommand):
    help = 'Seed only fictional appointments and public credential metadata in the isolated phone database.'

    def handle(self, *args, **options):
        if not getattr(settings, 'PUBLIC_PHONE_DEMO', False):
            raise CommandError('Use --settings=techneighbor.settings_phone to protect the local database.')
        for day_offset in range(1, 5):
            day = timezone.localdate() + timedelta(days=day_offset)
            for hour in (10, 11, 14):
                SessionSlot.objects.get_or_create(starts_at=timezone.make_aware(datetime.combine(day, time(hour))))
        proof = json.loads((settings.BASE_DIR / 'contracts' / 'sample-proof.json').read_text())
        public_id = uuid.UUID(hex=proof['credential_id'][2:][-32:])
        if not ServiceCredential.objects.filter(public_id=public_id).exists():
            slot, _ = SessionSlot.objects.get_or_create(starts_at=timezone.now()-timedelta(days=1))
            booking = Booking.objects.create(slot=slot, name='Fictional demo participant', topic='video', status='completed', is_sample=True)
            ServiceCredential.objects.create(booking=booking, public_id=public_id,
                volunteer_alias='Demo volunteer', volunteer_wallet=proof['volunteer_wallet'],
                issuer_wallet=proof['issuer_wallet'], contract_address=proof['contract_address'],
                chain_id=proof['chain_id'], status='issued', issue_tx=proof['issue_transaction'])
        self.stdout.write('Phone demo ready: synthetic bookings, public proof, and no coordinator accounts.')
