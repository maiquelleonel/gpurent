import logging

from django.http import JsonResponse
from django.utils import timezone

from users.models import TokenUsage

logger = logging.getLogger(__name__)


class APITokenRateLimitMiddleware:
    """
    Middleware that inspects incoming requests for an 'X-API-Token' header.
    If present, enforces a rate limit of 60 requests per minute and logs consumption
    metadata to the TokenUsage database table.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Retrieve 'X-API-Token' header from incoming request
        api_token = request.headers.get("X-API-Token")

        if not api_token:
            # No token present, bypass rate limiting and proceed normally
            return self.get_response(request)

        # 1. Evaluate current request quota (last 60 seconds)
        now = timezone.now()
        one_minute_ago = now - timezone.timedelta(seconds=60)

        # Count total requests processed in the last 60 seconds
        request_count = TokenUsage.objects.filter(
            api_token=api_token,
            request_timestamp__gte=one_minute_ago,
        ).count()

        endpoint = request.path

        # 2. Block request if quota is exceeded (60 requests/minute limit)
        if request_count >= 60:
            logger.warning(
                "Rate limit breached for token: %s on endpoint: %s. Requests in last 60s: %d",
                api_token,
                endpoint,
                request_count,
            )

            # Log delinquent request status to DB as 429
            TokenUsage.objects.create(
                api_token=api_token,
                endpoint=endpoint,
                request_timestamp=now,
                response_status=429,
            )

            return JsonResponse(
                {"error": "Rate limit exceeded. Quota is 60 requests per minute."},
                status=429,
            )

        # 3. Process the request
        response = self.get_response(request)

        # Log successful/failed response status code to DB
        TokenUsage.objects.create(
            api_token=api_token,
            endpoint=endpoint,
            request_timestamp=timezone.now(),
            response_status=response.status_code,
        )

        return response
