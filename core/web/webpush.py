"""
Web Push Notification module (RFC 8291, RFC 8292).
Handles VAPID keypair management, payload encryption (aes128gcm),
and async HTTP delivery to browser push services (FCM, Apple APNs, Mozilla).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from urllib.parse import urlparse

import aiohttp
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .. import config
from ..i18n import STRINGS, get_text as _, get_user_lang
from ..models import WebPushSubscription

logger = logging.getLogger("webpush")

# Cache in-memory VAPID keys
_VAPID_CACHE: dict[str, str] = {}


def b64url_encode(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def b64url_decode(data: str) -> bytes:
    """Base64url decode with automatic padding correction."""
    pad = 4 - (len(data) % 4)
    if pad != 4:
        data += "=" * pad
    return base64.urlsafe_b64decode(data)


def generate_vapid_keypair() -> tuple[str, str]:
    """
    Generate standard NIST P-256 (secp256r1) keypair for VAPID.
    Returns (private_key_b64url, public_key_b64url).
    """
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = priv.public_key()
    pub_bytes = pub.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    priv_num = priv.private_numbers().private_value
    priv_bytes = priv_num.to_bytes(32, byteorder="big")
    return b64url_encode(priv_bytes), b64url_encode(pub_bytes)


async def get_or_create_vapid_keys() -> tuple[str, str]:
    """
    Retrieve existing VAPID keys from env or bot_config, or generate and persist new ones.
    Returns (private_key_b64url, public_key_b64url).
    """
    global _VAPID_CACHE
    if _VAPID_CACHE.get("private_key") and _VAPID_CACHE.get("public_key"):
        return _VAPID_CACHE["private_key"], _VAPID_CACHE["public_key"]

    # 1. Check environment variables
    env_priv = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    env_pub = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    if env_priv and env_pub:
        _VAPID_CACHE = {"private_key": env_priv, "public_key": env_pub}
        return env_priv, env_pub

    # 2. Check bot.db bot_config
    saved = await config.get_bot_config("webpush_vapid", {})
    if isinstance(saved, dict) and saved.get("private_key") and saved.get("public_key"):
        _VAPID_CACHE = saved
        return saved["private_key"], saved["public_key"]

    # 3. Generate new keypair and persist
    logger.info("Generating new VAPID keypair for Web Push...")
    priv_b64, pub_b64 = generate_vapid_keypair()
    new_keys = {"private_key": priv_b64, "public_key": pub_b64}
    await config.set_bot_config("webpush_vapid", new_keys)
    _VAPID_CACHE = new_keys
    logger.info("✅ VAPID keypair created and saved to bot config.")
    return priv_b64, pub_b64


async def get_vapid_public_key() -> str:
    """Return the active VAPID public key (base64url encoded)."""
    _, pub_key = await get_or_create_vapid_keys()
    return pub_key


def encrypt_payload(payload: str | bytes, client_p256dh: str, client_auth: str) -> bytes:
    """
    Encrypt message payload using RFC 8291 (Message Encryption for Web Push)
    with aes128gcm Content-Encoding.
    """
    if isinstance(payload, str):
        payload_bytes = payload.encode("utf-8")
    else:
        payload_bytes = payload

    client_pub_bytes = b64url_decode(client_p256dh)
    auth_secret = b64url_decode(client_auth)

    client_pub_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), client_pub_bytes)

    # Server ephemeral ECDH keypair
    server_priv = ec.generate_private_key(ec.SECP256R1())
    server_pub = server_priv.public_key()
    server_pub_bytes = server_pub.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )

    # Compute shared secret
    shared_secret = server_priv.exchange(ec.ECDH(), client_pub_key)

    # IKM derivation (RFC 8291 section 3.2)
    auth_info = b"WebPush: info\x00" + client_pub_bytes + server_pub_bytes
    ikm = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=auth_secret,
        info=auth_info,
    ).derive(shared_secret)

    salt = os.urandom(16)

    # CEK & Nonce (RFC 8188 / RFC 8291)
    cek = HKDF(
        algorithm=hashes.SHA256(),
        length=16,
        salt=salt,
        info=b"Content-Encoding: aes128gcm\x00",
    ).derive(ikm)

    nonce = HKDF(
        algorithm=hashes.SHA256(),
        length=12,
        salt=salt,
        info=b"Content-Encoding: nonce\x00",
    ).derive(ikm)

    # Pad payload with delimiter \x02 (final record)
    padded = payload_bytes + b"\x02"

    cipher = Cipher(algorithms.AES(cek), modes.GCM(nonce))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize() + encryptor.tag

    # Header: salt (16 bytes) + record_size (4 bytes big-endian) + idlen (1 byte) + server_pub_bytes (65 bytes)
    rs_bytes = (4096).to_bytes(4, byteorder="big")
    idlen_byte = bytes([len(server_pub_bytes)])

    return salt + rs_bytes + idlen_byte + server_pub_bytes + ciphertext


def create_vapid_headers(endpoint: str, priv_key_b64: str, pub_key_b64: str) -> dict[str, str]:
    """
    Build RFC 8292 VAPID Authorization header (ES256 signed JWT).
    """
    parsed = urlparse(endpoint)
    audience = f"{parsed.scheme}://{parsed.netloc}"

    claims = {
        "aud": audience,
        "exp": int(time.time()) + 43200,  # 12 hours
        "sub": "mailto:admin@localhost",
    }

    header_json = json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode("utf-8")
    claims_json = json.dumps(claims, separators=(",", ":")).encode("utf-8")

    signing_input = f"{b64url_encode(header_json)}.{b64url_encode(claims_json)}".encode("ascii")

    # Load private key from raw 32 bytes
    priv_bytes = b64url_decode(priv_key_b64)
    priv_num = int.from_bytes(priv_bytes, byteorder="big")
    priv_key = ec.derive_private_key(priv_num, ec.SECP256R1())

    der_sig = priv_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der_sig)
    raw_sig = r.to_bytes(32, byteorder="big") + s.to_bytes(32, byteorder="big")

    jwt = f"{signing_input.decode('ascii')}.{b64url_encode(raw_sig)}"

    return {
        "Authorization": f"vapid t={jwt}, k={pub_key_b64}",
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": "86400",
        "Urgency": "normal",
    }


def clean_html_for_push(raw_text: str) -> str:
    """Strip HTML tags and normalize whitespace for push notification body."""
    if not raw_text:
        return ""
    # Replace <br> and </p> with newlines
    text = re.sub(r"(?i)<br\s*/?>", "\n", raw_text)
    text = re.sub(r"(?i)</p>", "\n", text)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Normalize multiple newlines
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


async def send_web_push_notification(
    subscription: WebPushSubscription | dict,
    payload: dict | str,
    session: aiohttp.ClientSession | None = None,
) -> bool:
    """
    Encrypt and deliver a Web Push notification to an endpoint.
    Deletes the subscription if the push service responds with 404 or 410 Gone.
    """
    endpoint = subscription.endpoint if isinstance(subscription, WebPushSubscription) else subscription.get("endpoint")
    p256dh = subscription.p256dh if isinstance(subscription, WebPushSubscription) else subscription.get("p256dh")
    auth = subscription.auth if isinstance(subscription, WebPushSubscription) else subscription.get("auth")

    if not endpoint or not p256dh or not auth:
        logger.warning("Invalid subscription data: missing endpoint, p256dh or auth")
        return False

    payload_str = json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else str(payload)

    try:
        priv_key, pub_key = await get_or_create_vapid_keys()
        encrypted_body = encrypt_payload(payload_str, p256dh, auth)
        headers = create_vapid_headers(endpoint, priv_key, pub_key)

        own_session = session is None
        client = session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))

        try:
            async with client.post(endpoint, data=encrypted_body, headers=headers) as resp:
                if resp.status in (200, 201, 202):
                    return True

                if resp.status in (404, 410):
                    # Subscription expired or app uninstalled
                    logger.info("Web Push subscription expired (HTTP %s). Removing: %s", resp.status, endpoint[:50])
                    try:
                        await WebPushSubscription.filter(endpoint=endpoint).delete()
                    except Exception as exc:
                        logger.warning("Error deleting expired subscription: %s", exc)
                    return False

                resp_body = await resp.text()
                logger.warning("Push service error (HTTP %s): %s", resp.status, resp_body[:200])
                return False
        finally:
            if own_session:
                await client.close()

    except Exception as exc:
        logger.error("Failed to send Web Push notification: %s", exc)
        return False


async def send_web_push_for_alert(
    user_ids: list[int],
    alert_type: str,
    message_or_func,
    node_token: str | None = None,
    kwargs: dict | None = None,
) -> None:
    """
    Send Web Push notifications to all active subscriptions of user_ids.
    Respects user localization and formats title and body appropriately.
    """
    if not user_ids:
        return

    try:
        subscriptions = await WebPushSubscription.filter(user_id__in=user_ids).all()
        if not subscriptions:
            return

        # Group subscriptions by user_id
        subs_by_user: dict[int, list[WebPushSubscription]] = {}
        for sub in subscriptions:
            subs_by_user.setdefault(sub.user_id, []).append(sub)

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            tasks = []
            for uid, user_subs in subs_by_user.items():
                lang = get_user_lang(uid)
                if callable(message_or_func):
                    raw_text = message_or_func(lang)
                else:
                    raw_text = message_or_func
                    if kwargs:
                        try:
                            raw_text = raw_text.format(**kwargs)
                        except Exception as e:
                            logger.debug(f"Failed to format push notification text: {e}")

                body = clean_html_for_push(raw_text)
                title = _resolve_alert_title(alert_type, lang)

                payload = {
                    "title": title,
                    "body": body,
                    "icon": "/static/favicons/android-chrome-192x192.png",
                    "badge": "/static/favicons/favicon-32x32.png",
                    "tag": f"vps-alert-{alert_type}",
                    "data": {
                        "url": "/nodes" if node_token else "/",
                        "alert_type": alert_type,
                        "time": time.time(),
                    },
                }

                for sub in user_subs:
                    tasks.append(send_web_push_notification(sub, payload, session=session))

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                success_count = sum(1 for r in results if r is True)
                logger.info(
                    "Web Push alert [%s] delivered to %d/%d devices for %d user(s).",
                    alert_type,
                    success_count,
                    len(tasks),
                    len(subs_by_user),
                )
    except Exception as exc:
        logger.error("Error dispatching web push alert: %s", exc)


def _resolve_alert_title(alert_type: str, lang: str) -> str:
    """Map alert type to a concise, localized push notification title with emoji."""
    if alert_type == "resources":
        return f"⚠️ {_('notifications_alert_name_res', lang)}"
    elif alert_type == "logins":
        return f"🚨 {_('notifications_alert_name_logins', lang)}"
    elif alert_type == "bans":
        return f"🛡️ {_('notifications_alert_name_bans', lang)}"
    elif alert_type == "node_offline":
        return f"🔌 {_('notifications_alert_name_downtime', lang) if 'notifications_alert_name_downtime' in STRINGS.get(lang, {}) else 'Node Offline'}"
    elif alert_type == "node_online":
        return "🟢 Node Online"
    elif alert_type == "updates":
        return "🚀 System Update"
    return f"🔔 {_('web_brand_name', lang) if 'web_brand_name' in STRINGS.get(lang, {}) else 'TG Bot Panel'}"


async def send_test_push_to_user(user_id: int) -> tuple[int, int]:
    """
    Send a test push notification to all subscriptions of a specific user.
    Returns (success_count, total_count).
    """
    subscriptions = await WebPushSubscription.filter(user_id=user_id).all()
    if not subscriptions:
        return 0, 0

    lang = get_user_lang(user_id)
    test_title = _("web_push_test_title", lang)
    test_body = _("web_push_test_body", lang)

    payload = {
        "title": test_title,
        "body": test_body,
        "icon": "/static/favicons/android-chrome-192x192.png",
        "badge": "/static/favicons/favicon-32x32.png",
        "tag": "vps-test-push",
        "data": {
            "url": "/settings",
            "time": time.time(),
        },
    }

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        tasks = [send_web_push_notification(sub, payload, session=session) for sub in subscriptions]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        success_count = sum(1 for r in results if r is True)
        return success_count, len(subscriptions)
