from pathlib import Path
import configparser
import os


# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_project_config():
    config_dir = os.path.join(BASE_DIR, 'config')
    os.makedirs(config_dir, exist_ok=True)
    cfg_path = os.path.join(config_dir, 'config.cfg')
    parser = configparser.ConfigParser(inline_comment_prefixes=(';', '#'))
    parser.read(cfg_path, encoding='utf-8')
    return parser


_PROJECT_CONFIG = _load_project_config()


def _config_value(name, fallback=None):
    if _PROJECT_CONFIG.has_option('app', name):
        return _PROJECT_CONFIG.get('app', name)
    return fallback


def _config_bool(name, fallback=False):
    value = _config_value(name, fallback)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _config_int(name, fallback):
    try:
        return int(_config_value(name, fallback))
    except Exception:
        return int(fallback)



# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.10/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = _config_value('SECRET_KEY', '#+m+r2vq)0fy2r((-=g4(m3betkfhj7ax5hbwf34v^+fb(kb8g')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = _config_bool('DEBUG', False)

ALLOWED_HOSTS = [host.strip() for host in str(_config_value('ALLOWED_HOSTS', '*')).split(',') if host.strip()]

# Trusted origins for CSRF when serving the site via HTTPS or a proxy.
# Add your external domain and port used by the browser (scheme + host[:port]).
# Example: https://ftcdstudio.com:4500
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in str(_config_value('CSRF_TRUSTED_ORIGINS')).split(',') if origin.strip()]

# Django upload limits. For large files behind a reverse proxy, the proxy still
# needs its own client_max_body_size / max_request_body_size configuration.
DATA_UPLOAD_MAX_MEMORY_SIZE = _config_int('DATA_UPLOAD_MAX_MEMORY_SIZE', 200 * 1024 * 1024)
FILE_UPLOAD_MAX_MEMORY_SIZE = _config_int('FILE_UPLOAD_MAX_MEMORY_SIZE', 5368709120)

# When the site is served behind a reverse proxy that terminates TLS, enable
# the following so Django knows the original request was secure. Adjust header
# name if your proxy uses a different one (most use X-Forwarded-Proto).
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# 如果生产环境使用 HTTPS，建议启用安全 Cookie
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # 添加项目应用index
    'index'
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'CRCFiles.middleware.RequestLoggingMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'CRCFiles.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]


WSGI_APPLICATION = 'CRCFiles.wsgi.application'



MYSQL_HOST = os.environ.get('MYSQL_HOST', '127.0.0.1')
MYSQL_PORT = os.environ.get('MYSQL_PORT', '3306')
MYSQL_DATABASE = os.environ.get('MYSQL_DATABASE')
MYSQL_USER = os.environ.get('MYSQL_USER')
MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD')

if MYSQL_DATABASE and MYSQL_USER:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': MYSQL_DATABASE,
            'USER': MYSQL_USER,
            'PASSWORD': MYSQL_PASSWORD or '',
            'HOST': MYSQL_HOST,
            'PORT': MYSQL_PORT,
            'OPTIONS': {
                'charset': 'utf8mb4',
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
        }
    }


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



LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True




DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
# 配置文件数据的临时存放文件夹
FILE_UPLOAD_TEMP_DIR = os.path.join(BASE_DIR, 'temp')
# 设置文件上存的处理过程
FILE_UPLOAD_HANDLERS = ['CRCFiles.handler.myFileUploadHandler']
# # 默认配置
# FILE_UPLOAD_HANDLERS = (
#     "django.core.files.uploadhandler.MemoryFileUploadHandler",
#     "django.core.files.uploadhandler.TemporaryFileUploadHandler",)

if DEBUG:
    STATIC_URL = '/static/'
    STATICFILES_DIRS = [
        os.path.join(BASE_DIR, "static")
    ]
else:
    STATIC_URL = '/static/'
    STATIC_ROOT = os.path.join(BASE_DIR, "static")

# Media 配置：项目根下的 media 文件夹
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
# 日志目录
LOG_ROOT = os.path.join(BASE_DIR, 'log')
# 用于生成和校验 media 访问签名的密钥（生产环境请设置环境变量）
MEDIA_ACCESS_SECRET = _config_value('MEDIA_ACCESS_SECRET', os.environ.get('MEDIA_ACCESS_SECRET', SECRET_KEY))
# 用于删除操作的固定密码，生产环境建议通过环境变量设置
DELETE_PASSWORD = _config_value('DELETE_PASSWORD', os.environ.get('DELETE_PASSWORD', 'admin'))
# 登录与删除操作防暴力破解保护：连续错误次数达到后按 IP 锁定等待
AUTH_PROTECT_MAX_FAILS = _config_int('AUTH_PROTECT_MAX_FAILS', os.environ.get('AUTH_PROTECT_MAX_FAILS', '5'))
AUTH_PROTECT_LOCK_SECONDS = _config_int('AUTH_PROTECT_LOCK_SECONDS', os.environ.get('AUTH_PROTECT_LOCK_SECONDS', '60'))
# 访客人脸识别次数阈值；超过该值后当天封禁
GUEST_FACE_BLOCK_THRESHOLD = _config_int('GUEST_FACE_BLOCK_THRESHOLD', 2)
# 是否启用登录验证；false 则查询和预览时不再强制登录
ENABLE_LOGIN_VERIFICATION = _config_bool('ENABLE_LOGIN_VERIFICATION', True)
# 是否启用上传功能；false 则视频/照片上传入口被禁用
ENABLE_UPLOAD = _config_bool('ENABLE_UPLOAD', True)
