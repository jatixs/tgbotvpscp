from tortoise import fields, models
from core.config import CIPHER_SUITE
import json
import time


class EncryptedTextField(fields.TextField):

    def to_db_value(self, value, instance):
        if value is None:
            return None
        try:
            return CIPHER_SUITE.encrypt(str(value).encode()).decode()
        except Exception:
            return value

    def to_python_value(self, value):
        if value is None:
            return None
        try:
            return CIPHER_SUITE.decrypt(str(value).encode()).decode()
        except Exception:
            return value


class Node(models.Model):
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

    class Meta:
        table = "nodes"
