import logging

from django.contrib.auth import get_user_model
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger(__name__)
User = get_user_model()


class APITokenAuthentication(authentication.BaseAuthentication):
    """
    Custom authentication class for Django REST Framework.
    Validates requests using the 'X-API-Token' header and returns the authenticated User.
    Supports a mock token pattern 'dev_token_<username>' for testing.
    """

    def authenticate(self, request):
        # Inspect headers for 'X-API-Token'
        api_token = request.headers.get("X-API-Token")

        if not api_token:
            # Allow fallback to standard session auth or return None to let permission classes handle
            return None

        # 1. Dual-Mode Auth: Check official DRF Token table first
        from rest_framework.authtoken.models import Token

        try:
            token_obj = Token.objects.select_related("user__profile").get(key=api_token)
            user = token_obj.user
            if user.profile.deleted_at is not None:
                raise AuthenticationFailed("This account has been soft-deleted.")
            logger.info("Successfully authenticated API request using official DRF Token for user: %s", user.username)
            return (user, None)
        except Token.DoesNotExist:
            pass

        # 2. Dual-Mode Auth: Fallback to mock token format 'dev_token_<username>' for test environments
        if not api_token.startswith("dev_token_"):
            raise AuthenticationFailed("Invalid API Token. Expected an official DRF Token or 'dev_token_<username>'.")

        # Extract username from mock token
        username = api_token.replace("dev_token_", "")

        try:
            user = User.objects.select_related("profile").get(username=username)
        except User.DoesNotExist as e:
            raise AuthenticationFailed("No user associated with this API Token.") from e

        # Check soft-deletion safety
        if user.profile.deleted_at is not None:
            raise AuthenticationFailed("This account has been soft-deleted.")

        # Successfully authenticated! Return (user, auth_payload)
        logger.info("Successfully authenticated API request using Mock Token for user: %s", user.username)
        return (user, None)
