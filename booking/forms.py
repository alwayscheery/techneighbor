from django import forms
from django.utils import timezone
from .models import Booking, SessionSlot, TOPICS

def available_slots():
    return SessionSlot.objects.filter(starts_at__gt=timezone.now()).exclude(
        bookings__status__in=[Booking.Status.BOOKED, Booking.Status.COMPLETED]
    ).order_by('starts_at')

class BookingForm(forms.Form):
    topic = forms.ChoiceField(choices=TOPICS, label='What would you like help with?', widget=forms.RadioSelect)
    slot = forms.ModelChoiceField(queryset=SessionSlot.objects.none(), label='Choose a session', empty_label=None, widget=forms.RadioSelect)
    booking_for = forms.ChoiceField(choices=[('self', 'Myself'), ('someone', 'Someone else')], widget=forms.RadioSelect, initial='self', label='Who are you booking for?')
    name = forms.CharField(max_length=80, label='Name of the person attending', widget=forms.TextInput(attrs={'autocomplete': 'name', 'placeholder': 'For example, Maria'}))
    contact = forms.CharField(required=False, max_length=120, label='Phone or email (optional)', widget=forms.TextInput(attrs={'placeholder': 'So the coordinator can reach you'}))

    def __init__(self, *args, category=None, **kwargs):
        super().__init__(*args, **kwargs)
        if category:
            from .models import SUPPORT_CATEGORIES
            self.fields['topic'].choices = SUPPORT_CATEGORIES[category]['topics']
        self.fields['slot'].queryset = available_slots()
