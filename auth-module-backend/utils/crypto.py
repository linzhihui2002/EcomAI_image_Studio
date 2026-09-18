"""
加密工具模块
提供 SHA-256 哈希和 AES-256-CBC 加密/解密功能，用于邀请码安全存储
"""
import hashlib
import base64
import os as _os


def hash_sha256(text: str) -> str:
    """计算文本的 SHA-256 哈希值，返回 64 位 hex 字符串"""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def aes_encrypt(plaintext: str, key: str) -> str:
    """
    AES-256-CBC 加密

    参数:
        plaintext: 原始明文
        key: 加密密钥（任意长度字符串）

    返回:
        base64 编码的密文（格式：base64(iv + ciphertext)）
    """
    try:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import pad
    except ImportError:
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.primitives.padding import PKCS7
            from cryptography.hazmat.backends import default_backend
            return _aes_encrypt_cryptography(plaintext, key)
        except ImportError:
            return _aes_encrypt_fallback(plaintext, key)

    key_bytes = _derive_key(key)
    iv = _os.urandom(16)
    cipher = AES.new(key_bytes, AES.MODE_CBC, iv)
    ciphertext = cipher.encrypt(pad(plaintext.encode('utf-8'), AES.block_size))
    return base64.b64encode(iv + ciphertext).decode('utf-8')


def aes_decrypt(ciphertext_b64: str, key: str) -> str:
    """
    AES-256-CBC 解密

    参数:
        ciphertext_b64: base64 编码的密文
        key: 加密密钥

    返回:
        原始明文
    """
    try:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad
    except ImportError:
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.primitives.padding import PKCS7
            from cryptography.hazmat.backends import default_backend
            return _aes_decrypt_cryptography(ciphertext_b64, key)
        except ImportError:
            return _aes_decrypt_fallback(ciphertext_b64, key)

    key_bytes = _derive_key(key)
    raw = base64.b64decode(ciphertext_b64)
    iv = raw[:16]
    ciphertext = raw[16:]
    cipher = AES.new(key_bytes, AES.MODE_CBC, iv)
    plaintext = unpad(cipher.decrypt(ciphertext), AES.block_size)
    return plaintext.decode('utf-8')


# ---- cryptography 降级实现 ----

def _aes_encrypt_cryptography(plaintext: str, key: str) -> str:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7
    from cryptography.hazmat.backends import default_backend

    key_bytes = _derive_key(key)
    iv = _os.urandom(16)
    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    padder = PKCS7(128).padder()
    padded = padder.update(plaintext.encode('utf-8')) + padder.finalize()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(iv + ciphertext).decode('utf-8')


def _aes_decrypt_cryptography(ciphertext_b64: str, key: str) -> str:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7
    from cryptography.hazmat.backends import default_backend

    key_bytes = _derive_key(key)
    raw = base64.b64decode(ciphertext_b64)
    iv = raw[:16]
    ciphertext = raw[16:]
    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()
    return plaintext.decode('utf-8')


# ---- 纯标准库回退实现 ----

def _aes_encrypt_fallback(plaintext: str, key: str) -> str:
    """使用纯标准库的简单加密回退（建议安装 pycryptodome）"""
    import struct
    key_bytes = _derive_key(key)
    iv = _os.urandom(16)
    ciphertext = _xor_encrypt(plaintext.encode('utf-8'), key_bytes, iv)
    return base64.b64encode(iv + ciphertext).decode('utf-8')


def _aes_decrypt_fallback(ciphertext_b64: str, key: str) -> str:
    """使用纯标准库的简单解密回退"""
    key_bytes = _derive_key(key)
    raw = base64.b64decode(ciphertext_b64)
    iv = raw[:16]
    ciphertext = raw[16:]
    plaintext_bytes = _xor_encrypt(ciphertext, key_bytes, iv)
    return plaintext_bytes.decode('utf-8')


def _xor_encrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    """XOR 流加密（回退方案，建议安装 pycryptodome 获得真正的 AES）"""
    result = bytearray(len(data))
    key_stream = hashlib.sha256(key + iv).digest()
    for i in range(len(data)):
        result[i] = data[i] ^ key_stream[i % len(key_stream)]
    return bytes(result)


# ---- 辅助函数 ----

def _derive_key(key: str) -> bytes:
    """从任意长度字符串派生 32 字节 AES-256 密钥"""
    return hashlib.sha256(key.encode('utf-8')).digest()