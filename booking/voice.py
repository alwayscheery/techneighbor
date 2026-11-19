"""ElevenLabs reads fixed instructions and lessons, never user-submitted details."""
import hashlib
import re
from pathlib import Path
import requests
from django.conf import settings

from .integrations import elevenlabs_settings, private_dir

PROMPTS = {
    'community': 'Welcome to your community hub. Explore an activity to see when and where it happens, then save a place. You can also browse photo albums or share a moment of your own.',
    'joining': 'Check the activity date, time, and location. Enter a first name or nickname, then select Save my place. Return on this device to release your place if your plans change.',
    'albums': 'Choose an album, then open a photo to enjoy its story. To add your own, select Share a photo. A coordinator checks every photo before it appears in the shared album.',
    'upload': 'Choose an album and a photo. Add a title, a short description, and your nickname. Confirm you have permission to share, then send for approval. Avoid private documents or addresses.',
    'lesson_calls': 'Let us try a video call. Open your usual calling app. Choose someone you know, then look for the camera button. Ask for camera and microphone access only when you expect it. End the call with the red button.',
    'lesson_photos': 'Open Photos and choose a picture. Tap Share, then choose a person you trust. Check the recipient before sending. Ask permission from anyone pictured. You can stop before you press Send.',
    'lesson_safety': 'An urgent message can wait. Do not share passwords, verification codes, or money because of an unexpected call or message. Contact the person through a number you already know, or ask a trusted helper.',
    'welcome': 'Welcome. I can guide you through booking a free community session. First, choose companionship, everyday help, or technology help. You can pause or replay me at any time.',
    'companionship': 'You have chosen companionship. Choose a friendly chat, a gentle walk, or a board game together. Then choose an available time.',
    'everyday': 'You have chosen everyday help. Choose help planning errands, organizing a small task, or reading an everyday letter. Then choose an available time.',
    'technology': 'You have chosen technology help. Choose video calls, phone basics, or photos and sharing. Then choose an available time.',
    'time': 'Next, choose an available session. Each session lasts thirty minutes. Times are shown in Pacific Time. All sessions start at the community center.',
    'details': 'Now enter the name of the person attending. You can book for yourself or someone else. Phone or email is optional. For this demonstration, use fictional details.',
    'review': 'Review your activity, time, and name. When you are happy with your choices, select Book my free session. I will not submit the booking for you.',
    'confirmation': 'Your booking has been saved. Your session details are on this page. Save or print them for later. No email or text message has been sent. You can cancel using the section near the bottom of this page.',
}


class VoiceError(Exception):
    pass


def audio_for(prompt):
    if prompt not in PROMPTS:
        raise VoiceError('Choose one of the available guide steps.')
    config = elevenlabs_settings()
    if not re.fullmatch(r'[A-Za-z0-9_-]{10,80}', config['voice_id']):
        raise VoiceError('The configured voice is not valid. Ask your coordinator to check Integration setup.')
    text = PROMPTS[prompt]
    key = hashlib.sha256((config['voice_id'] + '|eleven_multilingual_v2|' + text).encode()).hexdigest()
    folder = private_dir() / 'audio-cache'
    folder.mkdir(mode=0o700, exist_ok=True)
    path = folder / (key + '.mp3')
    if path.exists():
        return path.read_bytes()
    if getattr(settings, 'HOSTED_APP', False):
        from .models import HostedGuideAudio
        saved = HostedGuideAudio.objects.filter(cache_key=key).first()
        if saved:
            return bytes(saved.audio_data)
    if getattr(settings, 'PUBLIC_PHONE_DEMO', False) or getattr(settings, 'VOICE_CACHE_ONLY', False):
        raise VoiceError('This demo clip is not available right now. The written steps remain available.')
    if not config['api_key']:
        raise VoiceError('Spoken guidance is not connected yet. A coordinator can connect the voice service in Integration setup. You can still use all of the written steps.')
    try:
        response = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{config['voice_id']}",
            params={'output_format': 'mp3_44100_128'},
            headers={'xi-api-key': config['api_key'], 'Content-Type': 'application/json'},
            json={'text': text, 'model_id': 'eleven_multilingual_v2'}, timeout=(5, 35),
        )
    except requests.RequestException as exc:
        raise VoiceError('The voice service could not be reached. Please try again, or follow the written steps.') from exc
    if response.status_code != 200 or not response.headers.get('Content-Type', '').startswith('audio/'):
        raise VoiceError('The voice service could not produce the guide audio. Ask your coordinator to check the API key, voice access, and available credits.')
    if len(response.content) > 5_000_000:
        raise VoiceError('The voice response was too large. Please use the written steps.')
    path.write_bytes(response.content)
    path.chmod(0o600)
    return response.content
