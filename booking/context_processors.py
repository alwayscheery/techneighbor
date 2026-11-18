from .voice import PROMPTS

def spoken_guide(request):
    return {'voice_prompts': PROMPTS}
