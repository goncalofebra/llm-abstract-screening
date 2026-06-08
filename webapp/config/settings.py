"""
Configuracao Django do web app de screening.

Uso local, 1 utilizador, SQLite, sem login. Carrega as chaves de API a partir
de pipeline/.env e poe o pipeline/ no sys.path para importar screening_core.
"""

from __future__ import annotations

import sys
from pathlib import Path

# webapp/  ->  GIC/
BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
PIPELINE_DIR = PROJECT_ROOT / "pipeline"

# Permite "import screening_core" (modulo partilhado em pipeline/).
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

# Carrega pipeline/.env (OPENAI_API_KEY, DEEPSEEK_API_KEY, GROQ_API_KEY, ...).
try:
    from dotenv import load_dotenv
    load_dotenv(PIPELINE_DIR / ".env")
except Exception:  # noqa: BLE001 - dotenv opcional
    pass

# Chave de dev fixa: aplicacao e' local e single-user.
SECRET_KEY = "django-insecure-gic-screening-local-dev-key-change-if-deployed"
DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0", "[::1]"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "screening",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 30},
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "pt-pt"
TIME_ZONE = "Europe/Lisbon"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Limite de upload generoso (corpora podem ter milhares de abstracts).
DATA_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024  # 100 MB
DATA_UPLOAD_MAX_NUMBER_FIELDS = None

# Email opcional para a NCBI E-utilities (boa pratica; nao obrigatorio).
import os  # noqa: E402

NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")
NCBI_EMAIL = os.getenv("NCBI_EMAIL", "")
