import unittest

from core.tls_config import (
    build_certbot_args,
    normalize_identifier,
    parse_public_https_url,
    public_https_url,
    upgrade_legacy_http_url,
)


class TLSConfigTests(unittest.TestCase):
    def test_public_ipv4_uses_short_lived_ip_certificate_profile(self):
        args = build_certbot_args("1.2.3.4", certbot_binary="/opt/certbot/bin/certbot")

        self.assertIn("--ip-address", args)
        self.assertIn("shortlived", args)
        self.assertIn("tgbot-ip-1-2-3-4", args)
        self.assertNotIn("--domain", args)

    def test_dns_name_uses_dns_identifier_without_ip_profile(self):
        args = build_certbot_args("Panel.Example.com", "ops@example.com")

        self.assertIn("--domain", args)
        self.assertIn("panel.example.com", args)
        self.assertNotIn("--ip-address", args)
        self.assertNotIn("shortlived", args)

    def test_https_url_round_trip_with_non_default_port(self):
        url = public_https_url("1.2.3.4", 8443)

        self.assertEqual(url, "https://1.2.3.4:8443")
        self.assertEqual(parse_public_https_url(url), ("ip", "1.2.3.4", 8443, "tgbot-ip-1-2-3-4"))

    def test_http_port_is_reserved_for_acme_challenge(self):
        with self.assertRaises(ValueError):
            public_https_url("1.2.3.4", 80)

    def test_http_or_path_urls_are_rejected(self):
        for value in ("http://1.2.3.4", "https://panel.example.com/path"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_public_https_url(value)

    def test_legacy_agent_url_upgrades_without_changing_host(self):
        self.assertEqual(
            upgrade_legacy_http_url("http://1.2.3.4:8080", 8443),
            "https://1.2.3.4:8443",
        )
        self.assertEqual(
            upgrade_legacy_http_url("http://panel.example.com:8080"),
            "https://panel.example.com",
        )

    def test_legacy_agent_url_rejects_path_and_credentials(self):
        for value in ("http://1.2.3.4/path", "http://user@1.2.3.4:8080"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                upgrade_legacy_http_url(value)

    def test_private_and_invalid_hosts_are_rejected(self):
        for value in (
            "127.0.0.1",
            "192.168.1.10",
            "bad host",
            "-bad.example",
            "localhost",
            "panel.local",
            "999.999.999.999",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_identifier(value)


if __name__ == "__main__":
    unittest.main()