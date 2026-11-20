import json
import shutil
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from eth_account import Account
from eth_tester import EthereumTester, PyEVMBackend
from eth_tester.exceptions import TransactionFailed
from web3 import Web3, EthereumTesterProvider

from . import blockchain, rewards
from .integrations import write_private
from .models import Booking, SessionSlot, VolunteerReward

SOURCE = Path(settings.BASE_DIR)


@override_settings(ALLOWED_HOSTS=['testserver'])
class VolunteerRewardTests(TestCase):
    """Real Solidity runs in PyEVM; no test sends an external transaction."""
    def setUp(self):
        self.folder = TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        root=Path(self.folder.name); (root/'contracts').mkdir()
        shutil.copy(SOURCE/'contracts/CommunityFund.json', root/'contracts/CommunityFund.json')
        self.override=override_settings(BASE_DIR=root); self.override.enable(); self.addCleanup(self.override.disable)
        backend=PyEVMBackend(); self.w3=Web3(EthereumTesterProvider(EthereumTester(backend)))
        self.owner=self.w3.eth.accounts[0]; self.operator=Account.from_key(backend.account_keys[1].to_bytes())
        self.volunteer=self.w3.eth.accounts[2]
        compiled=rewards.artifact(); factory=self.w3.eth.contract(abi=compiled['abi'],bytecode=compiled['bytecode'])
        tx=factory.constructor(self.operator.address).transact({'from':self.owner})
        address=self.w3.eth.get_transaction_receipt(tx)['contractAddress']
        self.config={'contract':address,'operator':self.operator.address,'owner':self.owner,'chain_id':blockchain.CHAIN_ID}
        (root/'contracts/reward-deployment.json').write_text(json.dumps(self.config))
        write_private('rewards.json', {'private_key':self.operator.key.to_0x_hex()})
        self.contract=self.w3.eth.contract(address=address,abi=compiled['abi'])
        self.w3.eth.send_transaction({'from':self.owner,'to':address,'value':10*10**18})
        network=patch('booking.blockchain.client',return_value=self.w3); network.start(); self.addCleanup(network.stop)
        self.staff=get_user_model().objects.create_user('coordinator',is_staff=True)
        self.slot=SessionSlot.objects.create(starts_at=timezone.now()-timedelta(days=1))
        self.booking=Booking.objects.create(slot=self.slot,name='PRIVATE RESIDENT NAME',contact='secret@example.test',topic='video',status='completed')

    def approved(self):
        return rewards.approve_reward(self.booking,self.volunteer,self.staff)

    def test_real_payment_transfers_fixed_amount_and_retry_is_idempotent(self):
        reward=self.approved(); before=self.w3.eth.get_balance(self.volunteer)
        rewards.pay_reward(reward); reward.refresh_from_db()
        self.assertEqual(self.w3.eth.get_balance(self.volunteer)-before,2*10**18)
        self.assertEqual(rewards.check_reward(reward)['state'],'paid')
        nonce=self.w3.eth.get_transaction_count(self.operator.address)
        rewards.pay_reward(reward)
        self.assertEqual(self.w3.eth.get_transaction_count(self.operator.address),nonce)
        self.assertEqual(VolunteerReward.objects.count(),1)
        self.assertEqual(rewards.fund_snapshot()['balance'],8)

    def test_only_completed_sessions_and_locked_recipients(self):
        self.booking.status='booked'; self.booking.save()
        with self.assertRaises(blockchain.ChainError): self.approved()
        self.booking.status='completed'; self.booking.save()
        reward=self.approved()
        self.assertEqual(self.approved().pk,reward.pk)
        with self.assertRaises(blockchain.ChainError): rewards.approve_reward(self.booking,self.w3.eth.accounts[3],self.staff)
        for wallet in [blockchain.ZERO_ADDRESS,'wrong',self.contract.address]:
            with self.assertRaises(blockchain.ChainError): rewards.approve_reward(self.booking,wallet,self.staff)

    def test_contract_rejects_unauthorized_operator_duplicate_and_empty_fund(self):
        uid=bytes.fromhex('01'*32)
        with self.assertRaises(TransactionFailed): self.contract.functions.payReward(uid,self.volunteer).transact({'from':self.owner})
        self.contract.functions.payReward(uid,self.volunteer).transact({'from':self.operator.address})
        with self.assertRaises(TransactionFailed): self.contract.functions.payReward(uid,self.volunteer).transact({'from':self.operator.address})
        for n in range(2,6): self.contract.functions.payReward(bytes([n])*32,self.volunteer).transact({'from':self.operator.address})
        with self.assertRaises(TransactionFailed): self.contract.functions.payReward(bytes([9])*32,self.volunteer).transact({'from':self.operator.address})
        self.assertEqual(self.contract.functions.rewardCount().call(),5)

    def test_contract_enforces_ten_rewards_per_utc_day(self):
        self.w3.eth.send_transaction({'from':self.owner,'to':self.contract.address,'value':20*10**18})
        for n in range(1,11): self.contract.functions.payReward(bytes([n])*32,self.volunteer).transact({'from':self.operator.address})
        with self.assertRaises(TransactionFailed): self.contract.functions.payReward(bytes([11])*32,self.volunteer).transact({'from':self.operator.address})

    def test_saved_signed_transaction_survives_broadcast_outage(self):
        reward=self.approved()
        with patch('booking.blockchain.broadcast',side_effect=blockchain.ChainError('Network unavailable')):
            with self.assertRaises(blockchain.ChainError): rewards.pay_reward(reward)
        reward.refresh_from_db(); tx=reward.transaction_hash; raw=reward.signed_transaction
        self.assertEqual(reward.status,'pending'); self.assertTrue(raw)
        rewards.pay_reward(reward); reward.refresh_from_db()
        self.assertEqual(reward.transaction_hash,tx); self.assertEqual(reward.signed_transaction,raw)
        self.assertEqual(reward.status,'paid'); self.assertEqual(self.contract.functions.rewardCount().call(),1)

    def test_public_receipt_and_feed_never_reveal_private_booking_or_signed_payload(self):
        reward=self.approved(); rewards.pay_reward(reward); reward.refresh_from_db()
        for name,args in [('community_fund',[]),('reward_receipt',[reward.public_id])]:
            response=self.client.get(reverse(name,args=args))
            self.assertEqual(response.status_code,200)
            for private in [self.booking.name,self.booking.contact,str(self.booking.reference),reward.signed_transaction]:
                self.assertNotContains(response,private)
            self.assertEqual(response.headers['Cache-Control'],'no-store')

    def test_an_unbroadcast_reward_blocks_signing_a_second_nonce(self):
        first = self.approved()
        with patch('booking.blockchain.broadcast', side_effect=blockchain.ChainError('Offline')):
            with self.assertRaises(blockchain.ChainError):
                rewards.pay_reward(first)
        slot = SessionSlot.objects.create(starts_at=timezone.now()-timedelta(days=2))
        booking = Booking.objects.create(slot=slot, name='Another private resident', topic='video', status='completed')
        second = rewards.approve_reward(booking, self.volunteer, self.staff)
        with self.assertRaises(blockchain.ChainError):
            rewards.pay_reward(second)
        second.refresh_from_db()
        self.assertFalse(second.transaction_hash)
        rewards.pay_reward(first)
        rewards.pay_reward(second)
        self.assertEqual(self.contract.functions.rewardCount().call(), 2)

    def test_public_cannot_approve_or_pay_and_staff_requires_csrf_and_post(self):
        url=reverse('approve_reward',args=[self.booking.reference])
        self.assertEqual(self.client.post(url,{'volunteer_wallet':self.volunteer,'agreed':'on'}).status_code,302)
        self.assertEqual(VolunteerReward.objects.count(),0)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(url,{'volunteer_wallet':self.volunteer,'agreed':'on'}).status_code,302)
        reward=VolunteerReward.objects.get(); pay=reverse('pay_reward',args=[reward.public_id])
        self.assertEqual(self.client.get(pay).status_code,405)
        strict=Client(enforce_csrf_checks=True); strict.force_login(self.staff)
        self.assertEqual(strict.post(pay).status_code,403)
        self.client.logout()
        self.assertEqual(self.client.post(pay).status_code,302)
        self.assertEqual(self.contract.functions.rewardCount().call(),0)

    def test_outage_mismatch_and_missing_hosted_signer_fail_honestly(self):
        reward=self.approved()
        with patch('booking.blockchain.client',side_effect=ConnectionError):
            self.assertFalse(rewards.fund_snapshot()['available'])
            self.assertEqual(rewards.check_reward(reward)['state'],'unknown')
        with override_settings(HOSTED_APP=True),patch.dict('os.environ',{},clear=True):
            with self.assertRaises(blockchain.ChainError): rewards.signing_account()
        bad=dict(self.config,operator=self.volunteer)
        with self.assertRaises(blockchain.ChainError): rewards.verified_contract(self.w3,bad)
        with self.assertRaises(blockchain.ChainError): rewards.verified_contract(self.w3,dict(self.config,chain_id=1))

    def test_website_keeps_voice_controls_without_provider_branding(self):
        for path in ['/','/book/','/learn/','/learn/video-calls/','/community/','/community/albums/']:
            response=self.client.get(path)
            self.assertNotContains(response,'ElevenLabs')
            self.assertNotContains(response,'ELEVENLABS')

    def test_private_circle_completion_requires_staff_approval_before_real_contract_payment(self):
        from .models import SupportCircle, SupportMember, SupportTask
        organizer = get_user_model().objects.create_user('circle-organizer')
        helper = get_user_model().objects.create_user('circle-helper')
        circle = SupportCircle.objects.create(owner=organizer, name='PRIVATE CIRCLE NAME')
        SupportMember.objects.create(circle=circle, user=organizer, role='owner')
        SupportMember.objects.create(circle=circle, user=helper, role='family')
        task = SupportTask.objects.create(circle=circle, created_by=organizer, title='PRIVATE CIRCLE TASK',
            details='PRIVATE CIRCLE NOTES', category='technology', assignee=helper, status='done')
        reward = VolunteerReward.objects.create(support_task=task, volunteer_wallet=self.volunteer, status='requested')
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('support_circle', args=[circle.pk])).status_code, 404)
        pay_url = reverse('pay_reward', args=[reward.public_id])
        self.client.post(pay_url)
        self.assertEqual(self.contract.functions.rewardCount().call(), 0)
        queue = self.client.get(reverse('support_reward_queue'))
        for private in [circle.name, task.title, task.details, organizer.username, helper.username]:
            self.assertNotContains(queue, private)
        self.client.post(reverse('approve_support_reward', args=[reward.public_id]))
        reward.refresh_from_db(); self.assertEqual(reward.status, 'approved')
        self.assertEqual(reward.approved_by, self.staff)
        before = self.w3.eth.get_balance(self.volunteer)
        self.client.post(pay_url)
        reward.refresh_from_db(); self.assertEqual(reward.status, 'paid')
        self.assertEqual(self.w3.eth.get_balance(self.volunteer)-before, 2*10**18)
        self.client.post(pay_url)
        self.assertEqual(self.contract.functions.rewardCount().call(), 1)
        page = self.client.get(reverse('reward_receipt', args=[reward.public_id]))
        for private in [circle.name, task.title, task.details, str(circle.pk), str(task.pk)]:
            self.assertNotContains(page, private)

    def test_circle_reward_cannot_be_approved_for_an_incomplete_or_removed_volunteer(self):
        from .models import SupportCircle, SupportMember, SupportTask
        owner = get_user_model().objects.create_user('circle-owner')
        circle = SupportCircle.objects.create(owner=owner, name='Private circle')
        member = SupportMember.objects.create(circle=circle, user=owner, role='owner')
        task = SupportTask.objects.create(circle=circle, created_by=owner, title='Example', category='company',
            status='review', assignee=owner)
        reward = VolunteerReward.objects.create(support_task=task, volunteer_wallet=self.volunteer, status='requested')
        self.client.force_login(self.staff)
        url = reverse('approve_support_reward', args=[reward.public_id])
        self.client.post(url); reward.refresh_from_db(); self.assertEqual(reward.status, 'requested')
        task.status='done'; task.save(); member.active=False; member.save()
        self.client.post(url); reward.refresh_from_db(); self.assertEqual(reward.status, 'requested')
        self.assertEqual(self.contract.functions.rewardCount().call(), 0)
