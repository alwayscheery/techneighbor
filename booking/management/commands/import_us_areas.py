import csv
from pathlib import Path
from django.core.management.base import BaseCommand
from django.db import transaction
from booking.models import NeighborArea


class Command(BaseCommand):
    help = 'Import bundled 2025 Census places for all 50 states and Washington, D.C.; preserve existing area links.'

    def handle(self, *args, **options):
        path = Path(__file__).resolve().parents[2] / 'data' / 'us_places_2025.csv'
        existing = list(NeighborArea.objects.all())
        slugs = {area.slug for area in existing}
        legacy = {area.name: area for area in existing if not area.slug.startswith('census-')}
        new, updated = [], []
        with path.open(newline='') as handle:
            for row in csv.DictReader(handle):
                slug = 'census-' + row['geoid']
                if slug in slugs:
                    continue
                area = legacy.get(row['name'])
                if area:
                    if not area.state:
                        area.state = row['state']; updated.append(area)
                    continue
                new.append(NeighborArea(slug=slug, state=row['state'], name=row['name'],
                    latitude=float(row['latitude']), longitude=float(row['longitude'])))
        with transaction.atomic():
            NeighborArea.objects.bulk_create(new, batch_size=150, ignore_conflicts=True)
            if updated:
                NeighborArea.objects.bulk_update(updated, ['state'], batch_size=150)
        self.stdout.write(f'U.S. area catalog ready: {NeighborArea.objects.count():,} areas; no resident data imported.')
