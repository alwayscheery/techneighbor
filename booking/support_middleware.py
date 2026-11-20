from django.core.cache import cache
from django.http import HttpResponse
from django.utils.cache import patch_vary_headers
from django.utils.crypto import salted_hmac


class SupportPrivacyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith('/support/'):
            return self.get_response(request)
        limits = {'/support/sign-in/': 20, '/support/sign-up/': 5, '/support/join/': 20}
        response = None
        if request.method == 'POST' and request.path in limits:
            key = 'support-rate:' + salted_hmac('support-auth', request.path + '|' + request.META.get('REMOTE_ADDR', '')).hexdigest()
            cache.add(key, 0, 3600)
            try:
                count = cache.incr(key)
            except ValueError:
                count = 1
                cache.set(key, count, 3600)
            if count > limits[request.path]:
                response = HttpResponse('Too many attempts. Please try again in one hour.', status=429)
        if response is None:
            response = self.get_response(request)
        response['Cache-Control'] = 'private, no-store'
        response['Referrer-Policy'] = 'same-origin'
        response['X-Robots-Tag'] = 'noindex, nofollow'
        patch_vary_headers(response, ['Cookie'])
        return response
