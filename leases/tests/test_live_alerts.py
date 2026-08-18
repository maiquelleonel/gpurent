from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from leases.models import SystemAlert

User = get_user_model()


class LiveAlertsTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        # Create normal user and superuser (staff member)
        self.normal_user = User.objects.create_user(username="normal", password="password")
        self.staff_user = User.objects.create_superuser(
            username="admin_staff", email="admin@example.com", password="password"
        )

    def test_anonymous_and_non_staff_users_are_redirected(self):
        # 1. Anonymous request to alerts endpoint redirects to admin login (302)
        response_anon = self.client.get("/admin/api/live-alerts/")
        self.assertEqual(response_anon.status_code, 302)

        # 2. Non-staff authenticated user redirects as well
        self.client.force_login(self.normal_user)
        response_non_staff = self.client.get("/admin/api/live-alerts/")
        self.assertEqual(response_non_staff.status_code, 302)

    def test_live_alerts_polling_renders_toasts_and_marks_as_read(self):
        # Create unread System Alerts
        alert1 = SystemAlert.objects.create(
            alert_type="signup",
            message="New tenant registered: testuser",
        )
        alert2 = SystemAlert.objects.create(
            alert_type="billing",
            message="Invoice #123 generated: $15.00",
        )

        # Log in staff member
        self.client.force_login(self.staff_user)

        # 1. First poll: retrieves both unread alerts
        response = self.client.get("/admin/api/live-alerts/")
        self.assertEqual(response.status_code, 200)

        # Assert response HTML contains messages and appropriate Bootstrap colors
        html_content = response.content.decode()
        self.assertIn("New tenant registered: testuser", html_content)
        self.assertIn("Invoice #123 generated: $15.00", html_content)
        self.assertIn("django-admin-alert", html_content)
        self.assertIn("#fef9c3", html_content)  # default warm yellow bg for signup alert
        self.assertIn("#dcfce7", html_content)  # green bg for billing alert
        self.assertIn("setTimeout", html_content)  # auto-destruction script

        # Verify that both alerts are now marked as read in database
        alert1.refresh_from_db()
        alert2.refresh_from_db()
        self.assertTrue(alert1.is_read)
        self.assertTrue(alert2.is_read)

        # 2. Second poll: since both are read, response should be empty
        response_empty = self.client.get("/admin/api/live-alerts/")
        self.assertEqual(response_empty.status_code, 200)
        self.assertEqual(response_empty.content.decode(), "")
