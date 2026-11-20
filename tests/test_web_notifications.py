"""Regression tests for the shared WebUI notification state used by API and SSE."""
import unittest
from collections import deque

from core import shared_state
from core.web.notification_state import clear_user_notifications, get_user_notifications


class NotificationClearTests(unittest.TestCase):
    def setUp(self):
        self.original_notifications = shared_state.WEB_NOTIFICATIONS
        self.original_read = shared_state.WEB_USER_LAST_READ
        self.original_cleared = shared_state.WEB_USER_CLEARED_AT
        self.original_alerts = shared_state.ALERTS_CONFIG
        shared_state.WEB_NOTIFICATIONS = deque([
            {"time": 100.0, "type": "cpu", "text": "Older"},
            {"time": 200.0, "type": "cpu", "text": "Newer"},
        ], maxlen=50)
        shared_state.WEB_USER_LAST_READ = {}
        shared_state.WEB_USER_CLEARED_AT = {}
        shared_state.ALERTS_CONFIG = {1: {"cpu": True}, 2: {"cpu": True}}
        self.addCleanup(self.restore)

    def restore(self):
        shared_state.WEB_NOTIFICATIONS = self.original_notifications
        shared_state.WEB_USER_LAST_READ = self.original_read
        shared_state.WEB_USER_CLEARED_AT = self.original_cleared
        shared_state.ALERTS_CONFIG = self.original_alerts

    def visible(self, user_id):
        return get_user_notifications(user_id, "en", "en")

    def test_clear_is_user_scoped(self):
        clear_user_notifications(1, now=150.0)
        self.assertEqual(len(shared_state.WEB_NOTIFICATIONS), 2)
        self.assertEqual(shared_state.WEB_USER_CLEARED_AT, {1: 150.0})
        self.assertEqual(shared_state.WEB_USER_LAST_READ[1], 150.0)
        self.assertEqual([n["text"] for n in self.visible(1)["notifications"]], ["Newer"])
        self.assertEqual([n["text"] for n in self.visible(2)["notifications"]], ["Older", "Newer"])
        self.assertEqual(self.visible(1)["unread_count"], 1)
        self.assertEqual(self.visible(2)["unread_count"], 2)

    def test_clear_idempotent_and_new_notifications_visible(self):
        clear_user_notifications(1, now=250.0)
        clear_user_notifications(1, now=250.0)
        self.assertEqual(self.visible(1)["notifications"], [])
        shared_state.WEB_NOTIFICATIONS.append({"time": 251.0, "type": "cpu", "text": "Fresh"})
        self.assertEqual([n["text"] for n in self.visible(1)["notifications"]], ["Fresh"])

    def test_language_fallback_and_type_filter(self):
        shared_state.WEB_NOTIFICATIONS.append({
            "time": 210.0, "type": "cpu", "text": "Original",
            "text_map": {"ru": "Перевод", "en": "Translation"},
        })
        visible = get_user_notifications(1, "de", "en")["notifications"]
        self.assertEqual(visible[-1]["text"], "Translation")
        self.assertNotIn("text_map", visible[-1])
        self.assertIn("text_map", shared_state.WEB_NOTIFICATIONS[-1])
        shared_state.ALERTS_CONFIG[1]["cpu"] = False
        self.assertEqual(self.visible(1)["notifications"], [])


if __name__ == "__main__":
    unittest.main()
