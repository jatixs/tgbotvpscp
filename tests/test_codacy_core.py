import os
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import manage
from core.web.avatar import get_avatar_html
from network_validation import (
    is_valid_iperf_server,
    is_valid_network_host,
    parse_public_ip,
    resolve_public_host,
)


class CodacyCoreRegressionTests(unittest.IsolatedAsyncioTestCase):
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
            "network_validation.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))],
        ):
            self.assertIsNone(resolve_public_host("iperf.example.net"))

    def test_public_ip_parser_rejects_non_public_or_malformed_values(self):
        self.assertEqual(str(parse_public_ip("8.8.8.8")), "8.8.8.8")
        self.assertIsNone(parse_public_ip("127.0.0.1"))
        self.assertIsNone(parse_public_ip("https://example.net"))

    async def test_docker_compose_command_prefers_docker_and_uses_static_strings(self):
        process = SimpleNamespace(wait=AsyncMock(return_value=0), returncode=0, kill=lambda: None)
        spawn = AsyncMock(return_value=process)

        def mock_which_docker(binary, **kw):
            return f"/usr/bin/{binary}" if binary == "docker" else None

        with (
            patch("manage.shutil.which", side_effect=mock_which_docker),
            patch("manage.asyncio.create_subprocess_exec", spawn),
        ):
            cmd = await manage._docker_compose_command()
            self.assertEqual(cmd, ["/usr/bin/docker", "compose"])
            self.assertEqual(spawn.call_args.args, ("docker", "compose", "version"))

    async def test_docker_compose_command_falls_back_to_docker_compose(self):
        process = SimpleNamespace(wait=AsyncMock(return_value=0), returncode=0, kill=lambda: None)
        spawn = AsyncMock(return_value=process)

        def mock_which_compose(binary, **kw):
            return f"/usr/local/bin/{binary}" if binary == "docker-compose" else None

        with (
            patch("manage.shutil.which", side_effect=mock_which_compose),
            patch("manage.asyncio.create_subprocess_exec", spawn),
        ):
            cmd = await manage._docker_compose_command()
            self.assertEqual(cmd, ["/usr/local/bin/docker-compose"])
            self.assertEqual(spawn.call_args.args, ("docker-compose", "version"))

    async def test_docker_compose_command_raises_when_neither_available(self):
        with patch("manage.shutil.which", return_value=None):
            with self.assertRaises(RuntimeError):
                await manage._docker_compose_command()


if __name__ == "__main__":
    unittest.main()
