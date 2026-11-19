"""Local deployment only. Existing credential issuer key never leaves the Mac."""
import json
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from eth_account import Account
from web3 import Web3
from booking import blockchain, rewards
from booking.integrations import read_private, write_private, signer_lock


class Command(BaseCommand):
    help = 'Deploy a fixed-reward community fund to Arc TESTNET with 10 test USDC; safe to repeat.'

    def handle(self, *args, **options):
        if getattr(settings, 'HOSTED_APP', False):
            raise CommandError('Run this command only in the private local app.')
        with signer_lock():
            owner_config = read_private('arc.json')
            if not owner_config.get('private_key'):
                raise CommandError('Connect the local Arc Testnet organization wallet first.')
            owner = Account.from_key(owner_config['private_key'])
            config = read_private('rewards.json')
            if not config.get('private_key'):
                operator = Account.create()
                config = {'private_key': operator.key.to_0x_hex(), 'operator': operator.address}
                write_private('rewards.json', config)
            w3 = blockchain.client()
            if not config.get('deploy_tx'):
                compiled = rewards.artifact()
                factory = w3.eth.contract(abi=compiled['abi'], bytecode=compiled['bytecode'])
                config['deploy_tx'], config['deploy_raw'] = blockchain.sign_call(w3, owner, factory.constructor(config['operator']))
                write_private('rewards.json', config)
            receipt = blockchain.receipt_or_none(w3, config['deploy_tx'])
            if receipt is None:
                blockchain.broadcast(w3, config['deploy_raw'], config['deploy_tx'])
                receipt = blockchain.receipt_or_none(w3, config['deploy_tx'], wait=True)
            if receipt is None or receipt['status'] != 1:
                raise CommandError('Deployment is pending or failed. Check the saved transaction before retrying.')
            config.update(contract=receipt['contractAddress'], owner=owner.address, chain_id=blockchain.CHAIN_ID)
            write_private('rewards.json', config)
            rewards.verified_contract(w3, config)
            for label, target, amount in [('fund', config['contract'], '10'), ('operator_gas', config['operator'], '0.2')]:
                hash_key, raw_key = label+'_tx', label+'_raw'
                if not config.get(hash_key):
                    gas_price = w3.eth.gas_price
                    tx = {'from': owner.address, 'to': target, 'value': Web3.to_wei(amount, 'ether'),
                          'chainId': blockchain.CHAIN_ID, 'nonce': w3.eth.get_transaction_count(owner.address, 'pending'), 'gasPrice': gas_price}
                    tx['gas'] = int(w3.eth.estimate_gas(tx)*1.2)+5000
                    if tx['gas']*gas_price > Web3.to_wei('0.5','ether'):
                        raise CommandError('Test-network fee is above the safety limit.')
                    signed = owner.sign_transaction(tx)
                    config[hash_key], config[raw_key] = signed.hash.to_0x_hex(), signed.raw_transaction.to_0x_hex()
                    write_private('rewards.json', config)
                receipt = blockchain.receipt_or_none(w3, config[hash_key])
                if receipt is None:
                    blockchain.broadcast(w3, config[raw_key], config[hash_key])
                    receipt = blockchain.receipt_or_none(w3, config[hash_key], wait=True)
                if receipt is None or receipt['status'] != 1:
                    raise CommandError('A saved funding transaction is pending or failed; inspect before retrying.')
            public = {key: config[key] for key in ('owner','operator','contract','chain_id','deploy_tx','fund_tx','operator_gas_tx')}
            public['network'] = 'Arc Testnet'
            (Path(settings.BASE_DIR)/'contracts/reward-deployment.json').write_text(json.dumps(public,indent=2)+'\n')
            self.stdout.write('Arc Testnet fund deployed with 10 test USDC and a separate 0.2-test-USDC gas wallet. No keys were printed.')
