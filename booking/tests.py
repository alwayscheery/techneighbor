from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from .forms import available_slots
from .models import Booking, SessionSlot, SUPPORT_CATEGORIES


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class BookingWorkflowTests(TestCase):
    def setUp(self):
        self.slot = SessionSlot.objects.create(starts_at=timezone.now() + timedelta(days=2))
        self.payload = {
            'topic': 'video', 'slot': self.slot.pk, 'name': 'Maria Example',
            'contact': 'fictional@example.test', 'booking_for': 'self',
        }

    def make_booking(self, **kwargs):
        return Booking.objects.create(slot=self.slot, name='Maria Example', topic='video', **kwargs)

    def test_booking_persists_and_confirmation_omits_contact(self):
        response = self.client.post(reverse('book'), self.payload)
        booking = Booking.objects.get()
        self.assertRedirects(response, reverse('confirmation', args=[booking.reference]))
        page = self.client.get(response.url)
        self.assertContains(page, 'Maria Example')
        self.assertContains(page, 'Video calls')
        self.assertNotContains(page, 'fictional@example.test')
        self.assertEqual(page.headers['Cache-Control'], 'no-store')
        self.assertFalse(available_slots().filter(pk=self.slot.pk).exists())

    def test_taken_slot_rejected_without_duplicate(self):
        self.make_booking()
        response = self.client.post(reverse('book'), self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors.get('slot'))
        self.assertEqual(Booking.objects.count(), 1)

    def test_database_prevents_double_booking(self):
        self.make_booking()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_booking()

    def test_cancellation_releases_slot_and_preserves_history(self):
        booking = self.make_booking()
        response = self.client.post(reverse('cancel_booking', args=[booking.reference]))
        self.assertEqual(response.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')
        self.assertTrue(available_slots().filter(pk=self.slot.pk).exists())
        self.client.post(reverse('book'), self.payload)
        self.assertEqual(Booking.objects.count(), 2)
        self.assertEqual(Booking.objects.filter(status='booked').count(), 1)

    def test_past_slot_rejected(self):
        self.slot.starts_at = timezone.now() - timedelta(hours=1)
        self.slot.save()
        response = self.client.post(reverse('book'), self.payload)
        self.assertTrue(response.context['form'].errors.get('slot'))
        self.assertEqual(Booking.objects.count(), 0)

    def test_required_name_and_valid_topic(self):
        response = self.client.post(reverse('book'), {**self.payload, 'name': '', 'topic': 'unknown'})
        self.assertIn('name', response.context['form'].errors)
        self.assertIn('topic', response.context['form'].errors)
        self.assertEqual(Booking.objects.count(), 0)

    def test_cancellation_requires_post(self):
        booking = self.make_booking()
        self.assertEqual(self.client.get(reverse('cancel_booking', args=[booking.reference])).status_code, 405)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'booked')

    def test_csrf_required_to_book_or_cancel(self):
        csrf_client = Client(enforce_csrf_checks=True)
        self.assertEqual(csrf_client.post(reverse('book'), self.payload).status_code, 403)
        booking = self.make_booking()
        self.assertEqual(csrf_client.post(reverse('cancel_booking', args=[booking.reference])).status_code, 403)

    def test_https_confirmation_allows_same_origin_cancellation(self):
        booking = self.make_booking()
        client = Client(enforce_csrf_checks=True)
        confirmation_url = reverse('confirmation', args=[booking.reference])
        page = client.get(confirmation_url, secure=True)
        self.assertEqual(page.headers['Referrer-Policy'], 'same-origin')
        response = client.post(
            reverse('cancel_booking', args=[booking.reference]),
            {'csrfmiddlewaretoken': client.cookies['csrftoken'].value},
            secure=True, HTTP_REFERER='https://testserver' + confirmation_url,
        )
        self.assertEqual(response.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')

    def test_name_is_html_escaped(self):
        self.client.post(reverse('book'), {**self.payload, 'name': '<script>alert(1)</script>'})
        booking = Booking.objects.get()
        response = self.client.get(reverse('confirmation', args=[booking.reference]))
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')

    def test_coordinator_requires_staff(self):
        booking = self.make_booking()
        update_url = reverse('update_booking', args=[booking.reference])
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 302)
        self.assertEqual(self.client.post(update_url, {'action': 'complete'}).status_code, 302)
        user = get_user_model().objects.create_user('resident', password='Example-test-password-42')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 302)
        self.assertEqual(self.client.post(update_url, {'action': 'complete'}).status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'booked')

    def test_staff_can_complete_but_completed_session_cannot_be_cancelled(self):
        booking = self.make_booking()
        staff = get_user_model().objects.create_user('staff', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)
        response = self.client.post(reverse('update_booking', args=[booking.reference]), {'action': 'complete'})
        self.assertRedirects(response, reverse('dashboard'))
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'completed')
        self.assertIsNotNone(booking.completed_at)
        self.client.post(reverse('cancel_booking', args=[booking.reference]))
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'completed')

    def test_no_slots_displays_clear_empty_state(self):
        self.slot.delete()
        response = self.client.get(reverse('book'))
        self.assertContains(response, 'No sessions available right now')
        self.assertContains(response, 'disabled')

    def test_confirmation_uses_private_random_reference(self):
        self.make_booking()
        self.assertEqual(self.client.get('/booking/1/').status_code, 404)
        import uuid
        self.assertEqual(self.client.get(reverse('confirmation', args=[uuid.uuid4()])).status_code, 404)

    def test_every_activity_books_with_the_correct_support_details(self):
        for category, details in SUPPORT_CATEGORIES.items():
            for topic, label in details['topics']:
                with self.subTest(category=category, topic=topic):
                    response = self.client.post(reverse('book'), {
                        **self.payload, 'topic': topic, 'category': category,
                    })
                    self.assertEqual(response.status_code, 302)
                    booking = Booking.objects.get(status='booked')
                    self.assertEqual(booking.support_category, category)
                    confirmation = self.client.get(response.url)
                    self.assertContains(confirmation, escape(label))
                    self.assertContains(confirmation, details['preparation'])
                    booking.status = Booking.Status.CANCELLED
                    booking.save()

    def test_activity_must_belong_to_selected_category(self):
        response = self.client.post(reverse('book'), {
            **self.payload, 'category': 'companionship', 'topic': 'video',
        })
        self.assertTrue(response.context['form'].errors.get('topic'))
        self.assertEqual(Booking.objects.count(), 0)

    def test_legacy_technology_links_and_new_category_links(self):
        for topic in ['video', 'phone', 'photos']:
            with self.subTest(topic=topic):
                page = self.client.get(reverse('book'), {'topic': topic})
                self.assertEqual(page.context['selected_category'], 'technology')
                self.assertEqual(page.context['form'].initial['topic'], topic)
        page = self.client.get(reverse('book'), {'category': 'companionship'})
        self.assertContains(page, 'A friendly chat')
        self.assertNotContains(page, 'name="topic" value="video"')
        self.assertContains(page, 'Just bring yourself')
        self.assertNotContains(page, 'Bring your own device')

    def test_coordinator_can_filter_support_categories(self):
        self.make_booking()
        chat_slot = SessionSlot.objects.create(starts_at=timezone.now() + timedelta(days=3))
        Booking.objects.create(slot=chat_slot, name='Companion Example', topic='chat')
        staff = get_user_model().objects.create_user('staff', is_staff=True)
        self.client.force_login(staff)
        page = self.client.get(reverse('dashboard'), {'category': 'companionship'})
        self.assertContains(page, 'Companion Example')
        self.assertNotContains(page, 'Maria Example')
        self.assertEqual(page.context['counts']['booked'], 2)
        page = self.client.get(reverse('dashboard'), {'category': 'technology'})
        self.assertContains(page, 'Maria Example')
        self.assertNotContains(page, 'Companion Example')

    def test_shared_capacity_across_support_categories(self):
        self.make_booking()
        page = self.client.post(reverse('book'), {
            **self.payload, 'category': 'companionship', 'topic': 'chat',
        })
        self.assertTrue(page.context['form'].errors.get('slot'))
        self.assertEqual(Booking.objects.count(), 1)
