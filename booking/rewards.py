"""Bounded Arc TESTNET rewards. The credential issuer key is never used here."""
import json
import os
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db import transaction
from eth_account import Account
from web3 import Web3

from . import blockchain
from .integrations import read_private, signer_lock
from .models import Booking, VolunteerReward, SupportMember

REWARD_AMOUNT = Decimal('2')
REWARD_WEI = 2 * 10**18


def artifact():
    return json.loads((Path(settings.BASE_DIR) / 'contracts/CommunityFund.json').read_text())


def deployment():
    try:
        config = json.loads((Path(settings.BASE_DIR) / 'contracts/reward-deployment.json').read_text())
    except FileNotFoundError:
        raise blockchain.ChainError('The community fund is not connected yet.')
    if config.get('chain_id') != blockchain.CHAIN_ID:
        raise blockchain.ChainError('Rewards must use Arc Testnet.')
    return config


def verified_contract(w3, config=None, block='latest'):
    config = config or deployment()
    if config.get('chain_id') != blockchain.CHAIN_ID:
        raise blockchain.ChainError('Rewards must use Arc Testnet.')
    compiled = artifact()
    address = Web3.to_checksum_address(config['contract'])
    if w3.eth.get_code(address, block_identifier=block).to_0x_hex().lower() != compiled['deployedBytecode'].lower():
        raise blockchain.ChainError('The community fund contract could not be verified.')
    contract = w3.eth.contract(address=address, abi=compiled['abi'])
    if (contract.functions.operator().call(block_identifier=block).lower() != config['operator'].lower()
            or contract.functions.owner().call(block_identifier=block).lower() != config['owner'].lower()
            or contract.functions.REWARD().call(block_identifier=block) != REWARD_WEI):
        raise blockchain.ChainError('The community fund configuration did not match.')
    return contract


def fund_snapshot():
    """All totals use the same current block; RPC failures never show a fake balance."""
    try:
        config = deployment()
        w3 = blockchain.client()
        block = w3.eth.block_number
        contract = verified_contract(w3, config, block)
        units = Decimal(10**18)
        return {'available': True, 'contract': config['contract'], 'block': block,
                'balance': Decimal(w3.eth.get_balance(config['contract'], block_identifier=block)) / units,
                'funded': Decimal(contract.functions.totalFunded().call(block_identifier=block)) / units,
                'rewarded': Decimal(contract.functions.totalRewarded().call(block_identifier=block)) / units,
                'count': contract.functions.rewardCount().call(block_identifier=block)}
    except Exception:
        return {'available': False, 'error': 'The live Arc Testnet balance is unavailable. Please try again shortly.'}


def signing_account():
    key = os.environ.get('ARC_REWARD_PRIVATE_KEY', '')
    if not key and not getattr(settings, 'HOSTED_APP', False):
        key = read_private('rewards.json').get('private_key', '')
    if not key:
        raise blockchain.ChainError('Payments are not connected on this server. Your approved reward is saved; no funds were sent.')
    try:
        account = Account.from_key(key)
    except Exception:
        raise blockchain.ChainError('The reward signing connection needs coordinator attention.')
    if account.address.lower() != deployment()['operator'].lower():
        raise blockchain.ChainError('The reward signer does not match the fund operator. No funds were sent.')
    return account


def approve_reward(booking, wallet, user):
    with transaction.atomic():
        locked = Booking.objects.select_for_update().get(pk=booking.pk)
        if locked.status != Booking.Status.COMPLETED:
            raise blockchain.ChainError('Confirm that the session is completed before approving a reward.')
        if not Web3.is_address(wallet) or wallet.lower() == blockchain.ZERO_ADDRESS.lower():
            raise blockchain.ChainError('Enter a valid, non-zero public wallet address.')
        wallet = Web3.to_checksum_address(wallet)
        if wallet.lower() == deployment()['contract'].lower():
            raise blockchain.ChainError('Use the volunteer’s wallet, not the community fund address.')
        reward, created = VolunteerReward.objects.get_or_create(booking=locked, defaults={
            'volunteer_wallet': wallet, 'approved_by': user,
        })
        if not created and reward.volunteer_wallet.lower() != wallet.lower():
            raise blockchain.ChainError('This session already has an approved recipient. It cannot be changed or paid twice.')
        return reward


def check_reward(reward):
    try:
        w3 = blockchain.client()
        block = w3.eth.block_number
        contract = verified_contract(w3, block=block)
        recipient, amount, paid_at = contract.functions.rewards(bytes.fromhex(reward.chain_uid[2:])).call(block_identifier=block)
        if paid_at:
            if recipient.lower() != reward.volunteer_wallet.lower() or amount != REWARD_WEI:
                raise blockchain.ChainError('The onchain receipt did not match this reward.')
            VolunteerReward.objects.filter(pk=reward.pk).update(status='paid')
            reward.status = 'paid'
            return {'state': 'paid', 'label': 'Verified payment on Arc Testnet', 'block': block}
        if reward.transaction_hash:
            receipt = blockchain.receipt_or_none(w3, reward.transaction_hash)
            if receipt is not None:
                if receipt['status'] == 0:
                    VolunteerReward.objects.filter(pk=reward.pk).update(status='failed')
                    reward.status = 'failed'
                    return {'state': 'failed', 'label': 'The transaction failed. No reward was paid.'}
                raise blockchain.ChainError('The confirmed transaction did not contain the expected reward.')
            return {'state': 'pending', 'label': 'Waiting for Arc Testnet confirmation'}
        if reward.status == 'requested':
            return {'state': 'requested', 'label': 'Awaiting coordinator approval · Not paid yet'}
        return {'state': 'approved', 'label': 'Approved by the coordinator · Not paid yet'}
    except Exception:
        return {'state': 'unknown', 'label': 'Could not verify payment right now. A saved status is not proof of payment.'}


def pay_reward(reward):
    """Persist the exact signed transaction before sending. Retries rebroadcast it."""
    with signer_lock():
        reward.refresh_from_db()
        if not reward.approved_by_id or not reward.approved_by.is_active or not reward.approved_by.is_staff:
            raise blockchain.ChainError('A coordinator must approve this reward before payment.')
        if reward.booking_id and reward.booking.status != Booking.Status.COMPLETED:
            raise blockchain.ChainError('Only a completed session can receive a reward.')
        if reward.support_task_id and not support_task_eligible(reward.support_task):
            raise blockchain.ChainError('The circle task must be confirmed complete and its volunteer must still be an eligible member.')
        account = signing_account()
        w3 = blockchain.client()
        contract = verified_contract(w3)
        uid = bytes.fromhex(reward.chain_uid[2:])
        recipient, amount, paid_at = contract.functions.rewards(uid).call()
        if paid_at:
            if recipient.lower() != reward.volunteer_wallet.lower() or amount != REWARD_WEI:
                raise blockchain.ChainError('The existing onchain receipt does not match.')
            VolunteerReward.objects.filter(pk=reward.pk).update(status='paid')
            return
        if not reward.transaction_hash:
            if reward.status != 'approved':
                raise blockchain.ChainError('This reward needs review before payment.')
            earlier = VolunteerReward.objects.filter(status='pending').exclude(pk=reward.pk).first()
            if earlier and check_reward(earlier)['state'] not in ('paid', 'failed'):
                raise blockchain.ChainError('An earlier reward is awaiting confirmation. Check its receipt before starting another payment.')
            if w3.eth.get_balance(contract.address) < REWARD_WEI:
                raise blockchain.ChainError('The community fund needs more free Arc Testnet USDC. Your approval is saved; no funds were sent.')
            tx_hash, raw = blockchain.sign_call(w3, account, contract.functions.payReward(uid, reward.volunteer_wallet))
            # The file lock serializes the single demo signer; commit before broadcast.
            reward.transaction_hash, reward.signed_transaction, reward.status = tx_hash, raw, 'pending'
            reward.save(update_fields=['transaction_hash', 'signed_transaction', 'status'])
        receipt = blockchain.receipt_or_none(w3, reward.transaction_hash)
        if receipt is None:
            blockchain.broadcast(w3, reward.signed_transaction, reward.transaction_hash)
            blockchain.receipt_or_none(w3, reward.transaction_hash, wait=True)
        check_reward(reward)


def support_task_eligible(task):
    if task.status != 'done' or not task.assignee_id or task.circle.archived:
        return False
    member = SupportMember.objects.filter(circle=task.circle, user_id=task.assignee_id, active=True).select_related('neighbor_profile').first()
    if member and task.care_record_id:
        from .care_access import access_level
        if task.care_record.archived or access_level(member,task.care_record.kind)=='none':
            return False
    return bool(member and (member.role != 'neighbor' or (member.neighbor_profile and
        member.neighbor_profile.status == 'approved' and not member.neighbor_profile.is_sample)))
