"""
验证码业务服务模块
生成、发送、校验验证码
"""
import random
import logging
from datetime import datetime
from models.verification_code import VerificationCodeModel
from services.email_service import send_verification_code_email
from config import get_config

config = get_config()
verification_code_model = VerificationCodeModel()
logger = logging.getLogger(__name__)


class VerificationError(Exception):
    """验证码业务异常"""
    def __init__(self, message: str, code: int, http_status: int = 400):
        self.message = message
        self.code = code
        self.http_status = http_status
        super().__init__(self.message)


def _generate_code() -> str:
    """生成6位随机数字验证码"""
    return ''.join(str(random.randint(0, 9)) for _ in range(config.VERIFICATION_CODE_LENGTH))


def send_code(email: str, purpose: str) -> dict:
    """
    发送验证码
    参数:
        email: 邮箱
        purpose: 'login' 或 'register'
    返回:
        dict: {'message': '...', 'expires_in': 300}
    异常:
        VerificationError: 发送过于频繁 / 超过每日上限
    """
    # 1. 检查60秒内是否已发送
    last_seconds = verification_code_model.latest_send_time(email)
    if last_seconds is not None and last_seconds < config.VERIFICATION_CODE_SEND_WINDOW:
        remaining = config.VERIFICATION_CODE_SEND_WINDOW - last_seconds
        raise VerificationError(
            f'发送过于频繁，请 {remaining} 秒后再试',
            3008, 429
        )

    # 2. 检查每日发送上限
    today_count = verification_code_model.count_today(email)
    if today_count >= config.VERIFICATION_CODE_DAILY_LIMIT:
        raise VerificationError(
            '今日验证码发送次数已达上限，请明天再试',
            3008, 429
        )

    # 3. 生成验证码
    code = _generate_code()

    # 4. 保存到数据库
    verification_code_model.save(email, code, purpose)

    # 5. 发送邮件
    success = send_verification_code_email(email, code, purpose)
    if not success:
        logger.error(f'验证码邮件发送失败: email={email}, purpose={purpose}')
        raise VerificationError(
            '验证码发送失败，请稍后重试',
            5001, 500
        )

    logger.info(f'验证码已发送: email={email}, purpose={purpose}')

    return {
        'message': '验证码已发送',
        'expires_in': config.VERIFICATION_CODE_EXPIRE,
    }


def verify_code(email: str, code: str, purpose: str) -> bool:
    """
    校验验证码
    参数:
        email: 邮箱
        code: 验证码
        purpose: 'login' 或 'register'
    返回:
        bool: True 表示验证通过
    """
    return verification_code_model.verify(email, code, purpose)