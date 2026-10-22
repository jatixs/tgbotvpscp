import time

from cryptography.fernet import InvalidToken
from tortoise import fields, models

from core.config import CIPHER_SUITE


class EncryptionOperationError(ValueError):
    """Errors that occur during encryption/decryption of database data."""

class EncryptedTextField(fields.TextField):
    """
    Tortoise ORM custom field for transparent encryption of text data.
    Values are encrypted when writing to the database and decrypted when reading.
    """

    def to_db_value(self, value, instance):
        if value is None:
            return None
        try:
            return CIPHER_SUITE.encrypt(str(value).encode("utf-8")).decode("utf-8")
        except Exception as exc:
            raise EncryptionOperationError("Failed to encrypt ORM field value") from exc

    def to_python_value(self, value):
        if value is None:
            return None
        try:
            return CIPHER_SUITE.decrypt(str(value).encode("utf-8")).decode("utf-8")
        except InvalidToken:
            return str(value)
        except Exception as exc:
            raise EncryptionOperationError("Failed to decrypt ORM field value") from exc


class Node(models.Model):
    """
    Node (server) model connected to the master bot.
    Contains configuration info, resource consumption stats, and billing details.
    """
    id = fields.IntField(pk=True)
    token_hash = fields.CharField(max_length=64, unique=True, index=True)
    token_safe = EncryptedTextField()
    name = EncryptedTextField()
    ip = EncryptedTextField()
    created_at = fields.FloatField(default=time.time)
    last_seen = fields.FloatField(default=0)
    stats = fields.JSONField(default=dict)
    history = fields.JSONField(default=list)
    tasks = fields.JSONField(default=list)
    extra_state = fields.JSONField(default=dict)
    is_cloud = fields.BooleanField(default=False)
    provider_name = fields.CharField(max_length=100, null=True)
    next_payment_date = fields.DatetimeField(null=True)
    billing_amount = fields.FloatField(null=True)
    currency = fields.CharField(max_length=10, default="$")
    reminder_enabled = fields.BooleanField(default=False)

    class Meta:
        table = "nodes"


class MetricSample(models.Model):
    """
    Resource history sample for an agent or node.
    res = 0 — raw sample, 60/300 — averaged 1-minute/5-minute buckets.
    rx/tx are stored as speed in bytes per second.
    """
    id = fields.BigIntField(pk=True)
    source = fields.CharField(max_length=32)
    res = fields.SmallIntField(default=0)
    t = fields.IntField()
    cpu = fields.FloatField(default=0)
    ram = fields.FloatField(default=0)
    disk = fields.FloatField(default=0)
    rx = fields.FloatField(default=0)
    tx = fields.FloatField(default=0)

    class Meta:
        table = "metric_samples"
        indexes = (("source", "res", "t"),)


class WebPushSubscription(models.Model):
    """
    Browser / PWA subscription for Web Push notifications.
    Stores push endpoint and cryptographic keys (p256dh, auth).
    """
    id = fields.IntField(pk=True)
    user_id = fields.BigIntField(index=True)
    endpoint = fields.TextField()
    p256dh = fields.TextField()
    auth = fields.TextField()
    user_agent = fields.CharField(max_length=255, null=True)
    created_at = fields.FloatField(default=time.time)

    class Meta:
        table = "web_push_subscriptions"

