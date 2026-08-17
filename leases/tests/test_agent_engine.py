from unittest.mock import patch

import httpx
from django.test import Client, TestCase

from leases.simulation.agent_engine import AgentEngine


class AgentEngineTestCase(TestCase):
    @patch("billing.services.payment_gateway.httpx.post")
    def test_all_programmatic_agent_personas_success(self, mock_post):
        # Seed catalog in test database
        from io import StringIO

        from django.core.management import call_command

        call_command("seed_catalog", stdout=StringIO())

        # Mock payment gateway response: Success
        mock_response = httpx.Response(status_code=200, json={"status": "succeeded"})
        mock_post.return_value = mock_response

        # Instantiate AgentEngine
        engine = AgentEngine()

        # Run all personas with Django Test Client
        client = Client()
        success = engine.run_all(client)

        # Assert all programmatic personas finished with expected outcomes
        self.assertTrue(success)

        # Verify specific persona results
        self.assertIn("HappyPath", engine.results)
        self.assertTrue(engine.results["HappyPath"]["success"])

        self.assertIn("Delinquent", engine.results)
        self.assertTrue(engine.results["Delinquent"]["success"])

        self.assertIn("UpgradeSeeker", engine.results)
        self.assertTrue(engine.results["UpgradeSeeker"]["success"])

        self.assertIn("Abusive", engine.results)
        self.assertTrue(engine.results["Abusive"]["success"])
