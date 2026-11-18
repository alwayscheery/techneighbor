from datetime import timedelta
from io import BytesIO
from unittest.mock import patch
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from .community_forms import PhotoUploadForm, MAX_UPLOAD
from .models import CommunityPost, CommunityAttendance, CommunityPhoto, PhotoAlbum, PhotoReport


def image_file():
    image = Image.new('RGB', (120, 80), (106, 123, 84))
    exif = Image.Exif()
    exif[0x010E] = 'PRIVATE EMBEDDED METADATA'
    output = BytesIO()
    image.save(output, format='JPEG', exif=exif)
    return SimpleUploadedFile('photo.jpg', output.getvalue(), content_type='image/jpeg')


@override_settings(ALLOWED_HOSTS=['testserver'])
class CommunityFeatureTests(TestCase):
    def setUp(self):
        self.album = PhotoAlbum.objects.create(slug='shared-moments', title='Shared moments', description='A shared community album.')
        self.event = CommunityPost.objects.create(slug='coffee', title='Coffee together', body='A fictional activity.', kind='event',
            starts_at=timezone.now()+timedelta(days=2), capacity=1)
        self.staff = get_user_model().objects.create_user('coordinator', is_staff=True)

    def upload(self, client=None, **overrides):
        payload = {'album': self.album.pk, 'image': image_file(), 'title': 'A little moment',
            'caption': 'A sample caption.', 'image_description': 'A green image for upload testing.',
            'uploader_name': 'Sample neighbor', 'permission': 'on'}
        payload.update(overrides)
        return (client or self.client).post(reverse('community_upload'), payload)

    def test_upload_is_pending_and_only_its_owner_can_see_it(self):
        response = self.upload()
        photo = CommunityPhoto.objects.get()
        self.assertEqual(photo.status, 'pending')
        self.assertRedirects(response, reverse('community_photo', args=[photo.pk]))
        self.assertContains(self.client.get(response.url), 'Awaiting coordinator approval')
        other = Client()
        self.assertEqual(other.get(response.url).status_code, 404)
        self.assertEqual(other.get(reverse('community_photo_image', args=[photo.pk])).status_code, 404)
        self.assertNotContains(other.get(reverse('community_album', args=[self.album.slug])), photo.title)

    def test_upload_is_reencoded_without_embedded_metadata(self):
        self.upload()
        photo = CommunityPhoto.objects.get()
        converted = Image.open(BytesIO(bytes(photo.image_data)))
        self.assertEqual(converted.format, 'JPEG')
        self.assertEqual(dict(converted.getexif()), {})
        self.assertNotIn(b'PRIVATE EMBEDDED METADATA', bytes(photo.image_data))
        self.assertEqual((photo.width, photo.height), (120, 80))

    def test_phone_multipicture_jpeg_is_accepted_and_flattened(self):
        output = BytesIO()
        Image.new('RGB', (120, 80), (100, 120, 80)).save(
            output, format='MPO', save_all=True,
            append_images=[Image.new('RGB', (120, 80), (20, 30, 40))])
        original = output.getvalue()
        self.assertEqual(Image.open(BytesIO(original)).format, 'MPO')
        response = self.upload(image=SimpleUploadedFile('phone.JPG', original, content_type='image/jpeg'))
        self.assertEqual(response.status_code, 302)
        photo = CommunityPhoto.objects.get()
        normalized = Image.open(BytesIO(bytes(photo.image_data)))
        self.assertEqual(normalized.format, 'JPEG')
        self.assertEqual(getattr(normalized, 'n_frames', 1), 1)
        self.assertEqual(normalized.size, (120, 80))
        self.assertEqual(photo.status, 'pending')

    def test_renamed_non_jpeg_has_an_accurate_format_error(self):
        output = BytesIO()
        Image.new('RGB', (30, 20)).save(output, format='GIF')
        response = self.upload(image=SimpleUploadedFile('renamed.jpg', output.getvalue(), content_type='image/jpeg'))
        self.assertContains(response, 'This file contains GIF data')
        self.assertEqual(CommunityPhoto.objects.count(), 0)

    def test_coordinator_approval_makes_photo_visible_to_others(self):
        self.upload()
        photo = CommunityPhoto.objects.get()
        staff = Client()
        staff.force_login(self.staff)
        response = staff.post(reverse('community_moderation'), {'source': 'local', 'action': 'approve', 'photo_id': str(photo.pk)})
        self.assertEqual(response.status_code, 302)
        photo.refresh_from_db()
        self.assertEqual(photo.status, 'approved')
        outsider = Client()
        page = outsider.get(reverse('community_album', args=[self.album.slug]))
        self.assertContains(page, photo.title)
        self.assertContains(page, photo.image_description)
        self.assertEqual(outsider.get(reverse('community_photo_image', args=[photo.pk])).status_code, 200)

    def test_only_staff_can_moderate(self):
        self.upload()
        photo = CommunityPhoto.objects.get()
        url = reverse('community_moderation')
        self.assertEqual(Client().post(url, {'action': 'approve', 'photo_id': photo.pk}).status_code, 302)
        ordinary = get_user_model().objects.create_user('ordinary')
        self.client.force_login(ordinary)
        self.assertEqual(self.client.post(url, {'action': 'approve', 'photo_id': photo.pk}).status_code, 302)
        photo.refresh_from_db()
        self.assertEqual(photo.status, 'pending')

    def test_owner_can_remove_photo_and_another_visitor_cannot(self):
        self.upload()
        photo = CommunityPhoto.objects.get()
        photo.status = 'approved'
        photo.save()
        url = reverse('community_photo_action', args=[photo.pk])
        self.assertEqual(Client().post(url, {'action': 'remove'}).status_code, 400)
        self.assertEqual(self.client.post(url, {'action': 'remove'}).status_code, 302)
        photo.refresh_from_db()
        self.assertEqual(photo.status, 'hidden')
        self.assertEqual(Client().get(reverse('community_photo_image', args=[photo.pk])).status_code, 404)

    def test_permission_and_accessible_description_are_required(self):
        response = self.upload(permission='', image_description='')
        self.assertEqual(response.status_code, 200)
        self.assertIn('permission', response.context['form'].errors)
        self.assertIn('image_description', response.context['form'].errors)
        self.assertEqual(CommunityPhoto.objects.count(), 0)

    def test_fake_image_and_oversized_upload_are_rejected(self):
        response = self.upload(image=SimpleUploadedFile('fake.jpg', b'<svg onload="alert(1)"></svg>', content_type='image/jpeg'))
        self.assertIn('image', response.context['form'].errors)
        form = PhotoUploadForm()
        form.cleaned_data = {'image': SimpleUploadedFile('large.jpg', b'x'*(MAX_UPLOAD+1), content_type='image/jpeg')}
        with self.assertRaisesMessage(Exception, 'smaller than 8 MB'):
            form.clean_image()
        self.assertEqual(CommunityPhoto.objects.count(), 0)

    def test_photo_captions_are_escaped(self):
        self.upload(caption='<script>alert("unsafe")</script>')
        photo = CommunityPhoto.objects.get()
        page = self.client.get(reverse('community_photo', args=[photo.pk]))
        self.assertNotContains(page, '<script>alert(')
        self.assertContains(page, '&lt;script&gt;')

    def test_upload_and_moderation_require_csrf(self):
        csrf = Client(enforce_csrf_checks=True)
        self.assertEqual(csrf.post(reverse('community_upload'), {}).status_code, 403)
        csrf.force_login(self.staff)
        self.assertEqual(csrf.post(reverse('community_moderation'), {}).status_code, 403)

    def test_reports_are_deduplicated_and_can_be_resolved_by_removing(self):
        self.upload()
        photo = CommunityPhoto.objects.get()
        photo.status = 'approved'
        photo.save()
        visitor = Client()
        for _ in range(2):
            visitor.post(reverse('community_photo_action', args=[photo.pk]), {'action': 'report', 'reason': 'privacy'})
        self.assertEqual(PhotoReport.objects.count(), 1)
        staff = Client()
        staff.force_login(self.staff)
        staff.post(reverse('community_moderation'), {'source': 'local', 'action': 'hide', 'photo_id': photo.pk})
        self.assertEqual(PhotoReport.objects.filter(resolved=False).count(), 0)

    def test_rsvp_is_private_idempotent_and_cannot_exceed_capacity(self):
        url = reverse('community_attendance', args=[self.event.slug])
        self.client.post(url, {'action': 'join', 'display_name': 'PRIVATE ATTENDEE'})
        self.client.post(url, {'action': 'join', 'display_name': 'PRIVATE ATTENDEE'})
        other = Client()
        other.post(url, {'action': 'join', 'display_name': 'Another visitor'})
        self.event.refresh_from_db()
        self.assertEqual(self.event.going_count, 1)
        self.assertEqual(CommunityAttendance.objects.count(), 1)
        self.assertNotContains(other.get(reverse('community_event', args=[self.event.slug])), 'PRIVATE ATTENDEE')
        self.client.post(url, {'action': 'leave'})
        self.event.refresh_from_db()
        self.assertEqual(self.event.going_count, 0)
        other.post(url, {'action': 'join', 'display_name': 'Another visitor'})
        self.assertEqual(CommunityAttendance.objects.get().display_name, 'Another visitor')

    def test_past_activity_cannot_be_joined(self):
        self.event.starts_at = timezone.now()-timedelta(hours=1)
        self.event.save()
        self.client.post(reverse('community_attendance', args=[self.event.slug]), {'action': 'join', 'display_name': 'Sample'})
        self.assertEqual(CommunityAttendance.objects.count(), 0)

    def test_coordinator_can_publish_an_event(self):
        self.client.force_login(self.staff)
        when = timezone.localtime(timezone.now()+timedelta(days=3)).strftime('%Y-%m-%dT%H:%M')
        response = self.client.post(reverse('community_moderation'), {'action': 'publish', 'source': 'local',
            'kind': 'event', 'title': 'A new activity', 'body': 'Come along.', 'starts_at': when,
            'location': 'Demo community center', 'capacity': 8})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(CommunityPost.objects.filter(title='A new activity').count(), 1)


@override_settings(ALLOWED_HOSTS=['testserver'])
class PhonePhotoModerationTests(TestCase):
    databases = {'default', 'phone_demo'}

    def test_local_coordinator_can_review_phone_photos_without_copying_private_data(self):
        album = PhotoAlbum.objects.using('phone_demo').create(slug='phone-album', title='Phone album', description='Phone only')
        photo = CommunityPhoto.objects.using('phone_demo').create(album=album, title='Phone image', image_description='Test image',
            uploader_name='Sample', owner_token='a'*64, image_data=b'normalized-image', width=10, height=10)
        self.assertEqual(CommunityPhoto.objects.using('default').count(), 0)
        staff = get_user_model().objects.create_user('local-coordinator', is_staff=True)
        self.client.force_login(staff)
        page = self.client.get(reverse('community_moderation'), {'source': 'phone'})
        self.assertContains(page, 'Phone image')
        image = self.client.get(reverse('community_moderation_image', args=[photo.pk]), {'source': 'phone'})
        self.assertEqual(image.status_code, 200)
        response = self.client.post(reverse('community_moderation'), {'source': 'phone', 'action': 'approve', 'photo_id': photo.pk})
        self.assertEqual(response.status_code, 302)
        photo.refresh_from_db(using='phone_demo')
        self.assertEqual(photo.status, 'approved')
        self.assertEqual(CommunityPhoto.objects.using('default').count(), 0)
