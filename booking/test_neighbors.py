from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlparse, parse_qs
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import HttpResponse
from django.test import TestCase, Client, RequestFactory, override_settings
from django.urls import reverse
from .models import NeighborArea, NeighborProfile, NeighborIntroduction
from .neighbor_forms import NeighborAreaForm
from .neighbor_views import google_search
from .phone_demo import PhoneDemoMiddleware
from .integrations import read_private


class NeighborTests(TestCase):
    def setUp(self):
        cache.clear()
        self.area = NeighborArea.objects.create(slug='maple-city', name='Maple City', latitude=34, longitude=-118)
        self.other_area = NeighborArea.objects.create(slug='other-city', name='Other City', latitude=35, longitude=-117)
        self.neighbor = NeighborProfile.objects.create(owner_token='someone-else', area=self.area, nickname='Example neighbor', interest='company', about='A fictional test profile.', status='approved')
        self.staff = get_user_model().objects.create_user('coordinator', is_staff=True)

    def create_own(self, client=None, approve=False):
        client = client or self.client
        response = client.post(reverse('neighbor_profile'), {'area': self.area.pk, 'nickname': 'Sample neighbor', 'interest': 'technology', 'about': 'PRIVATE PENDING INTRODUCTION', 'permission': 'on'})
        profile = NeighborProfile.objects.get(owner_token=client.session['community_owner'])
        if approve:
            profile.status = 'approved'
            profile.save()
        return profile

    def test_pending_profile_is_private_and_cannot_be_targeted(self):
        profile = self.create_own()
        self.assertNotContains(Client().get(reverse('neighbors')), profile.about)
        self.assertNotContains(Client().get(reverse('neighbor_profile')), profile.about)
        self.assertContains(self.client.get(reverse('neighbor_profile')), profile.about)
        self.assertEqual(Client().get(reverse('neighbor_introduce', args=[profile.pk])).status_code, 404)

    def test_consent_required_and_coordinator_approval_lists_profile(self):
        self.client.post(reverse('neighbor_profile'), {'area': self.area.pk, 'nickname': 'No consent', 'interest': 'company', 'about': 'Hello'})
        self.assertEqual(NeighborProfile.objects.count(), 1)
        profile = self.create_own()
        staff = Client()
        staff.force_login(self.staff)
        self.assertEqual(staff.post(reverse('neighbor_review'), {'action': 'approve', 'profile_id': profile.pk}).status_code, 302)
        self.assertContains(Client().get(reverse('neighbors')), profile.about)
        page = Client().get(reverse('neighbors'))
        self.assertNotContains(page, profile.owner_token)

    def test_edits_require_review_again_and_withdrawal_closes_requests(self):
        own = self.create_own(approve=True)
        intro = NeighborIntroduction.objects.create(requester=own, neighbor=self.neighbor, contact='private@example.test')
        self.create_own()
        own.refresh_from_db()
        self.assertEqual(own.status, 'pending')
        self.client.post(reverse('neighbor_profile'), {'action': 'withdraw'})
        own.refresh_from_db(); intro.refresh_from_db()
        self.assertEqual(own.status, 'hidden')
        self.assertEqual(intro.status, 'closed')
        self.assertNotContains(Client().get(reverse('neighbors')), own.about)

    def test_area_and_interest_filters_match_profiles_and_markers(self):
        other = NeighborProfile.objects.create(owner_token='other', area=self.other_area, nickname='Another neighbor', interest='walking', about='Another fictional profile.', status='approved')
        response = self.client.get(reverse('neighbors'), {'area': self.area.slug, 'interest': 'company'})
        self.assertContains(response, self.neighbor.nickname)
        self.assertNotContains(response, other.nickname)
        self.assertEqual(response.context['map_config']['points'], [{'lat': 34.0, 'lng': -118.0, 'label': self.area.name, 'count': 1, 'slug': self.area.slug}])
        self.assertContains(self.client.get(reverse('neighbors'), {'interest': 'photos'}), 'No approved profiles match')

    def test_introductions_require_approved_profile_and_refuse_sample_or_self(self):
        url = reverse('neighbor_introduce', args=[self.neighbor.pk])
        self.assertRedirects(self.client.get(url), reverse('neighbor_profile'))
        own = self.create_own()
        self.assertRedirects(self.client.get(url), reverse('neighbor_profile'))
        own.status = 'approved'; own.save()
        self.assertEqual(self.client.get(reverse('neighbor_introduce', args=[own.pk])).status_code, 400)
        self.neighbor.is_sample = True; self.neighbor.save()
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_introduction_is_private_deduplicated_and_not_auto_sent(self):
        own = self.create_own(approve=True)
        url = reverse('neighbor_introduce', args=[self.neighbor.pk])
        payload = {'contact': 'private@example.test', 'note': 'PRIVATE NOTE', 'permission': 'on'}
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.client.post(url, payload)
        self.assertEqual(NeighborIntroduction.objects.count(), 1)
        self.assertContains(self.client.get(url), 'Your request is with the coordinator.')
        page = Client().get(reverse('neighbors'))
        self.assertNotContains(page, payload['contact']); self.assertNotContains(page, payload['note'])
        staff = Client(); staff.force_login(self.staff)
        self.assertContains(staff.get(reverse('neighbor_review')), payload['contact'])
        intro = NeighborIntroduction.objects.get()
        staff.post(reverse('neighbor_review'), {'action': 'closed', 'introduction_id': intro.pk})
        intro.refresh_from_db(); self.assertEqual(intro.status, 'closed')

    def test_introduction_consent_and_daily_limit(self):
        own = self.create_own(approve=True)
        url = reverse('neighbor_introduce', args=[self.neighbor.pk])
        self.client.post(url, {'contact': 'private@example.test'})
        self.assertEqual(NeighborIntroduction.objects.count(), 0)
        for i in range(3):
            NeighborIntroduction.objects.create(requester=own, neighbor=self.neighbor, status='closed', contact='private@example.test')
        response = self.client.post(url, {'contact': 'private@example.test', 'permission': 'on'})
        self.assertContains(response, 'three introductions today')
        self.assertEqual(NeighborIntroduction.objects.count(), 3)

    def test_maps_urls_are_encoded_and_contain_no_personal_profile_data(self):
        url = google_search('Libraries in Maple City & District')
        self.assertEqual(urlparse(url).hostname, 'www.google.com')
        self.assertEqual(parse_qs(urlparse(url).query), {'api': ['1'], 'query': ['Libraries in Maple City & District']})
        response = self.client.get(reverse('neighbors'), {'area': self.area.slug})
        self.assertNotIn('nickname', response.context['map_config']['points'][0])
        self.assertNotContains(response, 'geolocation')

    def test_missing_maps_key_is_honest_and_does_not_load_google(self):
        with patch('booking.neighbor_views.maps_settings', return_value={'api_key': '', 'map_id': 'DEMO_MAP_ID'}):
            page = self.client.get(reverse('neighbors'))
        self.assertContains(page, 'Open this area in Google Maps')
        self.assertContains(page, 'Open Google Maps')
        self.assertNotContains(page, 'id="load-neighbor-map"')
        self.assertNotContains(page, '<script src="https://maps.googleapis.com')

    def test_maps_key_setup_is_staff_only_and_not_rerendered(self):
        with TemporaryDirectory() as folder, override_settings(BASE_DIR=Path(folder)):
            payload = {'api_key': 'test-browser-key-1234567890', 'map_id': '', 'restricted': 'on'}
            url = reverse('neighbor_maps_setup')
            self.assertEqual(self.client.post(url, payload).status_code, 302)
            self.assertEqual(read_private('maps.json'), {})
            self.client.force_login(self.staff)
            self.assertEqual(self.client.post(url, payload).status_code, 302)
            self.assertEqual(read_private('maps.json')['api_key'], payload['api_key'])
            self.assertNotContains(self.client.get(url), payload['api_key'])
            self.assertEqual(self.client.get(url).headers['Cache-Control'], 'private, no-store')

    def test_profiles_are_escaped_and_all_writes_require_csrf(self):
        self.neighbor.about = '<script>alert(1)</script>'; self.neighbor.save()
        self.assertContains(self.client.get(reverse('neighbors')), '&lt;script&gt;')
        self.assertNotContains(self.client.get(reverse('neighbors')), '<script>alert(1)')
        csrf = Client(enforce_csrf_checks=True)
        for url in [reverse('neighbor_profile'), reverse('neighbor_introduce', args=[self.neighbor.pk]), reverse('neighbor_review'), reverse('neighbor_maps_setup')]:
            self.assertEqual(csrf.post(url, {}).status_code, 403)
        self.assertEqual(Client().post(reverse('neighbor_review'), {'action': 'approve', 'profile_id': self.neighbor.pk}).status_code, 302)

    def test_phone_demo_allows_neighbor_routes_but_blocks_private_maps_settings(self):
        factory = RequestFactory(); middleware = PhoneDemoMiddleware(lambda request: HttpResponse())
        for url in ['/neighbors/', '/neighbors/profile/', reverse('neighbor_introduce', args=[self.neighbor.pk])]:
            self.assertEqual(middleware(factory.get(url)).status_code, 200)
        for url in ['/neighbors/profile/', reverse('neighbor_introduce', args=[self.neighbor.pk])]:
            self.assertEqual(middleware(factory.post(url)).status_code, 200)
        self.assertEqual(middleware(factory.post('/neighbors/')).status_code, 404)
        self.assertEqual(middleware(factory.get('/coordinator/neighbors/maps/')).status_code, 404)

    def test_coordinator_can_add_area_with_bounded_coordinates(self):
        self.client.force_login(self.staff)
        self.client.post(reverse('neighbor_review'), {'action': 'area', 'slug': 'new-city', 'name': 'New City', 'latitude': '10', 'longitude': '20'})
        self.assertTrue(NeighborArea.objects.filter(slug='new-city').exists())
        for bad in ['nan', 'inf', '100']:
            form = NeighborAreaForm({'slug': 'bad', 'name': 'Bad', 'latitude': bad, 'longitude': '20'})
            self.assertFalse(form.is_valid())


class PhoneNeighborModerationTests(TestCase):
    databases = {'default', 'phone_demo'}

    def test_phone_profiles_are_reviewed_in_their_own_database(self):
        area = NeighborArea.objects.using('phone_demo').create(slug='phone-area', name='Phone demo area', latitude=34, longitude=-118)
        profile = NeighborProfile.objects.using('phone_demo').create(area=area, owner_token='phone-owner', nickname='Phone example', interest='company', about='PHONE PENDING INTRODUCTION')
        staff = get_user_model().objects.create_user('coordinator', is_staff=True)
        self.client.force_login(staff)
        self.assertNotContains(self.client.get(reverse('neighbor_review')), profile.about)
        self.assertContains(self.client.get(reverse('neighbor_review'), {'source': 'phone'}), profile.about)
        self.client.post(reverse('neighbor_review'), {'source': 'phone', 'action': 'approve', 'profile_id': profile.pk})
        profile.refresh_from_db(using='phone_demo')
        self.assertEqual(profile.status, 'approved')
        self.assertFalse(NeighborProfile.objects.filter(pk=profile.pk).exists())
