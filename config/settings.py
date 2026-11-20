"""Configuración local; ninguna migración Django toca la base de negocio."""
import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
RUNTIME_DIR = BASE_DIR / '.runtime'
RUNTIME_DIR.mkdir(exist_ok=True)
CACHES = {
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
    'provider_quotas': {
        'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
        'LOCATION': str(RUNTIME_DIR / 'provider-quotas'),
    },
}
_secret_file = RUNTIME_DIR / 'django-secret'
if not os.environ.get('DJANGO_SECRET_KEY') and not _secret_file.exists():
    try:
        with _secret_file.open('x', encoding='utf-8') as f:
            f.write(secrets.token_urlsafe(64))
    except FileExistsError:
        pass
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY') or _secret_file.read_text(encoding='utf-8')
_previous_secret = os.environ.get('DJANGO_SECRET_KEY_FALLBACK', '')
SECRET_KEY_FALLBACKS = [_previous_secret] if _previous_secret and _previous_secret != SECRET_KEY else []
DEBUG = False
HTTPS_ONLY = os.environ.get('DJANGO_HTTPS', 'true').lower() != 'false'
ALLOWED_HOSTS = [host.strip().lower() for host in os.environ.get(
    'DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1]'
).split(',') if host.strip()]
INSTALLED_APPS = ['django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles', 'postal']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware', 'postal.middleware.LocalSecurityMiddleware', 'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.request', 'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages']}}]
WSGI_APPLICATION = 'config.wsgi.application'
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': RUNTIME_DIR / 'accounts.sqlite3', 'OPTIONS': {'timeout': 30}}}
AUTH_PASSWORD_VALIDATORS = [{'NAME': 'django.contrib.auth.password_validation.' + name} for name in ('UserAttributeSimilarityValidator', 'MinimumLengthValidator', 'CommonPasswordValidator', 'NumericPasswordValidator')]
LANGUAGE_CODE = 'es'
TIME_ZONE = 'America/La_Paz'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / '.static'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Strict'
SESSION_COOKIE_SECURE = HTTPS_ONLY
CSRF_COOKIE_SECURE = HTTPS_ONLY
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 28800
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_SSL_REDIRECT = HTTPS_ONLY
SECURE_HSTS_SECONDS = 31536000 if HTTPS_ONLY else 0
LOGIN_ACCOUNT_LIMIT = 5
LOGIN_RATE_WINDOW = 15 * 60
QUERY_RATE_WINDOW = 60
QUERY_RATE_LIMITS = {'chat': 3, 'tracking': 30, 'dashboard': 20}
QUERY_CONCURRENCY_PER_KIND = 2
DATA_MODE = os.environ.get('DATA_MODE', 'demo')
BUSINESS_DATABASE_URL = os.environ.get('BUSINESS_DATABASE_URL', '')
BUSINESS_USE_ISOLATED_VIEWS = os.environ.get('BUSINESS_USE_ISOLATED_VIEWS', '0') == '1'
BUSINESS_ADMIN_DATABASE_URL = os.environ.get('BUSINESS_ADMIN_DATABASE_URL', '')
BUSINESS_READONLY_PASSWORD = os.environ.get('BUSINESS_READONLY_PASSWORD', '')
BACKUP_PATH = os.environ.get('BACKUP_PATH', r'D:\edwin\Documents\correos\backapsiop\backapsiop.sql')
PG_BIN = os.environ.get('PG_BIN', r'D:\Program Files\PostgreSQL\bin')
# Windows can block wheel DLLs. Let psycopg fall back to the installed libpq.
if os.name == 'nt' and (Path(PG_BIN) / 'libpq.dll').is_file():
    os.environ['PATH'] = PG_BIN + os.pathsep + os.environ.get('PATH', '')
    _postgres_dll_directory = os.add_dll_directory(PG_BIN)
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_BACKUP_API_KEY = os.environ.get('GROQ_BACKUP_API_KEY', '')
GROQ_MODEL = 'openai/gpt-oss-120b'
GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
OPENROUTER_MODEL = 'nvidia/nemotron-3.5-super-vl:free'
AI_PROVIDER = os.environ.get('AI_PROVIDER', 'groq').lower()
NVIDIA_API_KEY = os.environ.get('NVIDIA_API_KEY', '')
NVIDIA_MODEL = os.environ.get('NVIDIA_MODEL', '')
CLOUDFLARE_API_TOKEN = os.environ.get('CLOUDFLARE_API_TOKEN', '')
CLOUDFLARE_ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID', '')
CLOUDFLARE_MODEL = os.environ.get('CLOUDFLARE_MODEL', '@cf/meta/llama-3.1-8b-instruct-fp8-fast')
RESULT_DIR = RUNTIME_DIR / 'results'
RESULT_TTL_HOURS = 24
JOBS_EAGER = False
DATA_UPLOAD_MAX_MEMORY_SIZE = 4 * 1024 * 1024
CSRF_FAILURE_VIEW = 'postal.views.csrf_failure'
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'ai_console': {'class': 'logging.StreamHandler', 'level': 'INFO'}},
    'loggers': {'postal.ai': {'handlers': ['ai_console'], 'level': 'INFO', 'propagate': False}},
}
