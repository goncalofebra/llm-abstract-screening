#!/usr/bin/env python
"""Utilitario de linha de comandos do Django."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Nao foi possivel importar o Django. Tens o ambiente certo ativo "
            "e o Django instalado? (pip install 'Django>=4.2,<5')"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
