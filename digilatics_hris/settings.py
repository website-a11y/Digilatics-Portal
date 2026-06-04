from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "django-insecure-mtag16*2xsg+!%uimjbxctzm$(9uwia!e186zbf170!lw6t)d0"
DEBUG = True
ALLOWED_HOSTS = ["*"]

# Allow same-origin iframes (used for edit popups in admin)
X_FRAME_OPTIONS = "SAMEORIGIN"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Your apps
    "accounts.apps.AccountsConfig",
    "leaves.apps.LeavesConfig",
    "teams.apps.TeamsConfig",
    "salary.apps.SalaryConfig",
    "attendance.apps.AttendanceConfig",
    "portal.apps.PortalConfig",
]

MIDDLEWARE = [
    "digilatics_hris.middleware.ZKTecoRequestLogger",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "digilatics_hris.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "digilatics_hris.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Karachi"  # Pakistani timezone (GMT+5)
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Email (Gmail SMTP) ────────────────────────────────────────────────────────
EMAIL_BACKEND    = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST       = "smtp.gmail.com"
EMAIL_PORT       = 587
EMAIL_USE_TLS    = True
EMAIL_HOST_USER  = "website@digilatics.com"
EMAIL_HOST_PASSWORD = "vvwp smqk qkpd dcgk" 
DEFAULT_FROM_EMAIL = "Digilatics HR <website@digilatics.com>"

# HOW TO GET A GMAIL APP PASSWORD:
# 1. Go to myaccount.google.com → Security → 2-Step Verification (must be ON)
# 2. Search "App passwords" → create one for "Mail"
# 3. Paste the 16-character code above (spaces optional, e.g. "abcd efgh ijkl mnop")

# ── Authentication ────────────────────────────────────────────────────────────
LOGIN_URL = "admin:login"
LOGIN_REDIRECT_URL = "admin:index"
LOGOUT_REDIRECT_URL = "admin:login"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
        "zkteco_file": {
            "class": "logging.FileHandler",
            "filename": BASE_DIR / "zkteco_debug.log",
            "encoding": "utf-8",
        },
    },
    "loggers": {
        "attendance": {
            "handlers": ["console", "zkteco_file"],
            "level": "DEBUG",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console", "zkteco_file"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}

# ── ZKTeco Biometric Device (SenseFace M2F-LR) ───────────────────────────────
ZK_DEVICE = {
    "host": "10.11.0.101",     # SenseFace M2F-LR device IP
    "port": 4370,
    "timeout": 30,
    "password": 0,
    "force_udp": False,        # Use TCP (device does not respond on UDP)
    "ommit_ping": True,        # Skip ping check
}
