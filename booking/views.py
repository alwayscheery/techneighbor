from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db import IntegrityError, transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from .forms import BookingForm, available_slots
from .models import Booking, SUPPORT_CATEGORIES, TOPIC_CATEGORY

staff_required = user_passes_test(lambda user: user.is_active and user.is_staff)

def home(request):
    return render(request, 'home.html', {'next_slot': available_slots().first(), 'categories': SUPPORT_CATEGORIES})

def book(request):
    # Derive the category from legacy topic links and direct POSTs as well as category links.
    requested_topic = request.POST.get('topic') if request.method == 'POST' else request.GET.get('topic')
    selected_category = request.POST.get('category') if request.method == 'POST' else request.GET.get('category')
    if selected_category not in SUPPORT_CATEGORIES:
        selected_category = TOPIC_CATEGORY.get(requested_topic, 'technology')
    category = SUPPORT_CATEGORIES[selected_category]
    initial_topic = requested_topic if requested_topic in dict(category['topics']) else category['topics'][0][0]
    form = BookingForm(request.POST if request.method == 'POST' else None, category=selected_category,
                       initial={'topic': initial_topic, 'booking_for': 'self'})
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                booking = Booking.objects.create(**form.cleaned_data)
        except IntegrityError:
            form.add_error('slot', 'Someone just booked that session. Please choose another time.')
        else:
            return redirect('confirmation', reference=booking.reference)
    return render(request, 'book.html', {
        'form': form, 'slots': list(form.fields['slot'].queryset),
        'categories': SUPPORT_CATEGORIES, 'selected_category': selected_category, 'category': category,
    })

def confirmation(request, reference):
    booking = get_object_or_404(Booking.objects.select_related('slot'), reference=reference)
    response = render(request, 'confirmation.html', {'booking': booking})
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'same-origin'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response

@require_POST
def cancel_booking(request, reference):
    booking = get_object_or_404(Booking, reference=reference)
    changed = Booking.objects.filter(pk=booking.pk, status=Booking.Status.BOOKED).update(status=Booking.Status.CANCELLED)
    if changed:
        messages.success(request, 'Your session has been cancelled. You can choose a new time whenever you are ready.')
    return redirect('confirmation', reference=reference)

@staff_required
def dashboard(request):
    selected = request.GET.get('status', 'booked')
    if selected not in ('booked', 'completed', 'cancelled', 'all'):
        selected = 'booked'
    bookings = Booking.objects.select_related('slot', 'credential', 'reward')
    counts = {status: bookings.filter(status=status).count() for status in ('booked', 'completed', 'cancelled')}
    selected_category = request.GET.get('category', 'all')
    if selected_category in SUPPORT_CATEGORIES:
        bookings = bookings.filter(topic__in=[key for key, label in SUPPORT_CATEGORIES[selected_category]['topics']])
    else:
        selected_category = 'all'
    if selected != 'all':
        bookings = bookings.filter(status=selected)
    response = render(request, 'dashboard.html', {
        'bookings': bookings, 'selected': selected, 'counts': counts,
        'categories': SUPPORT_CATEGORIES, 'selected_category': selected_category,
    })
    response['Cache-Control'] = 'no-store'
    return response

@staff_required
@require_POST
def update_booking(request, reference):
    booking = get_object_or_404(Booking, reference=reference)
    action = request.POST.get('action')
    if action not in ('complete', 'cancel'):
        return HttpResponseBadRequest('Unknown action')
    status = Booking.Status.COMPLETED if action == 'complete' else Booking.Status.CANCELLED
    changed = Booking.objects.filter(pk=booking.pk, status=Booking.Status.BOOKED).update(
        status=status, completed_at=timezone.now() if action == 'complete' else None,
    )
    if changed:
        messages.success(request, f'Session for {booking.name} marked {status}.')
    else:
        messages.info(request, 'That session has already been updated.')
    return redirect('dashboard')
