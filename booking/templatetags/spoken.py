from django import template
from booking.voice import PROMPTS

register = template.Library()


@register.inclusion_tag('spoken_help.html', takes_context=True)
def spoken_help(context, key, title):
    return {'voice_key': key, 'voice_title': title, 'voice_text': PROMPTS[key],
            'voice_prompts': {key: PROMPTS[key]}, 'csrf_token': context.get('csrf_token')}
