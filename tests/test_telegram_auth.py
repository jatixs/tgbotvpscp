import base64
import json
import os
import sys
import time
import types
import unittest
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils as crypto_utils

os.environ.setdefault("DATA_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("TG_BOT_TOKEN", "123456789:TEST_BOT_TOKEN")
os.environ.setdefault("TG_ADMIN_ID", "12345")

modules_to_mock = [
    "aiohttp", "aiohttp.web",
    "argon2", "argon2.exceptions",
    "aiosqlite",
    "requests",
    "PIL", "PIL.Image",
    "qrcode",
    "aiogram", "aiogram.types", "aiogram.exceptions",
    "netifaces", "psutil", "sentry_sdk", "yaml", "docker", "asyncssh", "tortoise",
]

for m in modules_to_mock:
    if m not in sys.modules:
        mod = MagicMock()
        mod.__path__ = []
        mod.__spec__ = types.SimpleNamespace(name=m, origin=None, submodule_search_locations=[])
        sys.modules[m] = mod

from core.web.auth import verify_telegram_id_token


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _int_to_b64(val: int) -> str:
    length = (val.bit_length() + 7) // 8
    return _b64url_encode(val.to_bytes(length, "big"))


class TelegramAuthTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # Generate RSA test key pair
        cls.rsa_private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        cls.rsa_pub_numbers = cls.rsa_private_key.public_key().public_numbers()
        cls.rsa_jwk = {
            "kid": "test-rsa-1",
            "kty": "RSA",
            "alg": "RS256",
            "n": _int_to_b64(cls.rsa_pub_numbers.n),
            "e": _int_to_b64(cls.rsa_pub_numbers.e),
        }

        # Generate EC test key pair (P-256)
        cls.ec_private_key = ec.generate_private_key(ec.SECP256R1())
        cls.ec_pub_numbers = cls.ec_private_key.public_key().public_numbers()
        cls.ec_jwk = {
            "kid": "test-es-1",
            "kty": "EC",
            "alg": "ES256",
            "crv": "P-256",
            "x": _int_to_b64(cls.ec_pub_numbers.x),
            "y": _int_to_b64(cls.ec_pub_numbers.y),
        }

        cls.mock_jwks = {
            "test-rsa-1": cls.rsa_jwk,
            "test-es-1": cls.ec_jwk,
        }

    def _create_rsa_token(self, claims: dict, kid: str = "test-rsa-1") -> str:
        header = {"alg": "RS256", "kid": kid}
        hdr_b64 = _b64url_encode(json.dumps(header).encode("utf-8"))
        pay_b64 = _b64url_encode(json.dumps(claims).encode("utf-8"))
        signing_input = f"{hdr_b64}.{pay_b64}".encode("ascii")
        sig = self.rsa_private_key.sign(
            signing_input,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return f"{hdr_b64}.{pay_b64}.{_b64url_encode(sig)}"

    def _create_ec_token(self, claims: dict, kid: str = "test-es-1") -> str:
        header = {"alg": "ES256", "kid": kid}
        hdr_b64 = _b64url_encode(json.dumps(header).encode("utf-8"))
        pay_b64 = _b64url_encode(json.dumps(claims).encode("utf-8"))
        signing_input = f"{hdr_b64}.{pay_b64}".encode("ascii")
        der_sig = self.ec_private_key.sign(
            signing_input,
            ec.ECDSA(hashes.SHA256()),
        )
        r, s = crypto_utils.decode_dss_signature(der_sig)
        raw_sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        return f"{hdr_b64}.{pay_b64}.{_b64url_encode(raw_sig)}"

    async def test_valid_rsa_token(self):
        claims = {
            "iss": "https://oauth.telegram.org",
            "aud": "123456789",
            "id": 987654321,
            "name": "Test User",
            "preferred_username": "testuser",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        token = self._create_rsa_token(claims)
        with patch("core.web.auth.fetch_telegram_jwks", return_value=self.mock_jwks):
            result = await verify_telegram_id_token(token, expected_client_id="123456789")
            self.assertIsNotNone(result)
            self.assertEqual(result["id"], 987654321)
            self.assertEqual(result["preferred_username"], "testuser")

    async def test_valid_es256_token(self):
        claims = {
            "iss": "https://oauth.telegram.org",
            "aud": "123456789",
            "id": 987654321,
            "name": "Test User",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        token = self._create_ec_token(claims)
        with patch("core.web.auth.fetch_telegram_jwks", return_value=self.mock_jwks):
            result = await verify_telegram_id_token(token, expected_client_id="123456789")
            self.assertIsNotNone(result)
            self.assertEqual(result["id"], 987654321)

    async def test_expired_token_rejected(self):
        claims = {
            "iss": "https://oauth.telegram.org",
            "aud": "123456789",
            "id": 987654321,
            "exp": int(time.time()) - 300,
            "iat": int(time.time()) - 600,
        }
        token = self._create_rsa_token(claims)
        with patch("core.web.auth.fetch_telegram_jwks", return_value=self.mock_jwks):
            result = await verify_telegram_id_token(token, expected_client_id="123456789")
            self.assertIsNone(result)

    async def test_wrong_issuer_rejected(self):
        claims = {
            "iss": "https://evil.oauth.example.com",
            "aud": "123456789",
            "id": 987654321,
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        token = self._create_rsa_token(claims)
        with patch("core.web.auth.fetch_telegram_jwks", return_value=self.mock_jwks):
            result = await verify_telegram_id_token(token, expected_client_id="123456789")
            self.assertIsNone(result)

    async def test_wrong_audience_rejected(self):
        claims = {
            "iss": "https://oauth.telegram.org",
            "aud": "999999999",
            "id": 987654321,
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        token = self._create_rsa_token(claims)
        with patch("core.web.auth.fetch_telegram_jwks", return_value=self.mock_jwks):
            result = await verify_telegram_id_token(token, expected_client_id="123456789")
            self.assertIsNone(result)

    async def test_tampered_payload_rejected(self):
        claims = {
            "iss": "https://oauth.telegram.org",
            "aud": "123456789",
            "id": 987654321,
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        token = self._create_rsa_token(claims)
        parts = token.split(".")
        # Tamper payload
        tampered_claims = dict(claims, id=111111111)
        tampered_payload = _b64url_encode(json.dumps(tampered_claims).encode("utf-8"))
        tampered_token = f"{parts[0]}.{tampered_payload}.{parts[2]}"

        with patch("core.web.auth.fetch_telegram_jwks", return_value=self.mock_jwks):
            result = await verify_telegram_id_token(tampered_token, expected_client_id="123456789")
            self.assertIsNone(result)

    def test_login_template_hides_id_link_in_telegram_only_mode(self):
        try:
            from jinja2 import Environment, FileSystemLoader, select_autoescape
        except ImportError:
            with open("core/templates/login.html", "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("{% if telegram_only_mode %}hidden{% endif %}", content)
            self.assertIn("TELEGRAM_ONLY_MODE = {{ 'true' if telegram_only_mode else 'false' }};", content)
            return

        env = Environment(
            loader=FileSystemLoader("core/templates"),
            autoescape=select_autoescape(["html", "xml"]),
        )
        template = env.get_template("login.html")

        # When telegram_only_mode is True:
        rendered_true = template.render(
            current_lang="ru",
            web_title="Title",
            cache_ver="1",
            pwa_version="1",
            asset_ver="1",
            i18n_json="{}",
            bot_username="testbot",
            tg_client_id="123456789",
            telegram_only_mode=True,
            web_key_js="",
            web_toggle_perf_mode="",
            web_toggle_a11y_mode="",
            login_via_telegram_btn="Telegram",
            login_or_id_link="Или войти по ID (Magic Link)",
            login_telegram_id_label="ID",
            login_or_tg_button="",
            web_brand_name="Brand",
            is_default_pass=False,
            web_default_pass_alert="",
        )
        self.assertIn('id="switch-to-id-btn" onclick="toggleTelegramLoginMode(\'id\')" class="hidden', rendered_true)
        self.assertIn('const TELEGRAM_ONLY_MODE = true;', rendered_true)

        # When telegram_only_mode is False:
        rendered_false = template.render(
            current_lang="ru",
            web_title="Title",
            cache_ver="1",
            pwa_version="1",
            asset_ver="1",
            i18n_json="{}",
            bot_username="testbot",
            tg_client_id="123456789",
            telegram_only_mode=False,
            web_key_js="",
            web_toggle_perf_mode="",
            web_toggle_a11y_mode="",
            login_via_telegram_btn="Telegram",
            login_or_id_link="Или войти по ID (Magic Link)",
            login_telegram_id_label="ID",
            login_or_tg_button="",
            web_brand_name="Brand",
            is_default_pass=False,
            web_default_pass_alert="",
        )
        self.assertNotIn('id="switch-to-id-btn" onclick="toggleTelegramLoginMode(\'id\')" class="hidden', rendered_false)
        self.assertIn('const TELEGRAM_ONLY_MODE = false;', rendered_false)

    def test_cookie_path_and_samesite(self):
        from core.web.auth import _set_session_cookie, _set_csrf_cookie, COOKIE_NAME, CSRF_TOKEN_COOKIE

        mock_resp = MagicMock()
        mock_req = MagicMock()
        mock_req.scheme = "https"
        mock_req.headers = {}

        _set_session_cookie(mock_resp, request=mock_req, session_token="test_tok", max_age=3600)
        mock_resp.set_cookie.assert_called_with(
            COOKIE_NAME,
            "test_tok",
            max_age=3600,
            path="/",
            httponly=True,
            secure=True,
            samesite="Lax",
        )

        _set_csrf_cookie(mock_resp, mock_req, token="test_csrf")
        mock_resp.set_cookie.assert_called_with(
            CSRF_TOKEN_COOKIE,
            "test_csrf",
            max_age=3600,
            path="/",
            secure=True,
            httponly=False,
            samesite="Lax",
        )


if __name__ == "__main__":
    unittest.main()
