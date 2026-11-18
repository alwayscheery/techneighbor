"""Arc TESTNET only. No resident data is ever encoded in a transaction."""
import json
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from eth_account import Account
from web3 import Web3
from web3.exceptions import TransactionNotFound, TimeExhausted

from .integrations import read_private, write_private, signer_lock

CHAIN_ID = 5042002
RPC_URL = 'https://rpc.testnet.arc.io'
EXPLORER = 'https://explorer.testnet.arc.io'
ZERO_ADDRESS = '0x' + '0' * 40


class ChainError(Exception):
    pass


def artifact():
    return json.loads((Path(settings.BASE_DIR) / 'contracts' / 'ServiceCredentials.json').read_text())


def client():
    w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={'timeout': 8}))
    if w3.eth.chain_id != CHAIN_ID:
        raise ChainError('The connection is not Arc Testnet. No transaction was sent.')
    return w3


def create_wallet():
    with signer_lock():
        config = read_private('arc.json')
        if not config.get('private_key'):
            account = Account.create()
            config = {'private_key': account.key.to_0x_hex(), 'address': account.address}
            write_private('arc.json', config)
        return config['address']


def status():
    config = read_private('arc.json')
    result = {'address': config.get('address'), 'contract': config.get('contract'), 'connected': False}
    try:
        w3 = client()
        result.update(connected=True, block=w3.eth.block_number)
        if result['address']:
            result['balance'] = str(Web3.from_wei(w3.eth.get_balance(result['address']), 'ether'))
        if result['contract']:
            verified_contract(w3, result['contract'], config['address'])
            result['ready'] = True
    except Exception:
        result['error'] = 'Arc Testnet could not be checked. Try again shortly.'
    return result


def verified_contract(w3, address, expected_issuer=None, block_identifier='latest'):
    address = Web3.to_checksum_address(address)
    compiled = artifact()
    if w3.eth.get_code(address, block_identifier=block_identifier).to_0x_hex().lower() != compiled['deployedBytecode'].lower():
        raise ChainError('The contract code does not match this service credential registry.')
    contract = w3.eth.contract(address=address, abi=compiled['abi'])
    issuer = contract.functions.issuer().call(block_identifier=block_identifier)
    if expected_issuer and issuer.lower() != expected_issuer.lower():
        raise ChainError('The contract issuer does not match the configured organization wallet.')
    return contract


def sign_call(w3, account, call):
    gas_price = w3.eth.gas_price
    gas = int(call.estimate_gas({'from': account.address}) * 1.2) + 5000
    if gas > 1_200_000 or gas * gas_price > Web3.to_wei('0.5', 'ether'):
        raise ChainError('The estimated fee exceeds the test-network safety limit. Try again later.')
    if w3.eth.get_balance(account.address) < gas * gas_price:
        raise ChainError('The organization wallet needs free Arc Testnet USDC from the faucet.')
    tx = call.build_transaction({
        'from': account.address, 'chainId': CHAIN_ID, 'value': 0,
        'nonce': w3.eth.get_transaction_count(account.address, 'pending'),
        'gas': gas, 'gasPrice': gas_price,
    })
    signed = account.sign_transaction(tx)
    return signed.hash.to_0x_hex(), signed.raw_transaction.to_0x_hex()


def broadcast(w3, raw, tx_hash):
    """Replaying a stored signed transaction cannot create a second issuance."""
    try:
        w3.eth.send_raw_transaction(raw)
    except Exception:
        # The node may have accepted it before a timeout, or another node knows it.
        try:
            w3.eth.get_transaction(tx_hash)
        except Exception as exc:
            raise ChainError('The submission could not be confirmed. Its transaction ID was saved; retry to resend the same transaction safely.') from exc


def receipt_or_none(w3, tx_hash, wait=False):
    if not tx_hash:
        return None
    try:
        if wait:
            return w3.eth.wait_for_transaction_receipt(tx_hash, timeout=15, poll_latency=1)
        return w3.eth.get_transaction_receipt(tx_hash)
    except (TransactionNotFound, TimeExhausted):
        return None


def deploy():
    with signer_lock():
        config = read_private('arc.json')
        if not config.get('private_key'):
            raise ChainError('Create an organization test wallet first.')
        w3 = client()
        if config.get('contract'):
            verified_contract(w3, config['contract'], config['address'])
            return config['contract']
        if not config.get('deploy_tx'):
            compiled = artifact()
            factory = w3.eth.contract(abi=compiled['abi'], bytecode=compiled['bytecode'])
            config['deploy_tx'], config['deploy_raw'] = sign_call(w3, Account.from_key(config['private_key']), factory.constructor())
            write_private('arc.json', config)
        receipt = receipt_or_none(w3, config['deploy_tx'])
        if receipt is None:
            broadcast(w3, config['deploy_raw'], config['deploy_tx'])
            receipt = receipt_or_none(w3, config['deploy_tx'], wait=True)
        if receipt is None:
            raise ChainError('The deployment is pending. Use Check and deploy again to check the same transaction.')
        if receipt['status'] != 1:
            raise ChainError('The deployment transaction failed. Review its receipt before deploying again.')
        config['contract'] = receipt['contractAddress']
        verified_contract(w3, config['contract'], config['address'])
        write_private('arc.json', config)
        public = {key: config[key] for key in ('address', 'contract', 'deploy_tx')}
        public.update(chain_id=CHAIN_ID, network='Arc Testnet')
        (Path(settings.BASE_DIR) / 'contracts' / 'deployment.json').write_text(json.dumps(public, indent=2))
        return config['contract']


def issue(booking, alias, volunteer_wallet):
    from .models import Booking, ServiceCredential
    if booking.status != Booking.Status.COMPLETED:
        raise ChainError('Only a completed session can receive a credential.')
    with signer_lock():
        config = read_private('arc.json')
        if not config.get('contract'):
            raise ChainError('Connect and deploy the Arc Testnet registry in Integration setup first.')
        w3 = client()
        contract = verified_contract(w3, config['contract'], config['address'])
        credential, _ = ServiceCredential.objects.get_or_create(booking=booking, defaults={
            'volunteer_alias': alias, 'volunteer_wallet': Web3.to_checksum_address(volunteer_wallet),
            'issuer_wallet': config['address'], 'contract_address': config['contract'],
        })
        if credential.issue_tx:
            if credential.status == 'pending':
                if receipt_or_none(w3, credential.issue_tx) is None:
                    broadcast(w3, credential.issue_raw, credential.issue_tx)
            return credential
        if credential.status != 'draft':
            raise ChainError('This credential cannot be reissued. Review its transaction first.')
        credential.issue_tx, credential.issue_raw = sign_call(
            w3, Account.from_key(config['private_key']),
            contract.functions.issue(bytes.fromhex(credential.chain_uid[2:]), credential.volunteer_wallet),
        )
        credential.status = 'pending'
        credential.save()
        broadcast(w3, credential.issue_raw, credential.issue_tx)
        receipt_or_none(w3, credential.issue_tx, wait=True)
        return credential


def revoke(credential):
    with signer_lock():
        config = read_private('arc.json')
        if config.get('address', '').lower() != credential.issuer_wallet.lower():
            raise ChainError('The configured wallet is not this credential’s issuer.')
        w3 = client()
        contract = verified_contract(w3, credential.contract_address, credential.issuer_wallet)
        record = contract.functions.credentials(bytes.fromhex(credential.chain_uid[2:])).call()
        if not record[1]:
            raise ChainError('The credential has not been confirmed onchain yet.')
        if record[2]:
            return
        if not credential.revoke_tx:
            credential.revoke_tx, credential.revoke_raw = sign_call(
                w3, Account.from_key(config['private_key']), contract.functions.revoke(bytes.fromhex(credential.chain_uid[2:])),
            )
            credential.status = 'revoke_pending'
            credential.save()
        if receipt_or_none(w3, credential.revoke_tx) is None:
            broadcast(w3, credential.revoke_raw, credential.revoke_tx)
        receipt = receipt_or_none(w3, credential.revoke_tx, wait=True)
        if receipt is not None and receipt['status'] != 1:
            raise ChainError('The revocation transaction failed. This credential remains valid until a revocation succeeds.')


def verify_record(uid, contract_address, expected_issuer=None, expected_volunteer=None):
    """Reads current chain state. Does not consult a booking or cached status."""
    w3 = client()
    checked_block = w3.eth.block_number
    contract = verified_contract(w3, contract_address, expected_issuer, block_identifier=checked_block)
    volunteer, issued_at, revoked_at = contract.functions.credentials(bytes.fromhex(uid[2:])).call(block_identifier=checked_block)
    if not issued_at:
        return {'state': 'not_found', 'label': 'Not found on Arc Testnet'}
    if expected_volunteer and volunteer.lower() != expected_volunteer.lower():
        raise ChainError('The onchain volunteer address does not match this credential.')
    return {
        'state': 'revoked' if revoked_at else 'valid',
        'label': 'Revoked on Arc Testnet' if revoked_at else 'Verified on Arc Testnet',
        'volunteer': volunteer, 'issuer': contract.functions.issuer().call(block_identifier=checked_block),
        'issued_at': datetime.fromtimestamp(issued_at, tz=dt_timezone.utc),
        'revoked_at': datetime.fromtimestamp(revoked_at, tz=dt_timezone.utc) if revoked_at else None,
        'checked_block': checked_block,
    }


def verify(credential):
    if credential.chain_id != CHAIN_ID:
        return {'state': 'unknown', 'label': 'Unsupported network'}
    try:
        result = verify_record(credential.chain_uid, credential.contract_address,
                               credential.issuer_wallet, credential.volunteer_wallet)
        if result['state'] in ('valid', 'revoked'):
            if result['state'] == 'revoked':
                state = 'revoked'
            elif credential.revoke_tx and receipt_or_none(client(), credential.revoke_tx) is None:
                # A revocation in flight must not look unconditionally valid.
                result.update(state='revoking', label='Revocation pending on Arc Testnet')
                state = 'revoke_pending'
            else:
                state = 'issued'
            type(credential).objects.filter(pk=credential.pk).update(status=state)
            credential.status = state
        elif credential.issue_tx:
            receipt = receipt_or_none(client(), credential.issue_tx)
            if receipt is not None and receipt['status'] == 0:
                result.update(state='failed', label='Issuance transaction failed')
                type(credential).objects.filter(pk=credential.pk).update(status='failed')
            elif receipt is None:
                result.update(state='pending', label='Awaiting blockchain confirmation')
            else:
                result.update(state='unknown', label='Proof does not match the confirmed transaction')
        return result
    except Exception:
        return {'state': 'unknown', 'label': 'Could not verify right now',
                'error': 'Arc Testnet could not be checked, or this proof did not match the registry. A saved status is not proof of current validity.'}


def public_proof(credential):
    return {
        'schema': 'techneighbor.service.v1', 'network': 'Arc Testnet', 'chain_id': CHAIN_ID,
        'credential_id': credential.chain_uid, 'contract_address': credential.contract_address,
        'issuer_wallet': credential.issuer_wallet, 'volunteer_wallet': credential.volunteer_wallet,
        'issue_transaction': credential.issue_tx, 'revocation_transaction': credential.revoke_tx or None,
    }
