import secrets
import uuid
from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, F
from django.db.models.functions import Greatest
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST
from .community_forms import PhotoUploadForm, CommunityPostForm, AttendanceForm, PhotoReportForm
from .models import CommunityPost, CommunityAttendance, PhotoAlbum, CommunityPhoto, PhotoReport
from .views import staff_required


def owner_token(request):
    if not request.session.get('community_owner'):
        request.session['community_owner'] = secrets.token_hex(32)
    return request.session['community_owner']


def no_store(response):
    response['Cache-Control'] = 'private, no-store'
    response['Referrer-Policy'] = 'same-origin'
    return response


def hub(request):
    events = CommunityPost.objects.filter(published=True, kind='event', starts_at__gt=timezone.now()).order_by('starts_at')[:12]
    notices = CommunityPost.objects.filter(published=True, kind='notice').order_by('-created_at')[:6]
    joined = set(CommunityAttendance.objects.filter(owner_token=owner_token(request)).values_list('event_id', flat=True))
    for event in events:
        event.joined = event.pk in joined
    return no_store(render(request, 'community/hub.html', {'events': events, 'notices': notices}))


def event_detail(request, slug):
    event = get_object_or_404(CommunityPost, slug=slug, published=True, kind='event')
    attending = CommunityAttendance.objects.filter(event=event, owner_token=owner_token(request)).exists()
    return no_store(render(request, 'community/event.html', {
        'event': event, 'attending': attending, 'form': AttendanceForm(),
        'past': not event.starts_at or event.starts_at <= timezone.now(),
    }))


@require_POST
def event_attendance(request, slug):
    event = get_object_or_404(CommunityPost, slug=slug, published=True, kind='event')
    token = owner_token(request)
    if request.POST.get('action') == 'leave':
        with transaction.atomic():
            removed, _ = CommunityAttendance.objects.filter(event=event, owner_token=token).delete()
            if removed:
                CommunityPost.objects.filter(pk=event.pk).update(going_count=Greatest(F('going_count') - 1, 0))
        messages.success(request, 'Your place has been released. You can join another activity whenever you like.')
        return redirect('community_event', slug=slug)
    if request.POST.get('action') != 'join':
        return HttpResponseBadRequest('Unknown action')
    form = AttendanceForm(request.POST)
    if form.is_valid():
        try:
            with transaction.atomic():
                if CommunityAttendance.objects.filter(event=event, owner_token=token).exists():
                    messages.info(request, 'Your place is already saved on this device.')
                else:
                    reserved = CommunityPost.objects.filter(pk=event.pk, published=True,
                        starts_at__gt=timezone.now(), going_count__lt=F('capacity')).update(going_count=F('going_count') + 1)
                    if not reserved:
                        messages.error(request, 'This activity is full or has already started. Please choose another one.')
                    else:
                        CommunityAttendance.objects.create(event=event, owner_token=token, display_name=form.cleaned_data['display_name'])
                        messages.success(request, 'Your place is saved! Your name is visible only to the coordinator. This device remembers your RSVP.')
        except IntegrityError:
            messages.info(request, 'Your place is already saved on this device.')
        return redirect('community_event', slug=slug)
    return no_store(render(request, 'community/event.html', {'event': event, 'form': form,
        'attending': False, 'past': not event.starts_at or event.starts_at <= timezone.now()}))


def albums(request):
    token = owner_token(request)
    albums = PhotoAlbum.objects.annotate(shared_count=Count('photos', filter=Q(photos__status='approved'))).order_by('created_at')
    for album in albums:
        album.cover = album.photos.filter(status='approved').defer('image_data').first()
    own_pending = CommunityPhoto.objects.filter(owner_token=token, status='pending').defer('image_data').select_related('album')[:8]
    return no_store(render(request, 'community/albums.html', {'albums': albums, 'own_pending': own_pending}))


def album_detail(request, slug):
    album = get_object_or_404(PhotoAlbum, slug=slug)
    token = owner_token(request)
    photos = album.photos.filter(Q(status='approved') | Q(status='pending', owner_token=token)).defer('image_data')
    page = Paginator(photos, 24).get_page(request.GET.get('page'))
    return no_store(render(request, 'community/album.html', {'album': album, 'page': page}))


def upload_photo(request):
    initial_album = PhotoAlbum.objects.filter(slug=request.GET.get('album', '')).first()
    form = PhotoUploadForm(request.POST if request.method == 'POST' else None,
        request.FILES if request.method == 'POST' else None, initial={'album': initial_album})
    if request.method == 'POST':
        token = owner_token(request)
        valid = form.is_valid()
        if getattr(request, 'photo_upload_too_large', False):
            form.add_error('image', 'Please choose a photo smaller than 8 MB.')
            valid = False
        if valid:
            limit = 100 if getattr(settings, 'PUBLIC_PHONE_DEMO', False) else 1000
            if CommunityPhoto.objects.count() >= limit:
                form.add_error(None, 'This demo album has reached its photo limit. Please contact the coordinator.')
            elif CommunityPhoto.objects.filter(owner_token=token, status='pending').count() >= 10:
                form.add_error(None, 'You already have ten photos awaiting review. Please wait for the coordinator before adding more.')
            else:
                data = dict(form.cleaned_data)
                image = data.pop('image')
                data.pop('permission')
                photo = CommunityPhoto.objects.create(**data, owner_token=token,
                    image_data=image['data'], width=image['width'], height=image['height'])
                messages.success(request, 'Your photo is uploaded and awaiting review. Only you and the coordinator can see it until it is approved.')
                return redirect('community_photo', photo_id=photo.pk)
    return no_store(render(request, 'community/upload.html', {'form': form}))


def visible_photo(request, photo_id, include_data=False):
    query = CommunityPhoto.objects.select_related('album')
    if not include_data:
        query = query.defer('image_data')
    photo = get_object_or_404(query, pk=photo_id)
    own = secrets.compare_digest(photo.owner_token, owner_token(request))
    if photo.status != 'approved' and not own and not request.user.is_staff:
        raise Http404
    return photo, own


def photo_detail(request, photo_id):
    photo, own = visible_photo(request, photo_id)
    return no_store(render(request, 'community/photo.html', {
        'photo': photo, 'own': own, 'report_form': PhotoReportForm(),
    }))


def photo_image(request, photo_id):
    photo, own = visible_photo(request, photo_id, include_data=True)
    if photo.status == 'hidden':
        raise Http404
    response = no_store(HttpResponse(bytes(photo.image_data), content_type='image/jpeg'))
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Disposition'] = f'inline; filename="community-photo-{photo.pk}.jpg"'
    return response


@require_POST
def photo_action(request, photo_id):
    photo, own = visible_photo(request, photo_id)
    action = request.POST.get('action')
    if action == 'remove' and own:
        CommunityPhoto.objects.filter(pk=photo.pk).update(status='hidden')
        messages.success(request, 'Your photo has been removed from the shared album.')
        return redirect('community_albums')
    if action == 'report' and photo.status == 'approved':
        form = PhotoReportForm(request.POST)
        if form.is_valid():
            PhotoReport.objects.get_or_create(photo=photo, owner_token=owner_token(request), defaults={'reason': form.cleaned_data['reason']})
            messages.success(request, 'Thank you. The coordinator will review your concern.')
        else:
            messages.error(request, 'Please choose a reason for the report.')
        return redirect('community_photo', photo_id=photo.pk)
    return HttpResponseBadRequest('This action is not available.')


def moderation_source(request):
    source = request.POST.get('source') if request.method == 'POST' else request.GET.get('source', 'local')
    if source == 'phone' and not getattr(settings, 'PUBLIC_PHONE_DEMO', False) and 'phone_demo' in settings.DATABASES:
        return 'phone_demo', 'phone'
    return 'default', 'local'


@staff_required
def moderate_community(request):
    alias, source = moderation_source(request)
    form = CommunityPostForm()
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'publish':
            form = CommunityPostForm(request.POST)
            if form.is_valid():
                post = form.save(commit=False)
                post.slug = slugify(post.title)[:65] + '-' + uuid.uuid4().hex[:8]
                post.save(using=alias)
                messages.success(request, 'Your community post is published.')
                return redirect(reverse('community_moderation') + '?source=' + source)
        elif action in ('approve', 'hide'):
            photo = get_object_or_404(CommunityPhoto.objects.using(alias), pk=request.POST.get('photo_id'))
            photo.status = 'approved' if action == 'approve' else 'hidden'
            photo.reviewed_at = timezone.now()
            photo.save(using=alias, update_fields=['status', 'reviewed_at'])
            PhotoReport.objects.using(alias).filter(photo_id=photo.pk).update(resolved=True)
            messages.success(request, 'Photo approved and shared.' if action == 'approve' else 'Photo removed from the shared album.')
            return redirect(reverse('community_moderation') + '?source=' + source)
        else:
            return HttpResponseBadRequest('Unknown action')
    pending = CommunityPhoto.objects.using(alias).filter(status='pending').defer('image_data').select_related('album')
    reported = CommunityPhoto.objects.using(alias).filter(reports__resolved=False).distinct().defer('image_data').select_related('album')
    published = CommunityPost.objects.using(alias).filter(published=True).order_by('-created_at')[:8]
    return no_store(render(request, 'community/moderate.html', {
        'form': form, 'pending': pending, 'reported': reported, 'posts': published, 'source': source,
        'phone_available': 'phone_demo' in settings.DATABASES,
    }))


@staff_required
def moderation_image(request, photo_id):
    alias, source = moderation_source(request)
    photo = get_object_or_404(CommunityPhoto.objects.using(alias), pk=photo_id)
    response = no_store(HttpResponse(bytes(photo.image_data), content_type='image/jpeg'))
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def learn(request, lesson=None):
    lessons = {
        'video-calls': ('lesson_calls', 'Make a video call', 'Try a familiar calling app with someone you trust.'),
        'sharing-photos': ('lesson_photos', 'Share a photo', 'Take a moment to check who will receive your picture.'),
        'staying-safe': ('lesson_safety', 'Spot a suspicious message', 'Pause, check, and ask a trusted person for help.'),
    }
    if lesson is not None and lesson not in lessons:
        raise Http404
    selected = lessons.get(lesson)
    return no_store(render(request, 'learn.html', {'lessons': lessons.items(), 'selected': selected}))
