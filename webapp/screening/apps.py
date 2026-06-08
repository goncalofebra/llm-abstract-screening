import sys

from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _set_sqlite_pragmas(sender, connection, **kwargs):
    """WAL + synchronous=NORMAL: melhora concorrencia leitor/escritor
    entre o thread de request e o worker de screening em SQLite."""
    if connection.vendor == "sqlite":
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=30000;")


class ScreeningConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "screening"
    verbose_name = "Abstract Screening"

    def ready(self):
        connection_created.connect(_set_sqlite_pragmas)
        # Reconcilia runs orfas (processo morreu a meio: Ctrl+C, crash, autoreload).
        # So no arranque do servidor, para nao tocar na BD durante migrate/makemigrations.
        if "runserver" in sys.argv:
            self._reconcile_orphan_runs()

    @staticmethod
    def _reconcile_orphan_runs():
        try:
            from django.utils import timezone
            from .models import ScreeningRun
            ScreeningRun.objects.filter(
                status__in=[ScreeningRun.PENDING, ScreeningRun.RUNNING]
            ).update(
                status=ScreeningRun.ERROR,
                error="Interrompida por reinicio do servidor.",
                finished_at=timezone.now(),
            )
        except Exception:  # noqa: BLE001 - tabela pode nao existir ainda
            pass
