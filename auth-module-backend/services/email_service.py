"""
邮件服务模块
使用 QQ 邮箱 SMTP 发送邮件
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import get_config

config = get_config()

def send_welcome_email(to_email: str) -> bool:
    """
    发送注册确认邮件
    to_email: 收件人邮箱
    返回: True 发送成功, False 发送失败
    """
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = '欢迎注册 EcomAI Studio！'
        msg['From'] = f'{config.SMTP_FROM_NAME} <{config.SMTP_USERNAME}>'
        msg['To'] = to_email
        
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>欢迎加入 EcomAI Studio！</h2>
            <p>您的账号 <strong>{to_email}</strong> 已成功注册。</p>
            <p>您现在可以登录并开始使用 AI 驱动的跨境电商视觉工作台。</p>
            <p>功能包括：</p>
            <ul>
                <li>AI 商品图生成（Smart Mode / Pro Mode）</li>
                <li>AI 图片编辑工具箱</li>
            </ul>
            <p>如有任何问题，请随时联系我们。</p>
            <br/>
            <p>— EcomAI Studio 团队</p>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))
        
        # 使用 SSL 连接
        server = smtplib.SMTP_SSL(config.SMTP_SERVER, config.SMTP_PORT)
        server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
        server.sendmail(config.SMTP_USERNAME, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f'邮件发送失败: {e}')
        return False


def send_verification_code_email(to_email: str, code: str, purpose: str) -> bool:
    """
    发送验证码邮件
    to_email: 收件人邮箱
    code: 6位验证码
    purpose: 'login' 或 'register'
    返回: True 发送成功, False 发送失败
    """
    purpose_text = '登录' if purpose == 'login' else ('注册' if purpose == 'register' else '重置密码')
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'EcomAI Studio - {purpose_text}验证码'
        msg['From'] = f'{config.SMTP_FROM_NAME} <{config.SMTP_USERNAME}>'
        msg['To'] = to_email

        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f8fafc;">
            <div style="max-width: 480px; margin: 0 auto; background: #ffffff; border-radius: 16px; padding: 40px; box-shadow: 0 4px 24px rgba(0,0,0,0.08);">
                <div style="text-align: center; margin-bottom: 32px;">
                    <h1 style="color: #6C5CE7; margin: 0; font-size: 24px;">EcomAI Studio</h1>
                </div>
                <h2 style="color: #1e293b; font-size: 20px; margin-bottom: 12px;">{purpose_text}验证码</h2>
                <p style="color: #64748b; font-size: 14px; line-height: 1.6; margin-bottom: 24px;">
                    您正在使用邮箱 <strong>{to_email}</strong> 进行{purpose_text}操作，验证码 {config.VERIFICATION_CODE_EXPIRE // 60} 分钟内有效。
                </p>
                <div style="background: #f1f5f9; border-radius: 12px; padding: 20px; text-align: center; margin-bottom: 24px;">
                    <span style="font-size: 32px; font-weight: 700; letter-spacing: 8px; color: #6C5CE7; font-family: 'Courier New', monospace;">{code}</span>
                </div>
                <p style="color: #94a3b8; font-size: 12px; text-align: center;">
                    如果这不是您的操作，请忽略此邮件。
                </p>
            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html_content, 'html', 'utf-8'))

        server = smtplib.SMTP_SSL(config.SMTP_SERVER, config.SMTP_PORT)
        server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
        server.sendmail(config.SMTP_USERNAME, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f'验证码邮件发送失败: {e}')
        return False