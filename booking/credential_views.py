import re
from django import forms
from django.contrib import messages
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from web3 import Web3

from . import blockchain
from .integrations import elevenlabs_settings, write_private
from .models import Booking, ServiceCredential
from .views import staff_required
from .voice import PROMPTS, VoiceError, audio_for


class IssueForm(forms.Form):
    volunteer_alias = forms.CharField(max_length=80, label='Volunteer name or alias', help_text='Kept private in this app.')
    volunteer_wallet = forms.CharField(max_length=42, label='Volunteer’s public wallet address', help_text='An EVM-compatible address, starting with 0x. This will be public on Arc Testnet.')
    approved = forms.BooleanField(label='I confirm this volunteer completed the session and has agreed to a public service credential.')

    def clean_volunteer_wallet(self):
        value = self.cleaned_data['volunteer_wallet'].strip()
        if not Web3.is_address(value) or value.lower() == blockchain.ZERO_ADDRESS.lower():
            raise forms.ValidationError('Enter a valid, non-zero EVM wallet address.')
        return Web3.to_checksum_address(value)


class VoiceSetupForm(forms.Form):
    api_key = forms.CharField(max_length=300, required=False, label='Voice service API key', widget=forms.PasswordInput(render_value=False, attrs={'autocomplete': 'new-password'}))
    voice_id = forms.RegexField(regex=r'^[A-Za-z0-9_-]{10,80}$', max_length=80, label='Voice ID')


@staff_required
def integration_setup(request):
    voice_config = elevenlabs_settings()
    form = VoiceSetupForm(initial={'voice_id': voice_config['voice_id']})
    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'wallet':
                blockchain.create_wallet()
                messages.success(request, 'Created an organization wallet for Arc Testnet only. Its private key stays on this computer.')
            elif action == 'deploy':
                address = blockchain.deploy()
                messages.success(request, 'Arc Testnet registry confirmed at ' + address)
            elif action == 'voice':
                form = VoiceSetupForm(request.POST)
                if form.is_valid():
                    write_private('elevenlabs.json', {
                        'api_key': form.cleaned_data['api_key'] or voice_config['api_key'],
                        'voice_id': form.cleaned_data['voice_id'],
                    })
                    messages.success(request, 'Voice settings saved privately. Use Test spoken guide below to check the connection.')
                else:
                    return render(request, 'integration_setup.html', {'form': form, 'chain': blockchain.status(), 'voice_connected': bool(voice_config['api_key'])})
            else:
                return HttpResponse('Unknown action', status=400)
        except blockchain.ChainError as exc:
            messages.error(request, str(exc))
        except Exception:
            messages.error(request, 'The Arc Testnet action could not be completed. Check the connection and test wallet funding, then retry.')
        return redirect('integration_setup')
    response = render(request, 'integration_setup.html', {'form': form, 'chain': blockchain.status(), 'voice_connected': bool(voice_config['api_key'])})
    response['Cache-Control'] = 'no-store'
    return response


@staff_required
def issue_credential(request, reference):
    booking = get_object_or_404(Booking, reference=reference)
    existing = ServiceCredential.objects.filter(booking=booking).first()
    if existing:
        if request.method == 'POST' and existing.status == 'pending':
            try:
                blockchain.issue(booking, existing.volunteer_alias, existing.volunteer_wallet)
            except blockchain.ChainError as exc:
                messages.error(request, str(exc))
            except Exception:
                messages.error(request, 'Arc Testnet could not be reached. The saved transaction will not be duplicated.')
        return redirect('verify_credential', public_id=existing.public_id)
    if booking.status != Booking.Status.COMPLETED:
        messages.error(request, 'Confirm session completion before issuing a service credential.')
        return redirect('dashboard')
    form = IssueForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            credential = blockchain.issue(booking, form.cleaned_data['volunteer_alias'], form.cleaned_data['volunteer_wallet'])
        except blockchain.ChainError as exc:
            form.add_error(None, str(exc))
        except Exception:
            form.add_error(None, 'The blockchain action could not be completed. Check Integration setup and try again. If a transaction was submitted, its saved proof will show its status.')
        else:
            return redirect('verify_credential', public_id=credential.public_id)
    response = render(request, 'issue_credential.html', {'booking': booking, 'form': form})
    response['Cache-Control'] = 'no-store'
    return response


def verify_credential(request, public_id):
    credential = get_object_or_404(ServiceCredential, public_id=public_id)
    result = blockchain.verify(credential)
    response = render(request, 'verify_credential.html', {
        'credential': credential, 'result': result,
        'proof': blockchain.public_proof(credential), 'explorer': blockchain.EXPLORER,
    })
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response


def credential_proof(request, public_id):
    credential = get_object_or_404(ServiceCredential, public_id=public_id)
    result = blockchain.verify(credential)
    data = blockchain.public_proof(credential)
    data['verification'] = result
    response = JsonResponse(data)
    response['Content-Disposition'] = f'attachment; filename="service-credential-{public_id}.json"'
    response['Cache-Control'] = 'no-store'
    return response


@staff_required
@require_POST
def revoke_credential(request, public_id):
    credential = get_object_or_404(ServiceCredential, public_id=public_id)
    try:
        blockchain.revoke(credential)
        messages.info(request, 'Revocation submitted. Check the live verification status below.')
    except blockchain.ChainError as exc:
        messages.error(request, str(exc))
    except Exception:
        messages.error(request, 'Revocation could not be confirmed. Check the current blockchain status before relying on this credential.')
    return redirect('verify_credential', public_id=public_id)


@require_POST
def voice_audio(request):
    prompt = request.POST.get('prompt', '')
    if prompt not in PROMPTS:
        return JsonResponse({'error': 'Unknown guide step.'}, status=400)
    if not request.session.session_key:
        request.session.create()
    key = 'voice-limit:' + request.session.session_key
    count = cache.get(key, 0)
    if count >= 40:
        return JsonResponse({'error': 'Please take a short break from requesting new audio. The written guide remains available.'}, status=429)
    cache.set(key, count + 1, 3600)
    try:
        audio = audio_for(prompt)
    except VoiceError as exc:
        return JsonResponse({'error': str(exc)}, status=503)
    response = HttpResponse(audio, content_type='audio/mpeg')
    response['Cache-Control'] = 'private, max-age=3600'
    return response
