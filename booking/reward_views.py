from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from web3 import Web3

from . import blockchain, rewards
from .models import Booking, VolunteerReward
from .views import staff_required


class RewardApprovalForm(forms.Form):
    volunteer_wallet = forms.CharField(max_length=42, label='Volunteer’s public wallet address',
        help_text='Starts with 0x. The address and reward will be public on Arc Testnet.')
    agreed = forms.BooleanField(label='I confirm the volunteer completed this session and agreed to receive a public test-network reward.')

    def clean_volunteer_wallet(self):
        value = self.cleaned_data['volunteer_wallet'].strip()
        if not Web3.is_address(value) or value.lower() == blockchain.ZERO_ADDRESS.lower():
            raise forms.ValidationError('Enter a valid, non-zero public wallet address.')
        return Web3.to_checksum_address(value)


def private_response(response):
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'same-origin'
    return response


def community_fund(request):
    snapshot = rewards.fund_snapshot()
    recent = VolunteerReward.objects.filter(status='paid').order_by('-approved_at')[:20]
    return private_response(render(request, 'rewards/fund.html', {
        'fund': snapshot, 'recent_rewards': recent, 'explorer': blockchain.EXPLORER,
    }))


@staff_required
def approve(request, reference):
    booking = get_object_or_404(Booking, reference=reference)
    existing = VolunteerReward.objects.filter(booking=booking).first()
    if existing:
        return redirect('reward_receipt', public_id=existing.public_id)
    if booking.status != Booking.Status.COMPLETED:
        messages.error(request, 'Mark this session completed before approving a volunteer reward.')
        return redirect('dashboard')
    form = RewardApprovalForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            reward = rewards.approve_reward(booking, form.cleaned_data['volunteer_wallet'], request.user)
        except blockchain.ChainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, 'Reward approved. Review the recipient below, then choose Send test reward.')
            return redirect('reward_receipt', public_id=reward.public_id)
    return private_response(render(request, 'rewards/approve.html', {'booking': booking, 'form': form}))


def receipt(request, public_id):
    reward = get_object_or_404(VolunteerReward, public_id=public_id)
    result = rewards.check_reward(reward)
    connected = False
    if request.user.is_staff:
        try:
            rewards.signing_account()
            connected = True
        except blockchain.ChainError:
            pass
    # Never pass the private booking, approver, raw signed transaction, or name to public templates.
    public = {'public_id': reward.public_id, 'wallet': reward.volunteer_wallet,
              'transaction_hash': reward.transaction_hash, 'chain_uid': reward.chain_uid}
    return private_response(render(request, 'rewards/receipt.html', {
        'reward': public, 'result': result, 'signer_connected': connected,
        'explorer': blockchain.EXPLORER,
    }))


@staff_required
@require_POST
def pay(request, public_id):
    reward = get_object_or_404(VolunteerReward, public_id=public_id)
    try:
        rewards.pay_reward(reward)
        messages.info(request, 'The payment was checked. See its current blockchain status below.')
    except blockchain.ChainError as exc:
        messages.error(request, str(exc))
    except Exception:
        messages.error(request, 'Payment could not be confirmed. Check the receipt before retrying; a saved transaction is reused to prevent duplicate payment.')
    return redirect('reward_receipt', public_id=public_id)


@staff_required
def support_reward_queue(request):
    # The coordinator sees payment requests, never private task/circle content.
    pending = VolunteerReward.objects.filter(support_task__isnull=False, status='requested').order_by('approved_at')[:100]
    return private_response(render(request, 'rewards/requests.html', {'pending': pending}))


@staff_required
@require_POST
def approve_support_reward(request, public_id):
    from django.db import transaction
    with transaction.atomic():
        reward = get_object_or_404(VolunteerReward.objects.select_for_update(), public_id=public_id, support_task__isnull=False)
        if reward.status == 'requested' and rewards.support_task_eligible(reward.support_task):
            reward.status = 'approved'; reward.approved_by = request.user
            reward.save(update_fields=['status', 'approved_by'])
            messages.success(request, 'The 2-test-USDC reward is approved. Review the receipt before sending.')
        else:
            messages.error(request, 'This request is already handled or the task is no longer eligible.')
    return redirect('reward_receipt', public_id=public_id)
