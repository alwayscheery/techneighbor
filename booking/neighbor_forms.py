from django import forms
from .models import NeighborArea, NeighborProfile, NeighborIntroduction


class NeighborProfileForm(forms.ModelForm):
    permission = forms.BooleanField(label='I agree to share my nickname, general area, interest, and introduction publicly after coordinator approval. I have left out home addresses and contact details.')

    class Meta:
        model = NeighborProfile
        fields = ['nickname', 'area', 'interest', 'about']
        labels = {'nickname': 'First name or nickname', 'area': 'Your general area', 'interest': 'What would you enjoy?', 'about': 'A little introduction'}
        widgets = {'about': forms.Textarea(attrs={'rows': 3})}
        help_texts = {'area': 'Only a city or neighborhood center is shown. No home address or live location.', 'about': 'Share an interest. Keep phone numbers, email, and addresses out of this public introduction.'}


class NeighborIntroductionForm(forms.ModelForm):
    permission = forms.BooleanField(label='I agree that the coordinator may use these private details to help arrange an introduction. No message is sent automatically.')

    class Meta:
        model = NeighborIntroduction
        fields = ['contact', 'note']
        labels = {'contact': 'How can the coordinator reach you?', 'note': 'A note for the coordinator (optional)'}
        help_texts = {'contact': 'Your phone or email is visible only to the coordinator and you.'}
        widgets = {'note': forms.Textarea(attrs={'rows': 3})}


class NeighborAreaForm(forms.Form):
    slug = forms.SlugField(max_length=50)
    name = forms.CharField(max_length=100, help_text='Use a city or broad neighborhood, never a home address.')
    latitude = forms.FloatField(min_value=-85, max_value=85, help_text='Public area center only. Do not enter a resident’s coordinates.')
    longitude = forms.FloatField(min_value=-180, max_value=180)


class MapsSetupForm(forms.Form):
    api_key = forms.RegexField(regex=r'^[A-Za-z0-9_-]{20,150}$', label='Google Maps browser API key', widget=forms.PasswordInput(render_value=False, attrs={'autocomplete': 'new-password'}))
    map_id = forms.RegexField(regex=r'^[A-Za-z0-9_-]{1,150}$', required=False, label='Map ID (optional for testing)')
    restricted = forms.BooleanField(label='I have restricted this browser key to our website addresses and the Maps JavaScript API, and checked billing and usage limits in Google Cloud.')
