import hashlib
import secrets
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.contrib.auth import login, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .community_views import owner_token
from .models import (NeighborProfile, SupportCircle, SupportMember, SupportNeighborIdentity,
                     SupportInvite, SupportTask, SupportActivity)
from .support_forms import CircleForm, InviteForm, JoinForm, SupportTaskForm
from .care_access import task_filter, check_task_access


def circle_login(view):
    return login_required(view, login_url='support_login')


def member_for(request, circle, allow_archived=False):
    if circle.archived and not allow_archived:
        raise Http404
    member = get_object_or_404(SupportMember.objects.select_related('neighbor_profile'),
        circle=circle, user=request.user, active=True)
    if member.role == 'neighbor' and (not member.neighbor_profile or
            member.neighbor_profile.status != 'approved' or member.neighbor_profile.is_sample):
        raise Http404
    return member


def event(circle, actor, action, task=None):
    SupportActivity.objects.create(circle=circle, actor=actor, action=action, task=task)


def home(request):
    memberships = []
    if request.user.is_authenticated:
        for member in SupportMember.objects.filter(user=request.user, active=True).select_related('circle', 'neighbor_profile'):
            if member.role == 'neighbor' and (not member.neighbor_profile or member.neighbor_profile.status != 'approved' or member.neighbor_profile.is_sample):
                continue
            if not member.circle.archived or member.circle.owner_id == request.user.pk:
                memberships.append(member)
    return render(request, 'support/home.html', {'memberships': memberships})


def register(request):
    if request.user.is_authenticated:
        return redirect('support_home')
    form = UserCreationForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect('support_home')
    return render(request, 'support/auth.html', {'form': form, 'registering': True})


@circle_login
def create(request):
    form = CircleForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            # Lock the account to serialize circle creation across requests.
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            if SupportCircle.objects.filter(owner=request.user).count() >= 3:
                form.add_error(None, 'You can create up to three circles in this demo.')
            else:
                circle = SupportCircle.objects.create(owner=request.user, **form.cleaned_data)
                SupportMember.objects.create(circle=circle, user=request.user, role='owner')
                event(circle, request.user, 'Created the circle')
                return redirect('support_circle', circle_id=circle.pk)
    return render(request, 'support/form.html', {'form': form, 'heading': 'Create a support circle', 'submit': 'Create circle'})


@circle_login
def board(request, circle_id):
    circle = get_object_or_404(SupportCircle, pk=circle_id)
    member = member_for(request, circle)
    selected = request.GET.get('filter', 'active')
    if selected not in ['active', 'open', 'mine', 'done', 'all']:
        selected = 'active'
    tasks = circle.tasks.filter(task_filter(member)).select_related('created_by', 'assignee', 'reward', 'care_record').order_by('due_at', '-created_at')
    if selected == 'active': tasks = tasks.exclude(status__in=['done', 'cancelled'])
    elif selected == 'open': tasks = tasks.filter(status='open')
    elif selected == 'mine': tasks = tasks.filter(assignee=request.user).exclude(status__in=['done', 'cancelled'])
    elif selected == 'done': tasks = tasks.filter(status='done')
    return render(request, 'support/board.html', {'circle': circle, 'member': member, 'tasks': tasks[:100],
        'selected': selected, 'activity': circle.activity.filter(Q(task__isnull=True) | Q(task__in=circle.tasks.filter(task_filter(member)))).select_related('actor').order_by('-created_at')[:20]})


@circle_login
def task_form(request, circle_id, task_id=None):
    circle = get_object_or_404(SupportCircle, pk=circle_id)
    member = member_for(request, circle)
    task = get_object_or_404(SupportTask, pk=task_id, circle=circle) if task_id else None
    if task:
        check_task_access(member, task)
    if member.role == 'neighbor' or (task and (task.status != 'open' or (circle.owner_id != request.user.pk and task.created_by_id != request.user.pk))):
        raise Http404
    with timezone.override(ZoneInfo(circle.timezone)):
        form = SupportTaskForm(request.POST if request.method == 'POST' else None, instance=task)
        if request.method == 'POST' and form.is_valid():
            with transaction.atomic():
                circle = SupportCircle.objects.select_for_update().get(pk=circle.pk)
                current_member = member_for(request, circle)
                if current_member.role == 'neighbor':
                    raise Http404
                if task:
                    check_task_access(current_member,task)
                if circle.tasks.count() >= 250 and task is None:
                    form.add_error(None, 'This circle has reached the demo limit of 250 tasks.')
                elif task and (not SupportTask.objects.filter(pk=task.pk, status='open').exists()):
                    form.add_error(None, 'This task has changed. Return to the circle to check its current status.')
                else:
                    saved = form.save(commit=False)
                    saved.circle = circle
                    if not task:
                        saved.created_by = request.user
                    saved.save()
                    event(circle, request.user, 'Updated a task' if task else 'Posted a task', saved)
                    return redirect('support_circle', circle_id=circle.pk)
        return render(request, 'support/form.html', {'circle': circle, 'form': form,
            'heading': 'Edit task' if task else 'Post a task', 'submit': 'Save task', 'task_form': True})


@circle_login
@require_POST
def task_action(request, circle_id, task_id):
    with transaction.atomic():
        circle = get_object_or_404(SupportCircle.objects.select_for_update(), pk=circle_id)
        current_member = member_for(request, circle)
        task = get_object_or_404(SupportTask.objects.select_for_update(), pk=task_id, circle=circle)
        check_task_access(current_member, task)
        action = request.POST.get('action')
        is_manager = request.user.pk in (circle.owner_id, task.created_by_id)
        if action == 'claim' and task.status == 'open' and task.assignee_id is None:
            task.assignee = request.user; task.status = 'claimed'; label = 'Volunteered for a task'
        elif action == 'release' and task.status == 'claimed' and task.assignee_id == request.user.pk:
            task.assignee = None; task.status = 'open'; label = 'Released a task'
        elif action == 'complete' and task.status == 'claimed' and task.assignee_id == request.user.pk:
            task.status = 'review'; label = 'Requested task completion'
        elif action == 'confirm' and task.status == 'review' and request.user.pk == circle.owner_id:
            task.status = 'done'; label = 'Confirmed task completion'
        elif action == 'cancel' and task.status in ['open', 'claimed', 'review'] and is_manager:
            task.status = 'cancelled'; task.assignee = None; label = 'Cancelled a task'
        else:
            messages.error(request, 'That action is unavailable. The task may have changed; check its current status below.')
            return redirect('support_circle', circle_id=circle.pk)
        task.save(update_fields=['status', 'assignee'])
        event(circle, request.user, label, task)
    return redirect('support_circle', circle_id=circle_id)


@circle_login
def invite(request, circle_id):
    circle = get_object_or_404(SupportCircle, pk=circle_id, owner=request.user, archived=False)
    form = InviteForm(request.POST if request.method == 'POST' else None)
    code = None
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            circle = SupportCircle.objects.select_for_update().get(pk=circle.pk)
            member_for(request, circle)
            if circle.invites.filter(created_at__gte=timezone.now()-timedelta(days=1)).count() >= 20:
                form.add_error(None, 'You can create up to 20 invitations per day.')
            else:
                code = secrets.token_urlsafe(24)
                SupportInvite.objects.create(circle=circle, role=form.cleaned_data['role'], care_permissions=form.permissions(),
                    token_hash=hashlib.sha256(code.encode()).hexdigest(), expires_at=timezone.now()+timedelta(hours=48))
                event(circle, request.user, 'Created a private invitation')
    return render(request, 'support/invite.html', {'circle': circle, 'form': form, 'code': code,
        'invites': circle.invites.filter(used_by=None, revoked=False, expires_at__gt=timezone.now()).order_by('-created_at')[:20]})


@circle_login
def join(request):
    form = JoinForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        digest = hashlib.sha256(form.cleaned_data['code'].encode()).hexdigest()
        found = SupportInvite.objects.filter(token_hash=digest).first()
        if not found:
            form.add_error('code', 'This invitation is invalid or unavailable.')
        else:
            with transaction.atomic():
                get_user_model().objects.select_for_update().get(pk=request.user.pk)
                # All circle writes lock the circle before any invite/member/task.
                circle = SupportCircle.objects.select_for_update().get(pk=found.circle_id)
                found = SupportInvite.objects.select_for_update().get(pk=found.pk)
                if found.revoked or found.used_by_id or found.expires_at <= timezone.now() or circle.archived:
                    form.add_error('code', 'This invitation is invalid or unavailable.')
                elif circle.members.filter(user=request.user, active=True).exists():
                    form.add_error(None, 'You already belong to this circle.')
                elif circle.members.filter(active=True).count() >= 12:
                    form.add_error(None, 'This circle has reached its limit of 12 members.')
                else:
                    profile = None
                    if found.role == 'neighbor':
                        identity = SupportNeighborIdentity.objects.filter(user=request.user).select_related('profile').first()
                        profile = identity.profile if identity else NeighborProfile.objects.filter(owner_token=owner_token(request), status='approved', is_sample=False).first()
                        if not profile or profile.status != 'approved' or profile.is_sample:
                            form.add_error(None, 'A coordinator-approved neighbor profile is required. Create or review your profile using this browser, then try again.')
                        elif SupportNeighborIdentity.objects.filter(profile=profile).exclude(user=request.user).exists():
                            form.add_error(None, 'This neighbor profile is already linked to another account.')
                        elif not identity:
                            # Lock the shared profile before binding it to one account.
                            profile = NeighborProfile.objects.select_for_update().get(pk=profile.pk)
                            if SupportNeighborIdentity.objects.filter(profile=profile).exists():
                                form.add_error(None, 'This neighbor profile is already linked to another account.')
                            else:
                                SupportNeighborIdentity.objects.create(user=request.user, profile=profile)
                    if not form.errors:
                        SupportMember.objects.update_or_create(circle=circle, user=request.user,
                            defaults={'active': True, 'role': found.role, 'neighbor_profile': profile, 'care_permissions': found.care_permissions})
                        found.used_by = request.user; found.save(update_fields=['used_by'])
                        event(circle, request.user, 'Joined the circle')
                        return redirect('support_circle', circle_id=circle.pk)
    return render(request, 'support/form.html', {'form': form, 'heading': 'Join a support circle', 'submit': 'Join circle', 'joining': True})


@circle_login
def members(request, circle_id):
    circle = get_object_or_404(SupportCircle, pk=circle_id)
    member = member_for(request, circle)
    return render(request, 'support/members.html', {'circle': circle, 'member': member,
        'members': circle.members.filter(active=True).select_related('user', 'neighbor_profile')})


def remove_member(circle, membership, actor):
    membership.active = False; membership.save(update_fields=['active'])
    circle.care_changes.filter(author=membership.user,status='pending').update(status='rejected',reviewed_by=actor)
    circle.tasks.filter(assignee=membership.user, status__in=['claimed', 'review']).update(status='open', assignee=None)
    event(circle, actor, 'Left the circle' if membership.user_id == actor.pk else 'Removed a circle member')


@circle_login
@require_POST
def member_action(request, circle_id, member_id):
    with transaction.atomic():
        circle = get_object_or_404(SupportCircle.objects.select_for_update(), pk=circle_id)
        member_for(request, circle)
        target = get_object_or_404(SupportMember, pk=member_id, circle=circle, active=True)
        if target.user_id == circle.owner_id or (request.user.pk != circle.owner_id and target.user_id != request.user.pk):
            raise Http404
        remove_member(circle, target, request.user)
    return redirect('support_home' if target.user_id == request.user.pk else 'support_members', **({} if target.user_id == request.user.pk else {'circle_id': circle_id}))


@circle_login
@require_POST
def revoke_invite(request, circle_id, invite_id):
    with transaction.atomic():
        circle = get_object_or_404(SupportCircle.objects.select_for_update(), pk=circle_id, owner=request.user, archived=False)
        found = get_object_or_404(SupportInvite, pk=invite_id, circle=circle)
        found.revoked = True; found.save(update_fields=['revoked'])
        event(circle, request.user, 'Revoked a private invitation')
    return redirect('support_invite', circle_id=circle_id)


@circle_login
@require_POST
def archive(request, circle_id):
    with transaction.atomic():
        circle = get_object_or_404(SupportCircle.objects.select_for_update(), pk=circle_id, owner=request.user)
        action = request.POST.get('action')
        if action not in ['archive', 'restore']:
            return HttpResponseBadRequest('Choose archive or restore.')
        circle.archived = action == 'archive'; circle.save(update_fields=['archived'])
        if circle.archived:
            circle.care_changes.filter(status='pending').update(status='rejected',reviewed_by=request.user)
            circle.invites.filter(used_by=None).update(revoked=True)
        event(circle, request.user, 'Archived the circle' if circle.archived else 'Restored the circle')
    return redirect('support_home')


@circle_login
def request_reward(request, circle_id, task_id):
    from . import rewards
    from .models import VolunteerReward
    from .support_forms import SupportRewardForm
    circle = get_object_or_404(SupportCircle, pk=circle_id)
    member_for(request, circle)
    task = get_object_or_404(SupportTask, pk=task_id, circle=circle, assignee=request.user, status='done')
    check_task_access(member_for(request,circle),task)
    existing = VolunteerReward.objects.filter(support_task=task).first()
    if existing:
        return redirect('reward_receipt', public_id=existing.public_id)
    form = SupportRewardForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            circle = SupportCircle.objects.select_for_update().get(pk=circle.pk)
            member_for(request, circle)
            task = SupportTask.objects.select_for_update().get(pk=task.pk)
            if not rewards.support_task_eligible(task):
                form.add_error(None, 'This task is no longer eligible for a reward.')
            elif form.cleaned_data['volunteer_wallet'].lower() == rewards.deployment()['contract'].lower():
                form.add_error('volunteer_wallet', 'Use your wallet, not the fund address.')
            else:
                reward, _ = VolunteerReward.objects.get_or_create(support_task=task, defaults={
                    'volunteer_wallet': form.cleaned_data['volunteer_wallet'], 'status': 'requested'})
                event(circle, request.user, 'Requested a test-network reward', task)
                return redirect('reward_receipt', public_id=reward.public_id)
    return render(request, 'support/form.html', {'circle': circle, 'form': form, 'heading': 'Request a volunteer reward',
        'submit': 'Send reward request', 'reward_form': True})
