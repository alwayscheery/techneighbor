from .voice import PROMPTS
from django.conf import settings

def spoken_guide(request):
    return {'voice_prompts': PROMPTS, 'hosted_mode': getattr(settings, 'HOSTED_APP', False), 'issuer_tools_enabled': not getattr(settings, 'HOSTED_APP', False), 'phone_database_available': 'phone_demo' in settings.DATABASES}
