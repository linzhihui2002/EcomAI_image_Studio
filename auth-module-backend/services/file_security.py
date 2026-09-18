"""
文件安全验证服务
提供文件类型、扩展名、文件大小等安全校验功能
"""
import os
from config import AIConfig

# MIME 类型到扩展名的映射
_MIME_TO_EXTENSIONS = {
    'image/png': {'.png'},
    'image/jpeg': {'.jpg', '.jpeg'},
    'image/jpg': {'.jpg', '.jpeg'},
    'image/gif': {'.gif'},
    'image/bmp': {'.bmp'},
    'image/webp': {'.webp'},
    'text/plain': {'.txt'},
    'text/markdown': {'.md', '.markdown'},
    'application/json': {'.json'},
    'application/pdf': {'.pdf'},
    'application/msword': {'.doc'},
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': {'.docx'},
    'application/vnd.ms-powerpoint': {'.ppt'},
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': {'.pptx'},
    'application/vnd.ms-excel': {'.xls'},
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': {'.xlsx'},
}

# 危险扩展名列表
_DANGEROUS_EXTENSIONS = {
    '.exe', '.bat', '.cmd', '.sh', '.bash', '.js',
    '.vbs', '.ps1', '.com', '.dll', '.msi', '.scr', '.pif',
}


def validate_file_type(filename: str, mime_type: str) -> tuple:
    """
    验证文件扩展名与 MIME 类型是否匹配

    Args:
        filename: 文件名
        mime_type: 文件的 MIME 类型

    Returns:
        (True, "") 验证通过
        (False, "中文错误信息") 验证失败
    """
    _, ext = os.path.splitext(filename)
    ext = ext.lower()

    if mime_type not in _MIME_TO_EXTENSIONS:
        return False, f"不支持的文件类型：{mime_type}"

    allowed_extensions = _MIME_TO_EXTENSIONS[mime_type]
    if ext not in allowed_extensions:
        return False, f"文件扩展名 {ext} 与声明的文件类型 {mime_type} 不匹配"

    return True, ""


def is_dangerous_extension(filename: str) -> tuple:
    """
    检查文件扩展名是否属于危险类型

    Args:
        filename: 文件名

    Returns:
        (True, "中文错误信息") 文件扩展名危险
        (False, "") 文件扩展名安全
    """
    _, ext = os.path.splitext(filename)
    ext = ext.lower()

    if ext in _DANGEROUS_EXTENSIONS:
        return True, f"不允许上传的文件类型：{ext}"

    return False, ""


def validate_file_size(file_size: int, max_size: int = None) -> tuple:
    """
    验证文件大小是否超过限制

    Args:
        file_size: 文件大小（字节）
        max_size: 最大允许的文件大小（字节），为 None 时使用 AIConfig.FILE_UPLOAD_MAX_SIZE

    Returns:
        (True, "") 验证通过
        (False, "文件大小超过限制（最大 XX MB）") 验证失败
    """
    if max_size is None:
        max_size = AIConfig.FILE_UPLOAD_MAX_SIZE

    if file_size > max_size:
        max_mb = max_size / (1024 * 1024)
        return False, f"文件大小超过限制（最大 {max_mb:.0f} MB）"

    return True, ""