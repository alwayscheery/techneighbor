import json
from django.core.management.base import BaseCommand, CommandError
from booking.blockchain import verify_record


class Command(BaseCommand):
    help = 'Read an Arc Testnet service credential directly, without consulting the app database.'

    def add_arguments(self, parser):
        parser.add_argument('credential_id')
        parser.add_argument('--contract', required=True)

    def handle(self, *args, **options):
        import re
        if not re.fullmatch(r'0x[0-9a-fA-F]{64}', options['credential_id']):
            raise CommandError('Credential ID must be 0x plus 64 hexadecimal characters.')
        try:
            result = verify_record(options['credential_id'], options['contract'])
        except Exception as exc:
            raise CommandError('Could not verify the contract and credential on Arc Testnet.') from exc
        self.stdout.write(json.dumps(result, indent=2, default=str))
