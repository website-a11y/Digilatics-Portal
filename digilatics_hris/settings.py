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
    "digilatics_hris.middleware.BlockAdminForNonSuperusers",
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
                "attendance.context_processors.display_timezone",
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
TIME_ZONE = "America/New_York"  # Eastern Time (ET)
USE_I18N = True
USE_TZ = True
TIME_FORMAT = "g:i A"   # 12-hour display (e.g. 9:30 AM) across admin and templates
DATETIME_FORMAT = "d M Y, g:i A"

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
            "filename": str(BASE_DIR / "zkteco_debug.log"),
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
    "device_timezone": "Asia/Karachi",  # Physical clock timezone of the ZKTeco device (PKT = UTC+5)
}

# Stray device enrollment IDs with no real employee — their punches are dropped
# silently during ADMS sync instead of being logged as "unmapped".
ZK_IGNORED_DEVICE_IDS = [713, 113]

# ONE-TIME HISTORICAL RECOVERY: when set to a "YYYY-MM-DD" string, every device
# poll sends a wide DATA QUERY from that date and tells the device to re-send all
# stored punches. Set this to pull history, then set back to None once the audit
# confirms the data is in (otherwise the device re-dumps everything every minute).
# Use the "Fetch Latest" button in the attendance admin to trigger a one-off re-fetch.
ZK_FETCH_FROM = None
