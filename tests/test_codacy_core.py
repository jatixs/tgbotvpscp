import os
import socket
import unittest
from unittest.mock import patch

import manage
from core.web.avatar import get_avatar_html
from node.input_validation import (
    is_valid_iperf_server,
    is_valid_network_host,
    parse_public_ip,
    resolve_public_host,
)


class CodacyCoreRegressionTests(unittest.TestCase):
    def test_compose_profile_is_limited_to_configured_profiles(self):
        with patch.dict(os.environ, {"COMPOSE_PROFILES": "secure"}, clear=False):
            self.assertEqual(manage._docker_compose_profile(), "secure")

        with patch.dict(os.environ, {"COMPOSE_PROFILES": "--help"}, clear=False):
            with self.assertRaises(ValueError):
                manage._docker_compose_profile()

    def test_avatar_html_escapes_user_controlled_values(self):
        avatar = get_avatar_html({"photo_url": '"><script>alert(1)</script>'})
        self.assertNotIn("<script>", avatar)
        self.assertIn("&lt;script&gt;", avatar)

    def test_avatar_images_require_https(self):
        avatar = get_avatar_html({"photo_url": "http://images.example/avatar.png"})
        self.assertNotIn("<img", avatar)
        self.assertIn("http://images.example/avatar.png", avatar)

    def test_server_list_hosts_are_validated_before_ping(self):
        self.assertTrue(
            is_valid_iperf_server(
                {"IP/HOST": "iperf.example.net", "PORT": "5201"}
            )
        )
        self.assertFalse(
            is_valid_iperf_server(
                {"IP/HOST": "--help", "PORT": "5201"}
            )
        )
        self.assertFalse(is_valid_network_host("https://example.net"))
        self.assertFalse(is_valid_network_host("127.0.0.1"))
        self.assertEqual(resolve_public_host("8.8.8.8"), "8.8.8.8")
        with patch(
            "node.input_validation.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))],
        ):
            self.assertIsNone(resolve_public_host("iperf.example.net"))

    def test_public_ip_parser_rejects_non_public_or_malformed_values(self):
        self.assertEqual(str(parse_public_ip("8.8.8.8")), "8.8.8.8")
        self.assertIsNone(parse_public_ip("127.0.0.1"))
        self.assertIsNone(parse_public_ip("https://example.net"))


if __name__ == "__main__":
    unittest.main()
