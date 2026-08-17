from django.test import Client, TestCase

from users.models import TokenUsage


class APITokenRateLimitTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.token = "dev_token_abc_123"
        self.endpoint = "/admin/"  # Valid endpoint inside gpurent/urls.py

    def test_rate_limiting_enforced_after_sixty_requests(self):
        self.assertEqual(TokenUsage.objects.count(), 0)

        # 1. Fire exactly 60 requests using our X-API-Token header
        for _ in range(60):
            response = self.client.get(
                self.endpoint,
                headers={"X-API-Token": self.token},
            )
            # Standard response: admin returns 200/302, or 404 if not found
            # but middleware processes and logs either way.
            self.assertIn(response.status_code, [200, 302, 404])

        # Verify exactly 60 usage logs were recorded in the database
        self.assertEqual(TokenUsage.objects.filter(api_token=self.token).count(), 60)

        # 2. Fire the 61st request and assert rejection with HTTP 429
        response_61 = self.client.get(
            self.endpoint,
            headers={"X-API-Token": self.token},
        )
        self.assertEqual(response_61.status_code, 429)
        self.assertJSONEqual(
            response_61.content.decode(),
            {"error": "Rate limit exceeded. Quota is 60 requests per minute."},
        )

        # Confirm 61st request created a TokenUsage record with status 429
        self.assertEqual(TokenUsage.objects.filter(api_token=self.token).count(), 61)
        latest_usage = TokenUsage.objects.filter(api_token=self.token).order_by("-request_timestamp").first()
        self.assertEqual(latest_usage.response_status, 429)

    def test_requests_without_token_bypasses_rate_limiting(self):
        # Fire more than 60 requests without token
        for _ in range(65):
            response = self.client.get(self.endpoint)
            self.assertIn(response.status_code, [200, 302, 404])

        # Confirm zero database logs were recorded since token was missing
        self.assertEqual(TokenUsage.objects.count(), 0)
