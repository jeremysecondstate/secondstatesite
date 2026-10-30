import os
import sys
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
if len(sys.argv) < 2 or sys.argv[1] != "test":
    load_dotenv(BASE_DIR / ".env", override=False)

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-change-me")
DEBUG = os.environ.get("DEBUG", "false").strip().lower() in {"1", "true", "yes", "on"}
ALLOWED_HOSTS = os.environ.get(
    "ALLOWED_HOSTS",
    "localhost,127.0.0.1"
).split(",")
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "secondstateapp.apps.SecondstateappConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise right after SecurityMiddleware
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Recommended WhiteNoise storage for cache-busted files
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/
ROOT_URLCONF = 'secondstate.urls'
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates']
        ,
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]
WSGI_APPLICATION = 'secondstate.wsgi.application'
# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
db_kwargs = dict(conn_max_age=600)
# Only enforce SSL for Postgres (Render)
if DATABASE_URL.startswith("postgres"):
    db_kwargs["ssl_require"] = not DEBUG
DATABASES = {
    "default": dj_database_url.parse(DATABASE_URL, **db_kwargs)
}
# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]
# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
CALENDAR_TIME_ZONE = os.environ.get("CALENDAR_TIME_ZONE", "America/Los_Angeles")
SECONDSTATE_PUBLIC_URL = os.environ.get("SECONDSTATE_PUBLIC_URL", "https://secondstate.art").rstrip("/")
AUCTION_EMAIL_SENDING_ENABLED = os.environ.get("AUCTION_EMAIL_SENDING_ENABLED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
AUCTION_EMAIL_SENDER = os.environ.get("AUCTION_EMAIL_SENDER", "jeremy@secondstate.art")
AUCTION_EMAIL_RECIPIENT_JEREMY = os.environ.get("AUCTION_EMAIL_RECIPIENT_JEREMY", "")
AUCTION_EMAIL_RECIPIENT_OLIVER = os.environ.get("AUCTION_EMAIL_RECIPIENT_OLIVER", "")
AUCTION_EMAIL_RECIPIENT_ALEX = os.environ.get("AUCTION_EMAIL_RECIPIENT_ALEX", "")
GOOGLE_GMAIL_CLIENT_ID = os.environ.get("GOOGLE_GMAIL_CLIENT_ID", "")
GOOGLE_GMAIL_CLIENT_SECRET = os.environ.get("GOOGLE_GMAIL_CLIENT_SECRET", "")
GOOGLE_GMAIL_REFRESH_TOKEN = os.environ.get("GOOGLE_GMAIL_REFRESH_TOKEN", "")
MEDIA_URL = "/media/"
MEDIA_ROOT = Path("/var/data/media")   # <-- inside your Render disk mount
# WHITENOISE_ALLOW_ALL_ORIGINS = True
# WHITENOISE_ROOT = BASE_DIR / "media"
# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/
