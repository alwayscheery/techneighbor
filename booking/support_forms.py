from django import forms
from .models import SupportTask

TIMEZONES = [('America/New_York', 'Eastern'), ('America/Chicago', 'Central'),
    ('America/Denver', 'Mountain'), ('America/Phoenix', 'Arizona'),
    ('America/Los_Angeles', 'Pacific'), ('America/Anchorage', 'Alaska'), ('Pacific/Honolulu', 'Hawaii')]


class CircleForm(forms.Form):
    name = forms.CharField(max_length=80, label='Circle name', help_text='For example, Family and friends. Avoid full names or private health details.')
    timezone = forms.ChoiceField(choices=TIMEZONES, initial='America/Chicago', label='Time zone for this circle')


class InviteForm(forms.Form):
    role = forms.ChoiceField(choices=[('family', 'Family member'), ('neighbor', 'Approved neighbor')], label='Who are you inviting?')


class JoinForm(forms.Form):
    code = forms.RegexField(regex=r'^[A-Za-z0-9_-]{32}$', max_length=32, label='Private invitation code',
        widget=forms.TextInput(attrs={'autocomplete': 'off', 'spellcheck': 'false'}),
        error_messages={'invalid': 'Enter the complete 32-character invitation code.'})
    consent = forms.BooleanField(label='I understand that my username and my task activity will be shared with the members of this circle.')


class SupportTaskForm(forms.ModelForm):
    due_at = forms.DateTimeField(required=False, label='When is help needed? (optional)',
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
        input_formats=['%Y-%m-%dT%H:%M'])

    class Meta:
        model = SupportTask
        fields = ['title', 'category', 'details', 'due_at']
        labels = {'title': 'What help is needed?', 'details': 'Helpful details (optional)'}
        widgets = {'details': forms.Textarea(attrs={'rows': 4})}
        help_texts = {'details': 'Keep passwords, medical records, and home addresses out of task notes. Arrange meeting details privately.'}


class SupportRewardForm(forms.Form):
    volunteer_wallet = forms.CharField(max_length=42, label='Your public wallet address', help_text='An EVM wallet starting with 0x. This address will be public on Arc Testnet.')
    consent = forms.BooleanField(label='I agree to publish my wallet address and payment receipt for a 2-test-USDC reward. I understand these tokens have no cash value.')

    def clean_volunteer_wallet(self):
        from web3 import Web3
        from .blockchain import ZERO_ADDRESS
        value = self.cleaned_data['volunteer_wallet'].strip()
        if not Web3.is_address(value) or value.lower() == ZERO_ADDRESS.lower():
            raise forms.ValidationError('Enter a valid, non-zero public wallet address.')
        return Web3.to_checksum_address(value)
