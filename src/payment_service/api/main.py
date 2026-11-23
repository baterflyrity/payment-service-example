"""Совместимость: приложение собрано в ``entrypoints/api/app.py``.

Путь ``payment_service.api.main:app`` используется Dockerfile и compose;
перенос точки входа — в T09.
"""

from payment_service.entrypoints.api.app import app

__all__ = ["app"]
