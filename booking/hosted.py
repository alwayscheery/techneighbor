"""Boundaries for the public demo; moderation stays available after sign-in."""
import re
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseNotFound, JsonResponse
from django.db import connection
from django.utils.crypto import salted_hmac


class HostedDemoMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if (path.startswith(('/admin/', '/coordinator/integrations/', '/coordinator/neighbors/maps/'))
                or re.fullmatch(r'/coordinator/booking/[^/]+/credential/', path)
                or re.fullmatch(r'/credentials/[^/]+/revoke/', path)):
            return HttpResponseNotFound('Issuer integrations are managed in the local coordinator app.')
        if request.method == 'POST' and path == '/coordinator/sign-in/':
            key = 'hosted-login:' + salted_hmac('login-throttle', request.META.get('REMOTE_ADDR', '')).hexdigest()
            count = cache.get(key, 0)
            if count >= 20:
                return HttpResponse('Too many sign-in attempts. Please wait one hour before trying again.', status=429)
            cache.set(key, count + 1, 3600)
        response = self.get_response(request)
        response['X-Robots-Tag'] = 'noindex, nofollow'
        return response


def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        return JsonResponse({'status': 'ok'})
    except Exception:
        return JsonResponse({'status': 'unavailable'}, status=503)
