import os
import secrets
from datetime import datetime, timedelta, time
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone
from booking.models import Booking, SessionSlot

class Command(BaseCommand):
    help = 'Create fictional local demo sessions and a coordinator account; safe to repeat.'

    def handle(self, *args, **options):
        tomorrow = timezone.localdate() + timedelta(days=1)
        for day_offset in range(5):
            day = tomorrow + timedelta(days=day_offset)
            for hour, minute in [(10, 0), (11, 0), (14, 0)]:
                starts = timezone.make_aware(datetime.combine(day, time(hour, minute)))
                SessionSlot.objects.get_or_create(starts_at=starts)
        # Sample rows are explicitly marked and never contact a real person.
        if not Booking.objects.filter(is_sample=True).exists():
            first_slot = SessionSlot.objects.filter(starts_at__gt=timezone.now()).order_by('starts_at').first()
            if first_slot and not first_slot.bookings.exclude(status='cancelled').exists():
                Booking.objects.create(slot=first_slot, name='Evelyn (sample)', topic='video', is_sample=True)
            past_time = timezone.make_aware(datetime.combine(tomorrow - timedelta(days=2), time(14, 0)))
            past, _ = SessionSlot.objects.get_or_create(starts_at=past_time)
            Booking.objects.get_or_create(slot=past, defaults={
                'name': 'George (sample)', 'topic': 'photos', 'is_sample': True,
                'status': 'completed', 'completed_at': timezone.now(),
            })
        User = get_user_model()
        if not User.objects.filter(username='coordinator').exists():
            password = secrets.token_urlsafe(18)
            User.objects.create_user('coordinator', password=password, is_staff=True, is_superuser=True)
            path = Path(settings.BASE_DIR) / 'LOCAL_ACCESS.txt'
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write('TechNeighbor — local prototype access\n\n')
                f.write('Open: http://127.0.0.1:8000/coordinator/\n')
                f.write('Username: coordinator\nPassword: ' + password + '\n\n')
                f.write('For your local demo only. Keep this file private.\n')
            self.stdout.write('Created coordinator. Sign-in details are in LOCAL_ACCESS.txt (keep private).')
        self.stdout.write(self.style.SUCCESS('Demo sessions are ready. All people and the venue are fictional.'))
