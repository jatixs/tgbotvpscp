from tortoise import fields, models
from cryptography.fernet import InvalidToken
from core.config import CIPHER_SUITE
import json
import time


class EncryptionOperationError(ValueError):
    """Ошибки, возникающие при шифровании/дешифровании данных в БД."""
    pass

class EncryptedTextField(fields.TextField):
    """
    Пользовательское поле Tortoise ORM для прозрачного шифрования текстовых данных.
    Значения шифруются при записи в БД и расшифровываются при чтении.
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
    Модель узла (сервера), подключенного к мастер-боту.
    Содержит информацию о конфигурации, статистике потребления ресурсов и биллинге.
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
