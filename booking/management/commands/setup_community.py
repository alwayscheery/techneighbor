from datetime import datetime, time, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from booking.models import CommunityPost, PhotoAlbum


class Command(BaseCommand):
    help = 'Seed clearly fictional community activities and empty shared albums. Safe to repeat.'

    def handle(self, *args, **options):
        tomorrow = timezone.localdate() + timedelta(days=1)
        events = [
            ('coffee-and-conversation', 'Coffee & a good conversation', 0, 10, 'Pull up a chair for a relaxed chat at the community lounge. Come on your own or bring a friend. This is a fictional demo activity.'),
            ('phone-help-circle', 'Bring your phone, bring your questions', 2, 14, 'A patient, friendly session for practicing the everyday things you want to do with your phone. Bring a charged device. This is a fictional demo activity.'),
            ('photos-and-stories', 'Photos, stories & a cup of tea', 4, 11, 'Bring a favorite photograph and the story behind it. Sharing a memory is optional; listening is welcome too. This is a fictional demo activity.'),
        ]
        for slug, title, offset, hour, body in events:
            starts = timezone.make_aware(datetime.combine(tomorrow + timedelta(days=offset), time(hour)))
            CommunityPost.objects.get_or_create(slug=slug, defaults={'kind': 'event', 'title': title,
                'body': body, 'starts_at': starts, 'is_sample': True, 'capacity': 12})
        CommunityPost.objects.get_or_create(slug='welcome-to-your-community', defaults={
            'kind': 'notice', 'title': 'There is a place for you here.', 'is_sample': True,
            'body': 'Find a friendly activity, share a little of your day, or enjoy a moment someone else has shared. The center and activities in this prototype are fictional. Please use sample details while exploring.'})
        for slug, title, description, color in [
            ('community-moments', 'Community moments', 'The small things that bring us together: shared activities, friendly gatherings, and time well spent.', 'lavender'),
            ('everyday-joys', 'Everyday joys', 'A garden in bloom, a favorite recipe, or something that made you smile today.', 'green'),
            ('memories-and-stories', 'Memories & stories', 'A favorite memory and the story you would like to tell.', 'peach'),
        ]:
            PhotoAlbum.objects.get_or_create(slug=slug, defaults={'title': title, 'description': description, 'color': color})
        self.stdout.write('Fictional activities and empty shared albums are ready.')
