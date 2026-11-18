import re
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponseNotFound, HttpResponse
from django.core.cache import cache

UUID = r'[0-9a-fA-F-]{36}'
PUBLIC_GET = re.compile(rf'^(?:/|/learn/(?:[a-z-]+/)?|/book/|/booking/{UUID}/|/credentials/{UUID}/(?:proof\.json)?)$')
PUBLIC_POST = re.compile(rf'^(?:/book/|/voice/audio/|/booking/{UUID}/cancel/)$')
COMMUNITY_GET = re.compile(rf'^/community/(?:|albums/|albums/[a-zA-Z0-9_-]+/|events/[a-zA-Z0-9_-]+/|photos/upload/|photos/{UUID}/(?:image/)?)$')
COMMUNITY_POST = re.compile(rf'^/community/(?:photos/upload/|events/[a-zA-Z0-9_-]+/attendance/|photos/{UUID}/action/)$')


class PhoneDemoMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.phone_demo = True
        allowed = PUBLIC_GET.fullmatch(request.path) if request.method in ('GET', 'HEAD') else (
            PUBLIC_POST.fullmatch(request.path) if request.method == 'POST' else None)
        if not allowed:
            allowed = COMMUNITY_GET.fullmatch(request.path) if request.method in ('GET', 'HEAD') else (
                COMMUNITY_POST.fullmatch(request.path) if request.method == 'POST' else None)
        if not allowed:
            return HttpResponseNotFound('This action is available only in the local coordinator app.')
        if request.method == 'POST':
            count = cache.get('phone-demo-posts', 0)
            if count >= 300:
                return HttpResponse('This temporary demo has reached its request limit.', status=429)
            cache.set('phone-demo-posts', count + 1, 3600)
        response = self.get_response(request)
        response['X-Robots-Tag'] = 'noindex, nofollow'
        return response


class AnonymousDemoMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.user = AnonymousUser()
        return self.get_response(request)
