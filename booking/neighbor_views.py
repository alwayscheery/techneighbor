from urllib.parse import urlencode
from django.contrib import messages
from django.db import IntegrityError
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from datetime import timedelta
from .models import NeighborArea, NeighborProfile, NeighborIntroduction
from .neighbor_forms import NeighborProfileForm, NeighborIntroductionForm, NeighborAreaForm, MapsSetupForm
from .community_views import owner_token, no_store, moderation_source
from .views import staff_required
from .integrations import maps_settings, write_private


def google_search(query):
    return 'https://www.google.com/maps/search/?' + urlencode({'api': 1, 'query': query})


def directory(request):
    areas = list(NeighborArea.objects.annotate(count=Count('neighbors', filter=Q(neighbors__status='approved'))))
    selected = next((a for a in areas if a.slug == request.GET.get('area')), None)
    interest = request.GET.get('interest', '')
    interests = dict(NeighborProfile._meta.get_field('interest').choices)
    if interest not in interests:
        interest = ''
    people = NeighborProfile.objects.filter(status='approved').select_related('area').order_by('is_sample', 'nickname')
    if selected:
        people = people.filter(area=selected)
    if interest:
        people = people.filter(interest=interest)
    people = list(people[:100])
    counts = {}
    for person in people:
        counts[person.area_id] = counts.get(person.area_id, 0) + 1
    points = [{'lat': a.latitude, 'lng': a.longitude, 'label': a.name, 'count': counts[a.pk], 'slug': a.slug} for a in areas if counts.get(a.pk)]
    for area in areas:
        area.maps_url = google_search(area.name)
    config = maps_settings()
    return no_store(render(request, 'neighbors/directory.html', {
        'areas': areas, 'people': people, 'selected': selected, 'interest': interest,
        'interests': interests.items(), 'own_profile': NeighborProfile.objects.filter(owner_token=owner_token(request)).first(),
        'maps_url': google_search(selected.name if selected else 'community centers'),
        'meeting_url': google_search('libraries and community centers in ' + selected.name) if selected else None,
        'map_config': {'key': config['api_key'], 'mapId': config['map_id'], 'points': points,
                       'center': {'lat': selected.latitude, 'lng': selected.longitude} if selected else None},
        'maps_connected': bool(config['api_key']),
    }))


def close_introductions(profile, alias='default'):
    # Separate indexed updates also work around SQLite planners that reject OR
    # updates involving the conditional unique index on pending requests.
    pending = NeighborIntroduction.objects.using(alias).filter(status='pending')
    pending.filter(requester_id=profile.pk).update(status='closed')
    pending.filter(neighbor_id=profile.pk).update(status='closed')


def my_profile(request):
    profile = NeighborProfile.objects.filter(owner_token=owner_token(request)).first()
    form = NeighborProfileForm(request.POST if request.method == 'POST' else None, instance=profile)
    if request.method == 'POST':
        if request.POST.get('action') == 'withdraw' and profile:
            profile.status = 'hidden'
            profile.save(update_fields=['status', 'updated_at'])
            close_introductions(profile)
            messages.success(request, 'Your profile is no longer listed. Pending introductions have been closed.')
            return redirect('neighbor_profile')
        if form.is_valid():
            if not profile and NeighborProfile.objects.count() >= 1000:
                form.add_error(None, 'This demo directory is full. Please contact the coordinator.')
            else:
                profile = form.save(commit=False)
                profile.owner_token = owner_token(request)
                profile.status = 'pending'
                profile.is_sample = False
                profile.save()
                messages.success(request, 'Your profile is saved for coordinator review. It is not publicly listed until approved.')
                return redirect('neighbor_profile')
    return no_store(render(request, 'neighbors/profile.html', {'form': form, 'profile': profile}))


def introduce(request, neighbor_id):
    neighbor = get_object_or_404(NeighborProfile.objects.select_related('area'), pk=neighbor_id, status='approved', is_sample=False)
    own = NeighborProfile.objects.filter(owner_token=owner_token(request), status='approved', is_sample=False).first()
    if not own:
        messages.info(request, 'Create a profile and wait for coordinator approval before requesting an introduction.')
        return redirect('neighbor_profile')
    if own.pk == neighbor.pk:
        return HttpResponseBadRequest('Choose another neighbor.')
    existing = NeighborIntroduction.objects.filter(requester=own, neighbor=neighbor, status='pending').first()
    form = NeighborIntroductionForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and not existing and form.is_valid():
        if NeighborIntroduction.objects.filter(requester=own, created_at__gte=timezone.now()-timedelta(days=1)).count() >= 3:
            form.add_error(None, 'You have requested three introductions today. Please wait for the coordinator.')
        else:
            try:
                existing = NeighborIntroduction.objects.create(requester=own, neighbor=neighbor, **{k: form.cleaned_data[k] for k in ['contact', 'note']})
            except IntegrityError:
                existing = NeighborIntroduction.objects.get(requester=own, neighbor=neighbor, status='pending')
            messages.success(request, 'Introduction requested. The coordinator will review it; no message has been sent automatically.')
            return redirect('neighbor_introduce', neighbor_id=neighbor.pk)
    return no_store(render(request, 'neighbors/introduce.html', {'neighbor': neighbor, 'form': form, 'existing': existing,
        'meeting_url': google_search('libraries and community centers in ' + neighbor.area.name)}))


@staff_required
def moderate(request):
    alias, source = moderation_source(request)
    area_form = NeighborAreaForm(request.POST if request.method == 'POST' and request.POST.get('action') == 'area' else None)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action in ('approve', 'hide'):
            profile = get_object_or_404(NeighborProfile.objects.using(alias), pk=request.POST.get('profile_id'))
            if action == 'approve' and profile.status != 'pending':
                return HttpResponseBadRequest('Only profiles awaiting review can be approved.')
            profile.status = 'approved' if action == 'approve' else 'hidden'
            profile.save(using=alias, update_fields=['status', 'updated_at'])
            if action == 'hide':
                close_introductions(profile, alias)
        elif action in ('arranged', 'closed'):
            intro = get_object_or_404(NeighborIntroduction.objects.using(alias), pk=request.POST.get('introduction_id'))
            intro.status = action
            intro.save(using=alias, update_fields=['status'])
        elif action == 'area' and area_form.is_valid():
            data = area_form.cleaned_data
            NeighborArea.objects.using(alias).update_or_create(slug=data['slug'], defaults={k: data[k] for k in ['name', 'latitude', 'longitude']})
        elif action != 'area':
            return HttpResponseBadRequest('Unknown action.')
        if not area_form.errors:
            messages.success(request, 'Community directory updated.')
            return redirect('/coordinator/neighbors/?' + urlencode({'source': source}))
    return no_store(render(request, 'neighbors/moderate.html', {
        'source': source, 'area_form': area_form,
        'profiles': NeighborProfile.objects.using(alias).filter(status__in=['pending', 'approved']).select_related('area').order_by('status', 'nickname'),
        'introductions': NeighborIntroduction.objects.using(alias).filter(status='pending').select_related('requester__area', 'neighbor__area'),
    }))


@staff_required
def maps_setup(request):
    form = MapsSetupForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if request.POST.get('action') == 'disconnect':
            write_private('maps.json', {})
            messages.success(request, 'Saved Maps configuration removed. Environment settings, if any, still apply.')
            return redirect('neighbor_maps_setup')
        if form.is_valid():
            write_private('maps.json', {k: form.cleaned_data[k] for k in ['api_key', 'map_id']})
            messages.success(request, 'Maps settings saved. Open Nearby neighbors and choose Load Google map to test.')
            return redirect('neighbor_maps_setup')
    return no_store(render(request, 'neighbors/maps_setup.html', {'form': form, 'connected': bool(maps_settings()['api_key'])}))
