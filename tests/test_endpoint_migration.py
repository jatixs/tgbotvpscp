import unittest

from node.endpoint_migration import validate_https_migration_url


class EndpointMigrationTests(unittest.TestCase):
    def test_migration_preserves_ip_and_accepts_new_https_port(self):
        self.assertEqual(
            validate_https_migration_url("http://1.2.3.4:8080", "https://1.2.3.4:8443"),
            "https://1.2.3.4:8443",
        )

    def test_migration_preserves_dns_host(self):
        self.assertEqual(
            validate_https_migration_url("http://Panel.Example.com:8080", "https://panel.example.com"),
            "https://panel.example.com",
        )

    def test_migration_rejects_changed_host_and_non_https(self):
        for advertised in ("https://attacker.example", "http://1.2.3.4:8443"):
            with self.subTest(advertised=advertised), self.assertRaises(ValueError):
                validate_https_migration_url("http://1.2.3.4:8080", advertised)

    def test_migration_rejects_path_and_credentials(self):
        for advertised in ("https://1.2.3.4/path", "https://user@1.2.3.4"):
            with self.subTest(advertised=advertised), self.assertRaises(ValueError):
                validate_https_migration_url("http://1.2.3.4:8080", advertised)


if __name__ == "__main__":
    unittest.main()