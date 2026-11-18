from io import StringIO
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from .area_catalog import STATES
from .models import NeighborArea, NeighborProfile
from .neighbor_forms import NeighborProfileForm


class NationalAreaCatalogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.legacy = NeighborArea.objects.create(slug='ontario-ca', name='Ontario, California', latitude=34.06, longitude=-117.65)
        cls.profile = NeighborProfile.objects.create(owner_token='existing-resident', area=cls.legacy, nickname='Existing fictional profile', interest='company', about='A test profile.', status='approved')
        call_command('import_us_areas', stdout=StringIO())

    def test_all_fifty_states_and_dc_are_available_and_import_is_repeatable(self):
        self.assertEqual(set(NeighborArea.objects.values_list('state', flat=True)), set(STATES))
        self.assertEqual(len(STATES), 51)
        self.assertEqual(NeighborArea.objects.count(), 32058)
        call_command('import_us_areas', stdout=StringIO())
        self.assertEqual(NeighborArea.objects.count(), 32058)
        self.legacy.refresh_from_db(); self.profile.refresh_from_db()
        self.assertEqual(self.legacy.state, 'CA')
        self.assertEqual(self.profile.area_id, self.legacy.pk)
        self.assertEqual(self.legacy.slug, 'ontario-ca')

    def test_search_finds_places_across_the_country_without_huge_responses(self):
        for state, query, expected in [('TX', 'Austin', 'Austin, Texas'), ('NY', 'New York', 'New York, New York'), ('AK', 'Anchorage', 'Anchorage'), ('HI', 'Honolulu', 'Honolulu'), ('DC', 'Washington', 'Washington')]:
            with self.subTest(state=state):
                response = self.client.get(reverse('neighbor_area_search'), {'state': state, 'q': query})
                data = response.json()
                self.assertTrue(any(expected in area['name'] for area in data['areas']))
                self.assertLessEqual(len(data['areas']), 40)
                self.assertLess(len(response.content), 15000)
        response = self.client.get(reverse('neighbor_area_search'), {'state': 'CA'})
        self.assertEqual(len(response.json()['areas']), 40)
        self.assertTrue(response.json()['limited'])

    def test_directory_filters_countrywide_and_does_not_return_unrelated_profiles(self):
        austin = NeighborArea.objects.get(name='Austin, Texas')
        profile = NeighborProfile.objects.create(owner_token='texas-neighbor', area=austin, nickname='Texas fictional neighbor', interest='technology', about='A test profile.', status='approved')
        page = self.client.get(reverse('neighbors'), {'state': 'TX', 'q': 'Austin'})
        self.assertContains(page, profile.nickname)
        self.assertNotContains(page, self.profile.nickname)
        self.assertLess(len(page.content), 50000)
        empty = self.client.get(reverse('neighbors'), {'state': 'ME', 'q': 'Portland'})
        self.assertNotContains(empty, self.profile.nickname)
        self.assertContains(empty, 'No approved profiles match')
        self.assertIn('Maine', empty.context['maps_url'])

    def test_profile_accepts_national_area_and_limits_rendered_choices(self):
        austin = NeighborArea.objects.get(name='Austin, Texas')
        form = NeighborProfileForm({'area': austin.pk, 'nickname': 'Fictional Texan', 'interest': 'technology', 'about': 'A test profile.', 'permission': 'on'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['area'], austin)
        page = self.client.get(reverse('neighbor_profile'), {'state': 'TX', 'q': 'Austin'})
        self.assertContains(page, 'Austin, Texas')
        self.assertLess(len(page.content), 30000)
        self.assertLessEqual(page.context['form'].fields['area'].queryset.count(), 40)

    def test_repeated_city_names_are_disambiguated_by_state(self):
        texas = self.client.get(reverse('neighbor_area_search'), {'state': 'TX', 'q': 'Paris'}).json()['areas']
        france_not_used = self.client.get(reverse('neighbor_area_search'), {'state': 'TN', 'q': 'Paris'}).json()['areas']
        self.assertTrue(any(area['name'] == 'Paris, Texas' for area in texas))
        self.assertTrue(any(area['name'] == 'Paris, Tennessee' for area in france_not_used))
