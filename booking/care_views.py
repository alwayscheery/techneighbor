from datetime import datetime, timedelta, timezone as dt_timezone
from functools import wraps
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django import forms
from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST

from .care_access import access_level, allowed_kinds
from .care_crypto import CareDataError, seal, unseal
from .care_forms import CareAccessForm, FORMS, DATE_FIELDS
from .models import CARE_KINDS, CareRecord, CareChange, CareActivity, SupportCircle, SupportMember, SupportTask
from .support_views import circle_login, member_for, event


def guard(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except CareDataError:
            return HttpResponse('Saved care information cannot be read right now. Please try again or ask the circle owner to contact the project owner.', status=503)
    return wrapped


def scope(request, circle_id, kind=None):
    circle = get_object_or_404(SupportCircle, pk=circle_id)
    member = member_for(request, circle)
    if kind is not None and (kind not in FORMS or access_level(member, kind) == 'none'):
        raise Http404
    return circle, member


def record_context(record):
    return 'record:' + str(record.pk) + ':' + record.kind


def change_context(change):
    return 'change:' + str(change.pk) + ':' + change.kind


def read_record(record):
    return unseal(record.circle_id, record_context(record), record.encrypted_payload)


def date_value(fields, kind):
    value = fields.get(DATE_FIELDS.get(kind, ''))
    if isinstance(value, str):
        value = parse_datetime(value) if value else None
    return value


def display_fields(kind, fields, zone):
    rows = []
    for name, field in FORMS[kind].base_fields.items():
        if name in ['version','title','name'] or fields.get(name) in [None, '']:
            continue
        value = fields[name]
        if name == DATE_FIELDS.get(kind):
            value = date_value(fields, kind)
            value = timezone.localtime(value, ZoneInfo(zone)).strftime('%a, %b %d, %Y · %I:%M %p %Z') if value else ''
        elif isinstance(field, forms.ChoiceField):
            value = dict(field.choices).get(value, value)
        rows.append({'label':field.label or name.replace('_',' ').capitalize(), 'value':value})
    return rows


def care_event(circle, kind, actor, action):
    CareActivity.objects.create(circle=circle, kind=kind, actor=actor, action=action)


def apply_fields(circle, kind, fields, actor, record=None):
    if record is None:
        if circle.care_records.count() >= 250:
            raise ValueError('This circle has reached its demo limit of 250 care records.')
        record = CareRecord(circle=circle, kind=kind, created_by=actor, updated_by=actor)
    else:
        record.version += 1
        record.updated_by = actor
    record.encrypted_payload = seal(circle.pk, record_context(record), fields)
    record.due_at = date_value(fields, kind)
    record.save()
    return record


@circle_login
@guard
def home(request, circle_id):
    circle, member = scope(request, circle_id)
    kinds = allowed_kinds(member)
    selected = request.GET.get('kind') or (kinds[0] if kinds else None)
    if selected and selected not in kinds:
        raise Http404
    archived = request.GET.get('archived') == '1' and circle.owner_id == request.user.pk
    records = []
    if selected:
        for record in circle.care_records.filter(kind=selected, archived=archived).order_by('due_at','-updated_at')[:100]:
            fields = read_record(record)
            records.append({'id':record.pk, 'title':fields.get('title') or fields.get('name'),
                'rows':display_fields(selected, fields, circle.timezone), 'due':record.due_at,
                'overdue':bool(record.due_at and record.due_at < timezone.now() and fields.get('status') not in ['attended','cancelled','picked_up','done']),
                'version':record.version, 'archived':record.archived})
    return render(request, 'care/home.html', {'circle':circle, 'member':member, 'selected':selected,
        'tabs':[(key,label) for key,label in CARE_KINDS if key in kinds], 'records':records,
        'can_suggest':bool(selected and access_level(member, selected)=='help'),
        'archived':archived, 'care_activity':circle.care_activity.filter(kind__in=kinds).select_related('actor').order_by('-created_at')[:20]})


@circle_login
@guard
def edit(request, circle_id, kind, record_id=None):
    circle, member = scope(request, circle_id, kind)
    if access_level(member, kind) != 'help':
        raise Http404
    record = get_object_or_404(CareRecord, pk=record_id, circle=circle, kind=kind, archived=False) if record_id else None
    initial = read_record(record) if record else {}
    if record:
        initial = dict(initial, version=record.version)
        key = DATE_FIELDS.get(kind)
        if key and initial.get(key):
            initial[key] = date_value(initial, kind)
    with timezone.override(ZoneInfo(circle.timezone)):
        form = FORMS[kind](request.POST if request.method=='POST' else None, initial=initial)
        if request.method=='POST' and form.is_valid():
            with transaction.atomic():
                circle = SupportCircle.objects.select_for_update().get(pk=circle.pk)
                member = member_for(request, circle)
                if access_level(member, kind) != 'help':
                    raise Http404
                if record:
                    record = CareRecord.objects.select_for_update().get(pk=record.pk)
                if record and (record.archived or record.version != form.cleaned_data['version']):
                    form.add_error(None, 'This record changed. Reload it before submitting your update.')
                else:
                    fields = {key:value for key,value in form.cleaned_data.items() if key!='version'}
                    if circle.owner_id == request.user.pk:
                        try:
                            apply_fields(circle, kind, fields, request.user, record)
                        except ValueError as exc:
                            form.add_error(None, str(exc))
                        else:
                            care_event(circle, kind, request.user, 'Updated a care record' if record else 'Added a care record')
                            return redirect('care_home', circle_id=circle.pk)
                    elif circle.care_changes.filter(author=request.user,status='pending').count() >= 5:
                        form.add_error(None, 'You already have five changes awaiting the owner’s review.')
                    else:
                        change = CareChange(circle=circle, kind=kind, record=record, author=request.user, base_version=record.version if record else 0)
                        change.encrypted_payload = seal(circle.pk, change_context(change), fields)
                        change.save()
                        care_event(circle, kind, request.user, 'Suggested a care update')
                        messages.success(request, 'Your suggestion is saved privately for the circle owner to approve.')
                        return redirect('care_home', circle_id=circle.pk)
        return render(request, 'care/form.html', {'circle':circle, 'form':form, 'kind':kind,
            'label':dict(CARE_KINDS)[kind], 'singular':{'appointments':'appointment','medications':'medication record','contacts':'care contact','benefits':'benefit reminder'}[kind], 'editing':bool(record), 'is_owner':circle.owner_id==request.user.pk})


@circle_login
@guard
def reviews(request, circle_id):
    circle = get_object_or_404(SupportCircle, pk=circle_id, owner=request.user, archived=False)
    member_for(request,circle)
    changes=[]
    for change in circle.care_changes.filter(status='pending').select_related('author','record').order_by('created_at')[:50]:
        fields=unseal(circle.pk,change_context(change),change.encrypted_payload)
        original=read_record(change.record) if change.record else None
        changes.append({'id':change.pk,'title':fields.get('title') or fields.get('name'),'author':change.author.username,
            'kind':dict(CARE_KINDS)[change.kind], 'rows':display_fields(change.kind,fields,circle.timezone),
            'original_rows':display_fields(change.kind,original,circle.timezone) if original else None,
            'original_title':(original.get('title') or original.get('name')) if original else None})
    return render(request,'care/reviews.html',{'circle':circle,'changes':changes})


@circle_login
@require_POST
@guard
def review_action(request, circle_id, change_id):
    with transaction.atomic():
        circle=get_object_or_404(SupportCircle.objects.select_for_update(),pk=circle_id,owner=request.user,archived=False)
        member_for(request,circle)
        change=get_object_or_404(CareChange.objects.select_for_update(),pk=change_id,circle=circle,status='pending')
        action=request.POST.get('action')
        if action not in ['approve','reject']:
            return HttpResponse('Choose approve or reject.',status=400)
        if action=='approve':
            try:
                author_member=member_for(SimpleNamespace(user=change.author),circle)
            except Http404:
                author_member=None
            record=get_object_or_404(CareRecord.objects.select_for_update(),pk=change.record_id,circle=circle) if change.record_id else None
            if not author_member or access_level(author_member,change.kind)!='help':
                messages.error(request,'The author no longer has permission to suggest this update.')
            elif record and (record.archived or record.version!=change.base_version):
                messages.error(request,'The record changed since this suggestion. Ask the helper to submit a new suggestion.')
            else:
                fields=unseal(circle.pk,change_context(change),change.encrypted_payload)
                try:
                    apply_fields(circle,change.kind,fields,request.user,record)
                except ValueError as exc:
                    messages.error(request,str(exc))
                else:
                    change.status='approved'
                    care_event(circle,change.kind,request.user,'Approved a suggested update')
            if change.status!='approved':
                return redirect('care_reviews',circle_id=circle.pk)
        else:
            change.status='rejected'
            care_event(circle,change.kind,request.user,'Declined a suggested update')
        change.reviewed_by=request.user;change.save(update_fields=['status','reviewed_by'])
    return redirect('care_reviews',circle_id=circle_id)


@circle_login
def permissions(request, circle_id, member_id):
    circle=get_object_or_404(SupportCircle,pk=circle_id,owner=request.user,archived=False)
    member_for(request,circle)
    target=get_object_or_404(SupportMember,pk=member_id,circle=circle,active=True)
    if target.user_id==circle.owner_id:
        raise Http404
    form=CareAccessForm(request.POST if request.method=='POST' else None,initial=target.care_permissions)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            circle=SupportCircle.objects.select_for_update().get(pk=circle.pk)
            member_for(request,circle)
            target=SupportMember.objects.select_for_update().get(pk=target.pk)
            if not target.active:
                raise Http404
            target.care_permissions=form.permissions();target.save(update_fields=['care_permissions'])
            not_shared=[kind for kind,_ in CARE_KINDS if access_level(target,kind)=='none']
            not_help=[kind for kind,_ in CARE_KINDS if access_level(target,kind)!='help']
            circle.tasks.filter(assignee=target.user,status__in=['claimed','review'],care_record__kind__in=not_shared).update(status='open',assignee=None)
            circle.care_changes.filter(author=target.user,status='pending',kind__in=not_help).update(status='rejected',reviewed_by=request.user)
            event(circle,request.user,'Updated a member’s access permissions')
        return redirect('support_members',circle_id=circle.pk)
    return render(request,'care/access.html',{'circle':circle,'target':target,'form':form})


@circle_login
@require_POST
def record_action(request,circle_id,record_id):
    with transaction.atomic():
        circle=get_object_or_404(SupportCircle.objects.select_for_update(),pk=circle_id,owner=request.user,archived=False)
        member_for(request,circle)
        record=get_object_or_404(CareRecord.objects.select_for_update(),pk=record_id,circle=circle)
        action=request.POST.get('action')
        if action not in ['archive','restore']:
            return HttpResponse('Choose archive or restore.',status=400)
        record.archived=action=='archive';record.version+=1;record.save(update_fields=['archived','version'])
        if record.archived:
            circle.tasks.filter(care_record=record,status__in=['open','claimed','review']).update(status='cancelled',assignee=None)
            circle.care_changes.filter(record=record,status='pending').update(status='rejected',reviewed_by=request.user)
        care_event(circle,record.kind,request.user,'Archived a care record' if record.archived else 'Restored a care record')
    return redirect('care_home',circle_id=circle_id)


@circle_login
@require_POST
def help_task(request,circle_id,record_id):
    with transaction.atomic():
        circle=get_object_or_404(SupportCircle.objects.select_for_update(),pk=circle_id,owner=request.user,archived=False)
        member_for(request,circle)
        record=get_object_or_404(CareRecord,pk=record_id,circle=circle,archived=False)
        existing=circle.tasks.filter(care_record=record,status__in=['open','claimed','review']).first()
        if not existing:
            if circle.tasks.count()>=250:
                messages.error(request,'This circle has reached its demo task limit.')
                return redirect('support_circle',circle_id=circle_id)
            labels={'appointments':('Appointment support','transport'),'medications':('Pharmacy pickup support','errands'),
                    'contacts':('Care contact support','other'),'benefits':('Renewal paperwork support','other')}
            title,category=labels[record.kind]
            task=SupportTask.objects.create(circle=circle,care_record=record,created_by=request.user,title=title,category=category,
                details='Read the shared care record or ask the circle owner for the arrangements.')
            event(circle,request.user,'Posted a care support task',task)
    return redirect('support_circle',circle_id=circle_id)


def escape_ics(value):
    return str(value).replace('\\','\\\\').replace('\r','').replace('\n','\\n').replace(';','\\;').replace(',','\\,')


@circle_login
@guard
def calendar_entry(request,circle_id,record_id):
    circle,member=scope(request,circle_id,'appointments')
    record=get_object_or_404(CareRecord,pk=record_id,circle=circle,kind='appointments',archived=False)
    fields=read_record(record);start=date_value(fields,'appointments')
    end=start+timedelta(minutes=fields['duration'])
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//TechNeighbor//Care Planner//EN','BEGIN:VEVENT',
        'UID:'+str(record.pk)+'@techneighbor', 'DTSTAMP:'+timezone.now().strftime('%Y%m%dT%H%M%SZ'),
        'DTSTART:'+start.astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ'),
        'DTEND:'+end.astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ'),
        'SUMMARY:'+escape_ics(fields['title']),'LOCATION:'+escape_ics(fields.get('location','')),
        'STATUS:'+('CANCELLED' if fields['status']=='cancelled' else 'CONFIRMED'),'END:VEVENT','END:VCALENDAR']
    # Fold UTF-8 lines at <=75 octets, preserving multibyte characters.
    folded=[]
    for line in lines:
        current=''
        for char in line:
            if len((current+char).encode())>74:
                folded.append(current);current=' '+char
            else:current+=char
        folded.append(current)
    response=HttpResponse('\r\n'.join(folded)+'\r\n',content_type='text/calendar; charset=utf-8')
    response['Content-Disposition']='attachment; filename="appointment.ics"'
    return response
