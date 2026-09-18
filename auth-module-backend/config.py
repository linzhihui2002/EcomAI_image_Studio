"""
应用配置文件
集中管理数据库连接、JWT、邮件服务、限流等配置
"""
import os
from datetime import timedelta
from dotenv import load_dotenv

# 加载 .env 文件（必须在读取环境变量之前）
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))


class Config:
    """应用配置基类

    所有敏感项（密钥、密码、邮箱授权码）一律通过环境变量注入，
    代码内不保留任何真实凭据。下方默认值仅供本地开发占位，
    生产环境必须通过环境变量覆盖。
    """
    # Flask 配置
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-only-change-me-flask-secret')

    # MySQL 数据库配置
    MYSQL_HOST = os.environ.get('MYSQL_HOST', 'localhost')
    MYSQL_PORT = int(os.environ.get('MYSQL_PORT', 3306))
    MYSQL_USER = os.environ.get('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD', '')
    MYSQL_DATABASE = os.environ.get('MYSQL_DATABASE', 'ecomai_auth')

    # JWT 配置
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'dev-only-change-me-jwt-secret')
    JWT_ALGORITHM = 'HS256'
    JWT_EXPIRATION = timedelta(hours=24)

    # 邮件服务配置 (SMTP)
    SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.qq.com')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 465))
    SMTP_USE_SSL = os.environ.get('SMTP_USE_SSL', 'true').lower() in ('1', 'true', 'yes')
    SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
    SMTP_FROM_NAME = os.environ.get('SMTP_FROM_NAME', 'EcomAI Studio')

    # 限流配置
    LOGIN_RATE_LIMIT = 5       # 60秒内最多5次
    REGISTER_RATE_LIMIT = 3    # 60秒内最多3次
    RATE_LIMIT_WINDOW = 60     # 限流窗口（秒）

    # 验证码配置
    VERIFICATION_CODE_LENGTH = 6          # 验证码长度
    VERIFICATION_CODE_EXPIRE = 300        # 验证码有效期（秒），5分钟
    VERIFICATION_CODE_SEND_LIMIT = 1      # 同一邮箱60秒内最多发送1次
    VERIFICATION_CODE_SEND_WINDOW = 60    # 发送限流窗口（秒）
    VERIFICATION_CODE_DAILY_LIMIT = 10    # 同一邮箱每天最多发送10次

    # 邀请码配置
    INVITE_CODE_LENGTH = 10          # 邀请码长度
    INVITE_CODE_EXPIRE_DAYS = 7      # 默认有效期（天）
    INVITE_CODE_MAX_USAGE = 5        # 最大使用次数
    INVITE_CODE_ENCRYPTION_KEY = os.environ.get(
        'INVITE_CODE_ENCRYPTION_KEY',
        'dev-only-change-me-invite-aes-key'
    )

    # 用户自备模型 API Key 加密密钥（与邀请码密钥隔离）
    USER_AI_KEY_ENCRYPTION_KEY = os.environ.get(
        'USER_AI_KEY_ENCRYPTION_KEY',
        'dev-only-change-me-user-ai-aes-key'
    )

    # 密码强度要求
    PASSWORD_MIN_LENGTH = 6
    PASSWORD_REQUIRE_UPPER = False
    PASSWORD_REQUIRE_DIGIT = False
    PASSWORD_REQUIRE_SPECIAL = False

    # 多语言/多站点字典目录（站点语言映射、场景环境映射等 JSON 配置）
    SITE_DICT_PATH = os.environ.get(
        'SITE_DICT_PATH',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'dictionaries')
    )

    # AI 视觉合规审查开关（批量链路生成后自动审查）
    COMPLIANCE_REVIEW_ENABLED = os.environ.get('COMPLIANCE_REVIEW_ENABLED', 'true').lower() in ('1', 'true', 'yes')


class DevelopmentConfig(Config):
    """开发环境配置"""
    DEBUG = True


class ProductionConfig(Config):
    """生产环境配置"""
    DEBUG = False


class TestingConfig(Config):
    """测试环境配置"""
    TESTING = True
    MYSQL_DATABASE = 'ecomai_auth_test'


# 配置映射
config_map = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig,
}


class AIConfig:
    """AI 模型配置"""
    # LLM 文本模型配置
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'qwen3.6-plus')
    LLM_API_BASE = os.environ.get('LLM_API_BASE', '')
    LLM_API_KEY = os.environ.get('LLM_API_KEY', '')

    # 多模态模型配置
    MULTIMODAL_MODEL_NAME = os.environ.get('MULTIMODAL_MODEL_NAME', 'qwen3.5-omni-plus')
    MULTIMODAL_API_BASE = os.environ.get('MULTIMODAL_API_BASE', '')
    MULTIMODAL_API_KEY = os.environ.get('MULTIMODAL_API_KEY', '')

    # 图像生成模型配置
    IMAGE_GEN_MODEL_NAME = os.environ.get('IMAGE_GEN_MODEL_NAME', 'gpt-image-2')
    IMAGE_GEN_API_BASE = os.environ.get('IMAGE_GEN_API_BASE', '')
    IMAGE_GEN_API_KEY = os.environ.get('IMAGE_GEN_API_KEY', '')
    IMAGE_GEN_MAX_RETRIES = int(os.environ.get('IMAGE_GEN_MAX_RETRIES', 2))
    IMAGE_GEN_TIMEOUT = int(os.environ.get('IMAGE_GEN_TIMEOUT', 300))

    # LLM 调用重试配置
    LLM_MAX_RETRIES = int(os.environ.get('LLM_MAX_RETRIES', 2))

    # MinerU 文档解析配置
    MINERU_TOKEN = os.environ.get('MINERU_TOKEN', '')

    # 多模态 API 调用配置
    MULTIMODAL_TIMEOUT = int(os.environ.get('MULTIMODAL_TIMEOUT', 300))      # 单次请求超时（秒），默认 300
    MULTIMODAL_MAX_RETRIES = int(os.environ.get('MULTIMODAL_MAX_RETRIES', 2)) # 最大重试次数，默认 2

    # 生图计划分析配置
    ANALYSIS_CACHE_TTL = int(os.environ.get('ANALYSIS_CACHE_TTL', 3600))
    FILE_UPLOAD_MAX_SIZE = int(os.environ.get('FILE_UPLOAD_MAX_SIZE', 52428800))
    CHUNK_SIZE = int(os.environ.get('CHUNK_SIZE', 5242880))


def get_config(env=None):
    """获取配置实例"""
    if env is None:
        env = os.environ.get('FLASK_ENV', 'default')
    return config_map.get(env, config_map['default'])()