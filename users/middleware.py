import logging

from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.utils import timezone

from users.models import TokenUsage

logger = logging.getLogger(__name__)
User = get_user_model()


class APITokenRateLimitMiddleware:
    """
    Middleware that inspects incoming requests for an 'X-API-Token' header and checks
    user account freezing/deletion statuses (API Shielding).
    If X-API-Token is present, enforces a rate limit of 60 requests per minute and logs
    consumption metadata to the TokenUsage database table.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Retrieve 'X-API-Token' header from incoming request
        api_token = request.headers.get("X-API-Token")

        # 1. API Shielding: Resolve user dynamically from session or X-API-Token header
        user = None
        if hasattr(request, "user") and request.user.is_authenticated:
            user = request.user
        elif api_token and api_token.startswith("dev_token_"):
            # Extract username from token
            username = api_token.replace("dev_token_", "")
            try:
                user = User.objects.select_related("profile").get(username=username)
            except User.DoesNotExist:
                pass

        # Check account freezing/deletion if user is resolved
        if user:
            profile = getattr(user, "profile", None)
            if profile:
                if profile.deleted_at is not None:
                    return JsonResponse(
                        {"error": "Account has been soft-deleted."},
                        status=403,
                    )
                if profile.freezed_at is not None:
                    # Allow access to unfreeze endpoints to prevent lockout
                    if "unfreeze" not in request.path:
                        return JsonResponse(
                            {"error": "Account is frozen. Please reactivate to proceed."},
                            status=403,
                        )

        if not api_token:
            # No token present, bypass rate limiting and proceed normally
            return self.get_response(request)

        # 2. Evaluate current request quota (last 60 seconds)
        now = timezone.now()
        one_minute_ago = now - timezone.timedelta(seconds=60)

        # Count total requests processed in the last 60 seconds
        request_count = TokenUsage.objects.filter(
            api_token=api_token,
            request_timestamp__gte=one_minute_ago,
        ).count()

        endpoint = request.path

        # 3. Block request if quota is exceeded (60 requests/minute limit)
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

        # 4. Process the request
        response = self.get_response(request)

        # Log successful/failed response status code to DB
        TokenUsage.objects.create(
            api_token=api_token,
            endpoint=endpoint,
            request_timestamp=timezone.now(),
            response_status=response.status_code,
        )

        return response
