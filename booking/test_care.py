import hashlib
import secrets
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import care_views
from .care_crypto import CareDataError, seal, unseal
from .models import (CareRecord,CareChange,CareActivity,SupportCircle,SupportMember,SupportTask,SupportInvite)


class CarePlannerTests(TestCase):
    def setUp(self):
        cache.clear(); User=get_user_model()
        self.owner=User.objects.create_user('care-owner')
        self.helper=User.objects.create_user('care-helper')
        self.outsider=User.objects.create_user('uninvited')
        self.staff=User.objects.create_user('care-staff',is_staff=True)
        self.circle=SupportCircle.objects.create(owner=self.owner,name='Private care circle',timezone='America/Chicago')
        SupportMember.objects.create(circle=self.circle,user=self.owner,role='owner')
        self.member=SupportMember.objects.create(circle=self.circle,user=self.helper,role='family')
        self.client.force_login(self.owner)

    def url(self,name,**kwargs):
        return reverse(name,kwargs={'circle_id':self.circle.pk,**kwargs})

    def record(self,kind='appointments',**changes):
        values={
            'appointments':{'title':'PRIVATE CLINIC VISIT','when':datetime(2026,12,1,16,tzinfo=dt_timezone.utc),'duration':30,'location':'PRIVATE CLINIC','notes':'PRIVATE VISIT NOTES','status':'scheduled'},
            'medications':{'name':'PRIVATE MEDICATION','instructions':'PRIVATE EXISTING INSTRUCTIONS','schedule':'Existing reminder times','pharmacy':'PRIVATE PHARMACY','refill_at':None,'status':'listed'},
            'contacts':{'name':'PRIVATE PROVIDER','role':'provider','phone':'555-0100','notes':'PRIVATE CONTACT NOTES'},
            'benefits':{'name':'PRIVATE BENEFIT','renewal_at':None,'notes':'PRIVATE RENEWAL STEPS','status':'todo'},
        }[kind]
        values.update(changes)
        return care_views.apply_fields(self.circle,kind,values,self.owner)

    def permit(self,**permissions):
        self.member.care_permissions=permissions;self.member.save(update_fields=['care_permissions'])

    def proposal(self,record,**changes):
        fields=care_views.read_record(record);fields.update(changes)
        change=CareChange(circle=self.circle,record=record,kind=record.kind,author=self.helper,base_version=record.version)
        change.encrypted_payload=seal(self.circle.pk,care_views.change_context(change),fields);change.save()
        return change

    def test_default_private_and_category_permissions_are_enforced_for_members_and_staff(self):
        self.record();self.record('medications');self.record('contacts');self.record('benefits')
        self.client.force_login(self.helper)
        page=self.client.get(self.url('care_home'))
        for private in ['PRIVATE CLINIC','PRIVATE MEDICATION','PRIVATE PROVIDER','PRIVATE BENEFIT']:
            self.assertNotContains(page,private)
        self.assertEqual(self.client.get(self.url('care_home')+'?kind=medications').status_code,404)
        self.permit(appointments='view')
        page=self.client.get(self.url('care_home'))
        self.assertContains(page,'PRIVATE CLINIC VISIT');self.assertNotContains(page,'PRIVATE MEDICATION')
        self.assertEqual(self.client.get(self.url('care_create',kind='appointments')).status_code,404)
        for user in [self.outsider,self.staff]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url('care_home')).status_code,404)
            self.assertEqual(self.client.get(self.url('care_reviews')).status_code,404)

    def test_encryption_authenticates_context_tampering_and_key_rotation(self):
        record=self.record('medications');fields=care_views.read_record(record)
        self.assertNotIn('PRIVATE MEDICATION',record.encrypted_payload)
        self.assertNotIn('PRIVATE EXISTING INSTRUCTIONS',record.encrypted_payload)
        context=care_views.record_context(record)
        self.assertNotEqual(seal(self.circle.pk,context,fields),seal(self.circle.pk,context,fields))
        for circle,ctx,token in [(self.circle.pk,'another-record',record.encrypted_payload),
            ('another-circle',context,record.encrypted_payload), (self.circle.pk,context,record.encrypted_payload[:-4]+'AAAA')]:
            with self.assertRaises(CareDataError):unseal(circle,ctx,token)
        old=settings.SECRET_KEY
        with override_settings(SECRET_KEY='new-secret-for-rotation'*4,SECRET_KEY_FALLBACKS=[]):
            with self.assertRaises(CareDataError):care_views.read_record(record)
        with override_settings(SECRET_KEY='new-secret-for-rotation'*4,SECRET_KEY_FALLBACKS=[old]):
            self.assertEqual(care_views.read_record(record)['name'],'PRIVATE MEDICATION')

    def test_helper_suggestions_require_owner_approval_and_stay_encrypted(self):
        record=self.record('medications');self.permit(medications='help')
        self.client.force_login(self.helper)
        data={'version':record.version,'name':'SUGGESTED PRIVATE MEDICATION','instructions':'EXISTING PRIVATE DIRECTIONS','schedule':'As already directed','pharmacy':'Example pharmacy','refill_at':'','status':'ready'}
        response=self.client.post(self.url('care_edit',kind='medications',record_id=record.pk),data)
        self.assertEqual(response.status_code,302)
        record.refresh_from_db();self.assertEqual(care_views.read_record(record)['name'],'PRIVATE MEDICATION')
        change=CareChange.objects.get();self.assertNotIn('SUGGESTED PRIVATE MEDICATION',change.encrypted_payload)
        self.assertEqual(self.client.post(self.url('care_review_action',change_id=change.pk),{'action':'approve'}).status_code,404)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(self.url('care_reviews')),'SUGGESTED PRIVATE MEDICATION')
        self.client.post(self.url('care_review_action',change_id=change.pk),{'action':'approve'})
        record.refresh_from_db();change.refresh_from_db()
        self.assertEqual(care_views.read_record(record)['name'],'SUGGESTED PRIVATE MEDICATION')
        self.assertEqual(change.status,'approved');self.assertEqual(record.version,2)

    def test_stale_proposals_cannot_overwrite_newer_owner_edits(self):
        record=self.record();self.permit(appointments='help')
        change=self.proposal(record,title='OLD PROPOSAL')
        fields=care_views.read_record(record);fields['title']='NEW OWNER RECORD'
        care_views.apply_fields(self.circle,'appointments',fields,self.owner,record)
        self.client.post(self.url('care_review_action',change_id=change.pk),{'action':'approve'})
        record.refresh_from_db();self.assertEqual(care_views.read_record(record)['title'],'NEW OWNER RECORD')
        change.refresh_from_db();self.assertEqual(change.status,'pending')
        self.client.post(self.url('care_review_action',change_id=change.pk),{'action':'reject'})
        change.refresh_from_db();self.assertEqual(change.status,'rejected')

    def test_invite_scopes_are_explicit_and_cannot_be_changed_by_joiner(self):
        response=self.client.post(self.url('support_invite'),{'role':'family','appointments':'view','medications':'none','contacts':'help','benefits':'none'})
        code=response.context['code'];self.client.force_login(self.outsider)
        response=self.client.post(reverse('support_join'),{'code':code,'consent':'on','medications':'help'})
        self.assertEqual(response.status_code,302)
        member=SupportMember.objects.get(circle=self.circle,user=self.outsider)
        self.assertEqual(member.care_permissions['appointments'],'view')
        self.assertEqual(member.care_permissions['medications'],'none')
        self.assertEqual(member.care_permissions['contacts'],'help')

    def test_revocation_hides_records_tasks_and_activity_and_releases_claims(self):
        record=self.record('medications');self.permit(medications='help');change=self.proposal(record,status='ready')
        self.client.post(self.url('care_help_task',record_id=record.pk))
        task=SupportTask.objects.get(care_record=record)
        self.client.force_login(self.helper)
        self.client.post(self.url('support_task_action',task_id=task.pk),{'action':'claim'})
        self.assertContains(self.client.get(self.url('support_circle')),'Pharmacy pickup support')
        self.client.force_login(self.owner)
        self.client.post(self.url('care_permissions',member_id=self.member.pk),{'appointments':'none','medications':'none','contacts':'none','benefits':'none'})
        task.refresh_from_db();change.refresh_from_db()
        self.assertEqual(task.status,'open');self.assertIsNone(task.assignee);self.assertEqual(change.status,'rejected')
        self.client.force_login(self.helper)
        page=self.client.get(self.url('support_circle'));self.assertNotContains(page,'Pharmacy pickup support')
        self.assertNotContains(page,'Posted a care support task')
        self.assertEqual(self.client.post(self.url('support_task_action',task_id=task.pk),{'action':'claim'}).status_code,404)
        self.assertEqual(self.client.get(self.url('care_home')+'?kind=medications').status_code,404)

    def test_only_owner_can_manage_access_and_archive_records(self):
        record=self.record()
        self.client.force_login(self.helper)
        self.assertEqual(self.client.post(self.url('care_permissions',member_id=self.member.pk),{'appointments':'help'}).status_code,404)
        self.assertEqual(self.client.post(self.url('care_record_action',record_id=record.pk),{'action':'archive'}).status_code,404)
        self.client.force_login(self.owner)
        self.client.post(self.url('care_help_task',record_id=record.pk))
        self.client.post(self.url('care_help_task',record_id=record.pk))
        self.assertEqual(SupportTask.objects.filter(care_record=record).count(),1)
        self.client.post(self.url('care_record_action',record_id=record.pk),{'action':'archive'})
        record.refresh_from_db();self.assertTrue(record.archived)
        self.assertEqual(SupportTask.objects.get(care_record=record).status,'cancelled')
        self.assertEqual(self.client.get(self.url('care_calendar',record_id=record.pk)).status_code,404)
        self.client.post(self.url('care_record_action',record_id=record.pk),{'action':'restore'})
        self.client.post(self.url('care_help_task',record_id=record.pk))
        self.assertEqual(SupportTask.objects.filter(care_record=record).count(),2)

    def test_appointments_use_circle_timezone_and_calendar_export_is_private_and_escaped(self):
        response=self.client.post(self.url('care_create',kind='appointments'),{'title':'Private visit','when':'2026-12-01T10:00','duration':30,'location':'Private clinic','notes':'','status':'scheduled'})
        self.assertEqual(response.status_code,302)
        record=CareRecord.objects.get();self.assertEqual(record.due_at.hour,16)
        page=self.client.get(self.url('care_home'));self.assertContains(page,'10:00 AM CST')
        fields=care_views.read_record(record);fields['title']='Visit\nBEGIN:VEVENT';fields['location']='Clinic, example; north'
        care_views.apply_fields(self.circle,'appointments',fields,self.owner,record)
        exported=self.client.get(self.url('care_calendar',record_id=record.pk))
        self.assertEqual(exported.status_code,200)
        self.assertIn(b'DTSTART:20261201T160000Z',exported.content)
        self.assertEqual(exported.content.count(b'\r\nBEGIN:VEVENT\r\n'),1)
        self.assertIn(b'SUMMARY:Visit\\nBEGIN:VEVENT',exported.content)
        self.assertEqual(exported.headers['Cache-Control'],'private, no-store')
        self.client.force_login(self.helper)
        self.assertEqual(self.client.get(self.url('care_calendar',record_id=record.pk)).status_code,404)

    def test_approval_and_care_activity_do_not_leak_to_general_task_board(self):
        record=self.record('medications');self.permit(medications='help');self.proposal(record,status='ready')
        CareActivity.objects.create(circle=self.circle,kind='medications',actor=self.owner,action='PRIVATE MEDICATION ACTIVITY')
        self.client.force_login(self.helper)
        page=self.client.get(self.url('support_circle'))
        self.assertNotContains(page,'PRIVATE MEDICATION');self.assertNotContains(page,'PRIVATE MEDICATION ACTIVITY')
        self.assertEqual(self.client.get(self.url('care_reviews')).status_code,404)
        self.permit(contacts='view')
        self.assertNotContains(self.client.get(self.url('care_home')),'PRIVATE MEDICATION ACTIVITY')

    def test_removed_helper_cannot_have_pending_changes_approved(self):
        record=self.record();self.permit(appointments='help');change=self.proposal(record,title='Changed title')
        self.client.post(self.url('support_member_action',member_id=self.member.pk))
        change.refresh_from_db();self.assertEqual(change.status,'rejected')
        self.assertEqual(self.client.post(self.url('care_review_action',change_id=change.pk),{'action':'approve'}).status_code,404)

    def test_bad_ciphertext_fails_closed_and_mutations_require_csrf_and_post(self):
        record=self.record();record.encrypted_payload='v1.invalid';record.save(update_fields=['encrypted_payload'])
        response=self.client.get(self.url('care_home'))
        self.assertEqual(response.status_code,503);self.assertNotContains(response,'PRIVATE CLINIC',status_code=503)
        url=self.url('care_record_action',record_id=record.pk)
        self.assertEqual(self.client.get(url).status_code,405)
        strict=Client(enforce_csrf_checks=True);strict.force_login(self.owner)
        self.assertEqual(strict.post(url,{'action':'archive'}).status_code,403)

    def test_all_four_forms_and_owner_version_checks(self):
        for kind in ['appointments','medications','contacts','benefits']:
            self.assertEqual(self.client.get(self.url('care_create',kind=kind)).status_code,200)
        record=self.record('contacts')
        response=self.client.post(self.url('care_edit',kind='contacts',record_id=record.pk),{'version':0,'name':'Wrong update','role':'family','phone':'','notes':''})
        self.assertEqual(response.status_code,200)
        record.refresh_from_db();self.assertEqual(care_views.read_record(record)['name'],'PRIVATE PROVIDER')
