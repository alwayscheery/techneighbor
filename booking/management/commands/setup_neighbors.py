from django.core.management.base import BaseCommand
from booking.models import NeighborArea, NeighborProfile


class Command(BaseCommand):
    help = 'Seed example California areas and clearly fictional neighbor profiles. Never overwrites real profiles.'

    def handle(self, *args, **options):
        areas = [
            ('ontario-ca', 'Ontario, California', 34.06, -117.65),
            ('upland-ca', 'Upland, California', 34.10, -117.65),
            ('los-angeles-ca', 'Los Angeles, California', 34.05, -118.24),
        ]
        samples = [
            ('Example Maya', 'company', 'A fictional neighbor who enjoys a friendly conversation over coffee.'),
            ('Example Sam', 'technology', 'A fictional neighbor learning video calls, one small step at a time.'),
            ('Example Jo', 'walking', 'A fictional neighbor who enjoys gentle walks in a public park.'),
            ('Example Alex', 'photos', 'A fictional neighbor who likes sharing stories behind old photographs.'),
        ]
        saved = []
        for slug, name, lat, lng in areas:
            area, _ = NeighborArea.objects.get_or_create(slug=slug, defaults={'name': name, 'latitude': lat, 'longitude': lng})
            saved.append(area)
        for n, (nickname, interest, about) in enumerate(samples):
            NeighborProfile.objects.get_or_create(owner_token=f'fictional-neighbor-{n}', defaults={
                'nickname': nickname, 'interest': interest, 'about': about, 'area': saved[n % len(saved)], 'status': 'approved', 'is_sample': True})
        self.stdout.write('Example areas and fictional profiles ready. No real neighbors or contacts have been added.')
