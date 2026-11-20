import hashlib
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.test import TestCase, Client, RequestFactory
from django.urls import reverse
from django.utils import timezone

from .models import (SupportCircle, SupportMember, SupportTask, SupportInvite, SupportNeighborIdentity,
                     NeighborArea, NeighborProfile, VolunteerReward)
from .support_middleware import SupportPrivacyMiddleware


class SupportCircleTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.owner = User.objects.create_user('organizer')
        self.family = User.objects.create_user('family')
        self.outsider = User.objects.create_user('outsider')
        self.staff = User.objects.create_user('staff', is_staff=True)
        self.circle = SupportCircle.objects.create(owner=self.owner, name='PRIVATE FAMILY CIRCLE')
        self.owner_member = SupportMember.objects.create(circle=self.circle, user=self.owner, role='owner')
        self.family_member = SupportMember.objects.create(circle=self.circle, user=self.family, role='family')
        self.task = SupportTask.objects.create(circle=self.circle, created_by=self.owner,
            title='PRIVATE TASK TITLE', details='PRIVATE TASK NOTES', category='technology')
        self.client.force_login(self.owner)

    def url(self, name, **extra):
        return reverse(name, kwargs={'circle_id':self.circle.pk, **extra})

    def invitation(self, role='family', **changes):
        code = secrets.token_urlsafe(24)
        invite = SupportInvite.objects.create(circle=self.circle, role=role,
            token_hash=hashlib.sha256(code.encode()).hexdigest(),
            expires_at=changes.pop('expires_at', timezone.now()+timedelta(hours=48)), **changes)
        return code, invite

    def join(self, code):
        return self.client.post(reverse('support_join'), {'code':code, 'consent':'on'})

    def neighbor(self, user, status='approved', is_sample=False):
        token = secrets.token_hex(32)
        area = NeighborArea.objects.create(slug='test-area-'+token[:8], name='Example city', state='TX', latitude=30, longitude=-97)
        profile = NeighborProfile.objects.create(owner_token=token, area=area, nickname='Example neighbor',
            interest='technology', about='Fictional profile', status=status, is_sample=is_sample)
        self.client.force_login(user)
        session = self.client.session; session['community_owner'] = token; session.save()
        return profile

    def action(self, action, client=None, task=None):
        return (client or self.client).post(self.url('support_task_action', task_id=(task or self.task).pk), {'action':action})

    def test_private_pages_require_membership_even_for_staff(self):
        for user in [self.outsider, self.staff]:
            self.client.force_login(user)
            for name in ['support_circle','support_members','support_invite','support_task_create']:
                response=self.client.get(self.url(name))
                self.assertEqual(response.status_code,404)
                self.assertNotContains(response,self.circle.name,status_code=404)
                self.assertEqual(response.headers['Cache-Control'],'private, no-store')
        self.client.logout()
        self.assertEqual(self.client.get(self.url('support_circle')).status_code,302)
        self.assertNotContains(self.client.get(reverse('support_home')),self.circle.name)

    def test_circle_create_and_individual_registration_do_not_grant_staff(self):
        response=self.client.post(reverse('support_create'),{'name':'New private circle','timezone':'America/Chicago'})
        self.assertEqual(response.status_code,302)
        new=SupportCircle.objects.get(name='New private circle')
        self.assertEqual(new.owner,self.owner)
        self.assertTrue(new.members.filter(user=self.owner,role='owner').exists())
        self.client.logout()
        response=self.client.post(reverse('support_register'),{'username':'new-helper','password1':'Demo-circle-test-PASS-839!','password2':'Demo-circle-test-PASS-839!','is_staff':'on'})
        self.assertEqual(response.status_code,302)
        user=get_user_model().objects.get(username='new-helper')
        self.assertFalse(user.is_staff); self.assertFalse(user.is_superuser)
        self.assertEqual(user.support_memberships.count(),0)

    def test_invites_are_hashed_single_use_and_owner_only(self):
        response=self.client.post(self.url('support_invite'),{'role':'family'})
        self.assertEqual(response.status_code,200)
        code=response.context['code']; invite=SupportInvite.objects.get()
        self.assertEqual(len(code),32); self.assertNotEqual(invite.token_hash,code)
        self.assertEqual(invite.token_hash,hashlib.sha256(code.encode()).hexdigest())
        self.assertNotContains(self.client.get(self.url('support_invite')),code)
        self.client.force_login(self.outsider)
        self.assertEqual(self.join(code).status_code,302)
        self.assertTrue(SupportMember.objects.filter(circle=self.circle,user=self.outsider,role='family').exists())
        self.client.force_login(self.staff)
        self.assertEqual(self.join(code).status_code,200)
        self.assertFalse(SupportMember.objects.filter(circle=self.circle,user=self.staff).exists())
        self.client.force_login(self.family)
        self.assertEqual(self.client.post(self.url('support_invite'),{'role':'owner'}).status_code,404)

    def test_expired_revoked_and_invalid_codes_do_not_grant_access(self):
        expired,_=self.invitation(expires_at=timezone.now()-timedelta(seconds=1))
        revoked,_=self.invitation(revoked=True)
        self.client.force_login(self.outsider)
        for code in [expired,revoked,'x'*32,'bad']:
            self.assertEqual(self.join(code).status_code,200)
        self.assertFalse(SupportMember.objects.filter(circle=self.circle,user=self.outsider).exists())

    def test_neighbor_invitation_requires_real_approved_profile_and_tracks_status(self):
        code,_=self.invitation('neighbor')
        self.client.force_login(self.outsider)
        self.assertEqual(self.join(code).status_code,200)
        profile=self.neighbor(self.outsider,status='pending')
        self.assertEqual(self.join(code).status_code,200)
        profile.status='approved'; profile.save()
        self.assertEqual(self.join(code).status_code,302)
        self.assertEqual(SupportNeighborIdentity.objects.get(user=self.outsider).profile,profile)
        self.assertEqual(self.client.get(self.url('support_circle')).status_code,200)
        self.assertEqual(self.client.get(self.url('support_task_create')).status_code,404)
        profile.status='hidden'; profile.save()
        self.assertEqual(self.client.get(self.url('support_circle')).status_code,404)
        self.assertEqual(self.action('claim').status_code,404)

    def test_fictional_directory_profiles_cannot_unlock_a_neighbor_invite(self):
        code,_=self.invitation('neighbor')
        self.neighbor(self.outsider,is_sample=True)
        self.join(code)
        self.assertFalse(SupportMember.objects.filter(circle=self.circle,user=self.outsider).exists())

    def test_profile_cannot_be_bound_to_another_account(self):
        profile=self.neighbor(self.outsider)
        SupportNeighborIdentity.objects.create(user=self.staff,profile=profile)
        code,_=self.invitation('neighbor')
        self.assertEqual(self.join(code).status_code,200)
        self.assertFalse(SupportMember.objects.filter(circle=self.circle,user=self.outsider).exists())

    def test_claim_is_exclusive_and_completion_requires_organizer(self):
        self.client.force_login(self.family)
        self.action('claim'); self.task.refresh_from_db()
        self.assertEqual(self.task.assignee,self.family)
        self.client.force_login(self.owner); self.action('claim'); self.task.refresh_from_db()
        self.assertEqual(self.task.assignee,self.family)
        self.action('complete'); self.task.refresh_from_db(); self.assertEqual(self.task.status,'claimed')
        self.client.force_login(self.family); self.action('complete'); self.action('confirm')
        self.task.refresh_from_db(); self.assertEqual(self.task.status,'review')
        self.client.force_login(self.owner); self.action('confirm'); self.task.refresh_from_db()
        self.assertEqual(self.task.status,'done')
        self.action('cancel'); self.task.refresh_from_db(); self.assertEqual(self.task.status,'done')

    def test_member_removal_revokes_access_and_reopens_unfinished_tasks(self):
        self.task.assignee=self.family; self.task.status='review'; self.task.save()
        self.client.post(self.url('support_member_action',member_id=self.family_member.pk))
        self.task.refresh_from_db(); self.assertEqual(self.task.status,'open'); self.assertIsNone(self.task.assignee)
        self.client.force_login(self.family)
        self.assertEqual(self.client.get(self.url('support_circle')).status_code,404)
        self.assertEqual(self.action('claim').status_code,404)

    def test_members_cannot_remove_the_owner_or_another_member(self):
        self.client.force_login(self.family)
        self.assertEqual(self.client.post(self.url('support_member_action',member_id=self.owner_member.pk)).status_code,404)
        self.assertTrue(SupportMember.objects.get(pk=self.owner_member.pk).active)
        self.assertEqual(self.client.post(self.url('support_member_action',member_id=self.family_member.pk)).status_code,302)
        self.assertFalse(SupportMember.objects.get(pk=self.family_member.pk).active)

    def test_archive_blocks_members_and_invites_and_owner_can_restore(self):
        code,invite=self.invitation()
        self.client.post(self.url('support_archive'),{'action':'archive'})
        self.circle.refresh_from_db(); self.assertTrue(self.circle.archived)
        invite.refresh_from_db(); self.assertTrue(invite.revoked)
        self.client.force_login(self.family); self.assertEqual(self.client.get(self.url('support_circle')).status_code,404)
        self.client.force_login(self.owner); self.client.post(self.url('support_archive'),{'action':'restore'})
        self.assertEqual(self.client.get(self.url('support_circle')).status_code,200)
        self.client.force_login(self.outsider); self.assertEqual(self.join(code).status_code,200)

    def test_tasks_are_escaped_and_use_circle_timezone(self):
        response=self.client.post(self.url('support_task_create'), {'title':'<script>bad</script>', 'category':'technology',
            'details':'<img src=x>', 'due_at':'2026-12-01T10:00', 'status':'done'})
        self.assertEqual(response.status_code,302)
        task=SupportTask.objects.get(title='<script>bad</script>')
        self.assertEqual(task.status,'open'); self.assertEqual(task.due_at.hour,16)
        page=self.client.get(self.url('support_circle'))
        self.assertContains(page,'&lt;script&gt;bad&lt;/script&gt;'); self.assertNotContains(page,'<script>bad</script>')
        self.assertContains(page,'10:00 AM CST')

    def test_post_and_csrf_required_and_other_circle_task_cannot_be_mutated(self):
        action=self.url('support_task_action',task_id=self.task.pk)
        self.assertEqual(self.client.get(action).status_code,405)
        strict=Client(enforce_csrf_checks=True); strict.force_login(self.owner)
        self.assertEqual(strict.post(action,{'action':'claim'}).status_code,403)
        other=SupportCircle.objects.create(owner=self.owner,name='Other')
        SupportMember.objects.create(circle=other,user=self.owner,role='owner')
        other_url=reverse('support_task_action',kwargs={'circle_id':other.pk,'task_id':self.task.pk})
        self.assertEqual(self.client.post(other_url,{'action':'claim'}).status_code,404)

    def test_reward_request_requires_confirmed_task_assignee_and_consent(self):
        self.task.assignee=self.family; self.task.status='review'; self.task.save()
        self.client.force_login(self.family)
        url=self.url('support_request_reward',task_id=self.task.pk)
        self.assertEqual(self.client.get(url).status_code,404)
        self.task.status='done'; self.task.save()
        self.assertEqual(self.client.post(url,{'volunteer_wallet':'0x'+'1'*40}).status_code,200)
        self.assertFalse(VolunteerReward.objects.exists())
        self.assertEqual(self.client.post(url,{'volunteer_wallet':'0x'+'1'*40,'consent':'on'}).status_code,302)
        reward=VolunteerReward.objects.get()
        self.assertEqual(reward.status,'requested'); self.assertIsNone(reward.approved_by); self.assertIsNone(reward.booking)
        self.client.post(url,{'volunteer_wallet':'0x'+'2'*40,'consent':'on'})
        self.assertEqual(VolunteerReward.objects.count(),1)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code,404)

    def test_source_constraint_and_private_cache_headers(self):
        with self.assertRaises(IntegrityError),transaction.atomic():
            VolunteerReward.objects.create(volunteer_wallet='0x'+'1'*40)
        for url in [reverse('support_home'),reverse('support_login'),self.url('support_circle')]:
            response=self.client.get(url)
            self.assertEqual(response.headers['Cache-Control'],'private, no-store')
            self.assertIn('Cookie',response.headers['Vary'])
            self.assertEqual(response.headers['Referrer-Policy'],'same-origin')

    def test_auth_and_join_attempts_are_throttled(self):
        factory=RequestFactory(); middleware=SupportPrivacyMiddleware(lambda request:HttpResponse())
        for _ in range(20):self.assertEqual(middleware(factory.post('/support/sign-in/')).status_code,200)
        self.assertEqual(middleware(factory.post('/support/sign-in/')).status_code,429)
