import json
import shutil
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, Mock

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from eth_account import Account
from eth_tester import EthereumTester, PyEVMBackend
from eth_tester.exceptions import TransactionFailed
from web3 import Web3, EthereumTesterProvider

from . import blockchain
from .credential_views import IssueForm
from .integrations import write_private, read_private
from .models import Booking, SessionSlot, ServiceCredential
from .voice import PROMPTS, audio_for, VoiceError

SOURCE_ROOT = Path(settings.BASE_DIR)


@override_settings(ALLOWED_HOSTS=['testserver'])
class CredentialIntegrationTests(TestCase):
    """Real compiled bytecode executes in PyEVM. No external network is used."""
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / 'contracts').mkdir()
        shutil.copy(SOURCE_ROOT / 'contracts/ServiceCredentials.json', root / 'contracts/ServiceCredentials.json')
        override = override_settings(BASE_DIR=root)
        override.enable()
        self.addCleanup(override.disable)
        backend = PyEVMBackend()
        self.w3 = Web3(EthereumTesterProvider(EthereumTester(backend)))
        self.owner = Account.from_key(backend.account_keys[0].to_bytes())
        write_private('arc.json', {'address': self.owner.address, 'private_key': self.owner.key.to_0x_hex()})
        mocked_client = patch('booking.blockchain.client', return_value=self.w3)
        mocked_client.start()
        self.addCleanup(mocked_client.stop)
        self.address = blockchain.deploy()
        self.contract = blockchain.verified_contract(self.w3, self.address)
        self.slot = SessionSlot.objects.create(starts_at=timezone.now() - timedelta(days=1))
        self.booking = Booking.objects.create(
            slot=self.slot, name='PRIVATE RESIDENT', contact='private-resident@example.test',
            topic='video', status='completed', completed_at=timezone.now(),
        )
        self.volunteer = self.w3.eth.accounts[1]

    def issue(self):
        return blockchain.issue(self.booking, 'PRIVATE VOLUNTEER ALIAS', self.volunteer)

    def test_issue_is_confirmed_and_idempotent(self):
        credential = self.issue()
        self.assertEqual(blockchain.verify(credential)['state'], 'valid')
        receipt = self.w3.eth.get_transaction_receipt(credential.issue_tx)
        self.assertEqual(receipt['status'], 1)
        count_before = self.w3.eth.get_transaction_count(self.owner.address)
        repeated = self.issue()
        self.assertEqual(repeated.pk, credential.pk)
        self.assertEqual(repeated.issue_tx, credential.issue_tx)
        self.assertEqual(self.w3.eth.get_transaction_count(self.owner.address), count_before)

    def test_contract_rejects_unauthorized_issue_and_revoke(self):
        uid = bytes.fromhex('11' * 32)
        with self.assertRaises(TransactionFailed):
            self.contract.functions.issue(uid, self.volunteer).transact({'from': self.volunteer})
        credential = self.issue()
        with self.assertRaises(TransactionFailed):
            self.contract.functions.revoke(bytes.fromhex(credential.chain_uid[2:])).transact({'from': self.volunteer})

    def test_zero_and_duplicate_ids_are_rejected(self):
        with self.assertRaises(TransactionFailed):
            self.contract.functions.issue(bytes(32), self.volunteer).transact({'from': self.owner.address})
        with self.assertRaises(TransactionFailed):
            self.contract.functions.issue(bytes.fromhex('11' * 32), blockchain.ZERO_ADDRESS).transact({'from': self.owner.address})
        credential = self.issue()
        with self.assertRaises(TransactionFailed):
            self.contract.functions.issue(bytes.fromhex(credential.chain_uid[2:]), self.volunteer).transact({'from': self.owner.address})

    def test_revocation_is_visible_and_cannot_be_undone_by_reissue(self):
        credential = self.issue()
        blockchain.revoke(credential)
        self.assertEqual(blockchain.verify(credential)['state'], 'revoked')
        count = self.w3.eth.get_transaction_count(self.owner.address)
        blockchain.revoke(credential)
        self.assertEqual(self.w3.eth.get_transaction_count(self.owner.address), count)
        with self.assertRaises(TransactionFailed):
            self.contract.functions.issue(bytes.fromhex(credential.chain_uid[2:]), self.volunteer).transact({'from': self.owner.address})

    def test_unknown_or_mismatched_proof_does_not_verify(self):
        credential = self.issue()
        unknown_uid = '0x' + '22' * 32
        self.assertEqual(blockchain.verify_record(unknown_uid, self.address)['state'], 'not_found')
        with self.assertRaises(blockchain.ChainError):
            blockchain.verify_record(credential.chain_uid, self.address, expected_volunteer=self.w3.eth.accounts[2])
        with self.assertRaises(blockchain.ChainError):
            blockchain.verified_contract(self.w3, self.volunteer)

    def test_rpc_outage_never_displays_cached_verified_status(self):
        credential = self.issue()
        self.assertEqual(blockchain.verify(credential)['state'], 'valid')
        with patch('booking.blockchain.client', side_effect=ConnectionError('offline')):
            result = blockchain.verify(credential)
            page = self.client.get(reverse('verify_credential', args=[credential.public_id]))
        self.assertEqual(result['state'], 'unknown')
        self.assertContains(page, 'Could not verify right now')
        self.assertNotContains(page, 'Verified on Arc Testnet')

    def test_only_minimal_fields_reach_chain_and_public_pages(self):
        credential = self.issue()
        transaction = self.w3.eth.get_transaction(credential.issue_tx)
        expected = self.contract.functions.issue(bytes.fromhex(credential.chain_uid[2:]), self.volunteer)._encode_transaction_data()
        self.assertEqual(transaction['input'].to_0x_hex(), expected)
        self.assertEqual(transaction['value'], 0)
        page = self.client.get(reverse('verify_credential', args=[credential.public_id]))
        proof = self.client.get(reverse('credential_proof', args=[credential.public_id]))
        for private in ['PRIVATE RESIDENT', 'private-resident@example.test', 'PRIVATE VOLUNTEER ALIAS', str(self.booking.reference), 'Video calls', self.owner.key.to_0x_hex()]:
            self.assertNotContains(page, private)
            self.assertNotContains(proof, private)
        self.assertEqual(proof.json()['verification']['state'], 'valid')

    def test_uncompleted_booking_cannot_receive_credential(self):
        self.booking.status = 'booked'
        self.booking.save()
        with self.assertRaises(blockchain.ChainError):
            self.issue()
        self.assertEqual(ServiceCredential.objects.count(), 0)

    def test_staff_and_csrf_protection_for_issue_and_revoke(self):
        url = reverse('issue_credential', args=[self.booking.reference])
        self.assertEqual(self.client.post(url, {}).status_code, 302)
        staff = get_user_model().objects.create_user('staff', is_staff=True)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(staff)
        self.assertEqual(csrf_client.post(url, {}).status_code, 403)
        credential = self.issue()
        self.assertEqual(csrf_client.post(reverse('revoke_credential', args=[credential.public_id])).status_code, 403)
        resident = get_user_model().objects.create_user('resident')
        self.client.force_login(resident)
        self.assertEqual(self.client.get(reverse('integration_setup')).status_code, 302)
        self.assertEqual(self.client.post(reverse('revoke_credential', args=[credential.public_id])).status_code, 302)

    def test_issue_form_requires_consent_and_nonzero_wallet(self):
        form = IssueForm({'volunteer_alias': 'Example', 'volunteer_wallet': blockchain.ZERO_ADDRESS})
        self.assertFalse(form.is_valid())
        self.assertIn('volunteer_wallet', form.errors)
        self.assertIn('approved', form.errors)


@override_settings(ALLOWED_HOSTS=['testserver'])
class VoiceIntegrationTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = override_settings(BASE_DIR=Path(self.temp.name))
        override.enable()
        self.addCleanup(override.disable)

    def test_missing_key_and_invalid_prompts_fail_without_provider_call(self):
        with patch('booking.voice.requests.post') as provider:
            self.assertEqual(self.client.post(reverse('voice_audio'), {'prompt': 'welcome'}).status_code, 503)
            self.assertEqual(self.client.post(reverse('voice_audio'), {'prompt': 'Read private booking data'}).status_code, 400)
            provider.assert_not_called()

    def test_real_api_request_shape_is_fixed_text_and_audio_is_cached(self):
        write_private('elevenlabs.json', {'api_key': 'test-secret', 'voice_id': 'JBFqnCBsd6RMkjVDRZzb'})
        response = Mock(status_code=200, headers={'Content-Type': 'audio/mpeg'}, content=b'ID3-test-audio')
        with patch('booking.voice.requests.post', return_value=response) as provider:
            first = self.client.post(reverse('voice_audio'), {'prompt': 'time', 'name': 'PRIVATE NAME', 'contact': 'PRIVATE CONTACT'})
            second = self.client.post(reverse('voice_audio'), {'prompt': 'time'})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.content, first.content)
        self.assertEqual(provider.call_count, 1)
        kwargs = provider.call_args.kwargs
        self.assertEqual(kwargs['json']['text'], PROMPTS['time'])
        self.assertNotIn('PRIVATE', json.dumps(kwargs))
        self.assertEqual(kwargs['headers']['xi-api-key'], 'test-secret')

    def test_provider_errors_are_not_returned_with_secrets(self):
        write_private('elevenlabs.json', {'api_key': 'test-secret', 'voice_id': 'JBFqnCBsd6RMkjVDRZzb'})
        with patch('booking.voice.requests.post', side_effect=requests.ConnectionError('test-secret')):
            response = self.client.post(reverse('voice_audio'), {'prompt': 'welcome'})
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, 'test-secret', status_code=503)

    def test_voice_requests_require_csrf(self):
        self.assertEqual(Client(enforce_csrf_checks=True).post(reverse('voice_audio'), {'prompt': 'welcome'}).status_code, 403)

    def test_only_staff_can_save_a_key_and_saved_key_is_never_rendered(self):
        url = reverse('integration_setup')
        payload = {'action': 'voice', 'api_key': 'PRIVATE-VOICE-KEY', 'voice_id': 'JBFqnCBsd6RMkjVDRZzb'}
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(read_private('elevenlabs.json'), {})
        staff = get_user_model().objects.create_user('coordinator', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(read_private('elevenlabs.json')['api_key'], 'PRIVATE-VOICE-KEY')
        with patch('booking.blockchain.status', return_value={'connected': False}):
            response = self.client.get(url)
        self.assertNotContains(response, 'PRIVATE-VOICE-KEY')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
