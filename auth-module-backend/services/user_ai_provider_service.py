"""用户自备模型服务商（BYOK）服务层

负责用户自备第三方模型服务商（Bring Your Own Key）相关的业务能力，按下列分区组织，
后续任务会在同一文件内继续追加内容：

1. 安全校验：validate_api_base —— 校验并规范化用户填写的 API Base，拒绝内网/保留地址（防 SSRF）。
2. Key 加解密：encrypt_key / decrypt_key / mask_key —— API Key 落库加密、读取解密与展示掩码。
3. 通道配置 CRUD：list_providers / create_provider / update_provider / delete_provider /
   move_provider / test_provider / get_settings / set_use_own_provider。
4. 通道解析与号池：resolve_channel / iter_channel_entries（用户未启用自备通道时回退平台通道）。
5. 失败上报：report_entry_failure / report_entry_success（统计写库失败绝不影响主业务）。
6. 计费判定：get_feature_categories / is_feature_byok / calculate_effective_cost。
"""
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

from config import get_config, AIConfig
from models.user_ai_provider import UserAiProviderModel, UserAiSettingsModel
from utils.crypto import aes_encrypt, aes_decrypt

# 云元数据服务地址，显式拒绝
_METADATA_HOST = '169.254.169.254'

# 代理 fake-ip 模式（Clash/mihomo 等）会把所有域名解析为 198.18.0.0/15 假 IP，
# 实际连接由代理截获并转发到真实地址，不构成 SSRF 风险，需放行
_FAKE_IP_NETWORK = ipaddress.ip_network('198.18.0.0/15')

# 无端口时按协议补全的默认端口
_DEFAULT_PORTS = {'http': 80, 'https': 443}


# ========== 安全校验 ==========

class UserAiProviderError(Exception):
    """用户自备模型配置相关业务异常"""
    def __init__(self, message: str, code: int = 4001, http_status: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status


def _is_forbidden_ip(ip) -> bool:
    """判断单个解析出的 IP 是否为内网/保留地址"""
    if ip in _FAKE_IP_NETWORK:
        return False
    if str(ip) == _METADATA_HOST:
        return True
    if (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified):
        return True
    # IPv6 站点本地地址（IPv4Address 无该属性）
    return bool(getattr(ip, 'is_site_local', False))


def validate_api_base(api_base: str) -> str:
    """校验并规范化用户填写的 API Base，返回去掉尾部斜杠的结果。
    非法时抛 UserAiProviderError（中文提示）。
    """
    # 1. 必须是非空字符串，且以 http:// 或 https:// 开头（大小写不敏感）
    if not isinstance(api_base, str) or not api_base.strip():
        raise UserAiProviderError('API 地址必须以 http:// 或 https:// 开头')
    api_base = api_base.strip()
    if not api_base.lower().startswith(('http://', 'https://')):
        raise UserAiProviderError('API 地址必须以 http:// 或 https:// 开头')

    # 2. 必须能解析出主机名
    try:
        parsed = urlsplit(api_base)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise UserAiProviderError('API 地址格式无效')
    if not hostname:
        raise UserAiProviderError('API 地址格式无效')

    # 3. 无端口时按协议给默认端口
    if port is None:
        port = _DEFAULT_PORTS.get(parsed.scheme.lower(), 80)

    # 4. 解析域名/IP，任意一个结果为内网或保留地址即拒绝
    try:
        addr_infos = socket.getaddrinfo(hostname, port)
    except socket.gaierror:
        raise UserAiProviderError('API 地址域名无法解析，请检查后重试')
    for info in addr_infos:
        if _is_forbidden_ip(ipaddress.ip_address(info[4][0])):
            raise UserAiProviderError('API 地址不允许指向内网或保留地址')

    # 5. 校验通过，返回规范化结果
    return api_base.strip().rstrip('/')


# ========== Key 加解密 ==========

def encrypt_key(plaintext: str) -> str:
    """使用 utils.crypto.aes_encrypt 与 config.USER_AI_KEY_ENCRYPTION_KEY 加密 API Key"""
    return aes_encrypt(plaintext, get_config().USER_AI_KEY_ENCRYPTION_KEY)


def decrypt_key(ciphertext: str) -> str:
    """解密 API Key；解密失败时抛 UserAiProviderError"""
    try:
        return aes_decrypt(ciphertext, get_config().USER_AI_KEY_ENCRYPTION_KEY)
    except Exception:
        raise UserAiProviderError('API Key 解密失败，请重新填写', 5001, 500)


def mask_key(plaintext: str) -> str:
    """返回掩码，形如 'sk-a****wxyz'：长度<=8 时返回 '****'；否则前4位 + '****' + 后4位"""
    if not plaintext:
        return ''
    if len(plaintext) <= 8:
        return '****'
    return f'{plaintext[:4]}****{plaintext[-4:]}'


# ========== 通道配置 CRUD ==========

CATEGORY_IMAGE_GEN = 'image_gen'
CATEGORY_MULTIMODAL = 'multimodal'
CATEGORY_LLM = 'llm'
CATEGORIES = (CATEGORY_IMAGE_GEN, CATEGORY_MULTIMODAL, CATEGORY_LLM)

# 字段长度上限（与表结构保持一致）
_NAME_MAX_LENGTH = 64
_MODEL_NAME_MAX_LENGTH = 128
_ERROR_MAX_LENGTH = 500


def _validate_category(category) -> str:
    """校验通道分类合法性，返回原值"""
    if category not in CATEGORIES:
        raise UserAiProviderError('模型分类无效')
    return category


def _validate_name(name) -> str:
    """校验配置名称（去空白后非空且 <= 64 字符）"""
    text = name.strip() if isinstance(name, str) else ''
    if not text or len(text) > _NAME_MAX_LENGTH:
        raise UserAiProviderError('配置名称不能为空且不超过 64 个字符')
    return text


def _validate_model_name(model_name) -> str:
    """校验模型名（去空白后非空且 <= 128 字符）"""
    text = model_name.strip() if isinstance(model_name, str) else ''
    if not text or len(text) > _MODEL_NAME_MAX_LENGTH:
        raise UserAiProviderError('模型名不能为空且不超过 128 个字符')
    return text


def _require_provider(provider_id, user_id) -> dict:
    """按主键 + 所属用户取通道（越权防护），不存在时抛 4004"""
    row = UserAiProviderModel().find_by_id_and_user(provider_id, user_id)
    if not row:
        raise UserAiProviderError('配置不存在', code=4004, http_status=404)
    return row


def _to_time_str(value):
    """时间字段统一输出字符串；None 保持 None"""
    return None if value is None else str(value)


def _to_priority(value) -> int:
    """priority 缺省按 0 处理，保证排序不因 None 报错"""
    return 0 if value is None else int(value)


def _provider_to_dict(row: dict) -> dict:
    """把数据库行转换为对外条目字典（屏蔽明文 Key 与密文）"""
    cipher = row.get('api_key_cipher')
    if cipher:
        try:
            api_key_masked = mask_key(decrypt_key(cipher))
        except Exception:
            api_key_masked = '****'
    else:
        api_key_masked = '****'

    last_test_ok = row.get('last_test_ok')
    return {
        'id': row.get('id'),
        'category': row.get('category'),
        'name': row.get('name'),
        'api_base': row.get('api_base'),
        'api_key_masked': api_key_masked,
        'model_name': row.get('model_name'),
        'priority': _to_priority(row.get('priority')),
        'is_enabled': bool(row.get('is_enabled')),
        'last_test_ok': None if last_test_ok is None else bool(last_test_ok),
        'last_test_at': _to_time_str(row.get('last_test_at')),
        'last_test_error': row.get('last_test_error'),
        'last_used_at': _to_time_str(row.get('last_used_at')),
        'failure_count': row.get('failure_count') or 0,
        'last_error': row.get('last_error'),
        'created_at': _to_time_str(row.get('created_at')),
        'updated_at': _to_time_str(row.get('updated_at')),
    }


def list_providers(user_id) -> dict:
    """返回该用户全部自备通道与总开关

    返回 {'use_own_provider': bool, 'items': [provider_dict, ...]}，
    items 按 category 顺序 image_gen/multimodal/llm 分组、组内按 priority ASC, id ASC
    """
    rows = UserAiProviderModel().list_by_user(user_id) or []
    order = {category: index for index, category in enumerate(CATEGORIES)}
    rows = sorted(
        rows,
        key=lambda row: (
            order.get(row.get('category'), len(CATEGORIES)),
            _to_priority(row.get('priority')),
            row.get('id') or 0,
        )
    )
    enabled = UserAiSettingsModel().is_own_provider_enabled(user_id)
    return {
        'use_own_provider': bool(enabled),
        'items': [_provider_to_dict(row) for row in rows],
    }


def create_provider(user_id, category, name, api_base, api_key, model_name) -> dict:
    """新增一条自备通道，返回对外条目字典"""
    category = _validate_category(category)
    name = _validate_name(name)
    model_name = _validate_model_name(model_name)
    api_base = validate_api_base(api_base)
    if not isinstance(api_key, str) or not api_key.strip():
        raise UserAiProviderError('API Key 不能为空')

    row = UserAiProviderModel().create(
        user_id, category, name, api_base, encrypt_key(api_key.strip()), model_name
    )
    return _provider_to_dict(row)


def update_provider(user_id, provider_id, **fields) -> dict:
    """更新一条自备通道（仅更新传入字段；api_key 为空时保留原 Key），返回对外条目字典"""
    _require_provider(provider_id, user_id)

    payload = {}
    if fields.get('name') is not None:
        payload['name'] = _validate_name(fields['name'])
    if fields.get('model_name') is not None:
        payload['model_name'] = _validate_model_name(fields['model_name'])
    if fields.get('api_base') is not None:
        payload['api_base'] = validate_api_base(fields['api_base'])
    api_key = fields.get('api_key')
    if isinstance(api_key, str) and api_key.strip():
        payload['api_key_cipher'] = encrypt_key(api_key.strip())
    if fields.get('is_enabled') is not None:
        payload['is_enabled'] = 1 if fields['is_enabled'] else 0

    updated = UserAiProviderModel().update(provider_id, user_id, payload)
    if updated is None:
        updated = _require_provider(provider_id, user_id)
    return _provider_to_dict(updated)


def delete_provider(user_id, provider_id) -> None:
    """删除一条自备通道（越权/不存在时抛 4004）"""
    _require_provider(provider_id, user_id)
    UserAiProviderModel().delete(provider_id, user_id)


def move_provider(user_id, provider_id, direction) -> dict:
    """在分类内上移/下移一条自备通道；已是边界时返回当前条目（不报错）"""
    if direction not in ('up', 'down'):
        raise UserAiProviderError('移动方向无效')
    _require_provider(provider_id, user_id)

    UserAiProviderModel().move(provider_id, user_id, direction)
    return _provider_to_dict(_require_provider(provider_id, user_id))


def test_provider(user_id, provider_id) -> dict:
    """向 {api_base}/models 发起 GET 连通性测试，结果落库并返回 {'ok','error','tested_at'}"""
    row = _require_provider(provider_id, user_id)

    ok = False
    error = None
    try:
        api_base = validate_api_base(row.get('api_base'))
        api_key = decrypt_key(row.get('api_key_cipher'))
    except UserAiProviderError as exc:
        error = str(exc.message)[:_ERROR_MAX_LENGTH]
    else:
        try:
            response = requests.get(
                f'{api_base}/models',
                headers={'Authorization': f'Bearer {api_key}'},
                timeout=15,
            )
            if 200 <= response.status_code < 300:
                ok = True
            else:
                error = f'HTTP {response.status_code}: {str(response.text)[:_ERROR_MAX_LENGTH]}'
        except requests.exceptions.Timeout:
            error = '连接超时'
        except requests.exceptions.RequestException as exc:
            error = str(exc)[:_ERROR_MAX_LENGTH]
        except Exception as exc:
            error = str(exc)[:_ERROR_MAX_LENGTH]

    updated = UserAiProviderModel().update_test_result(provider_id, ok, error)
    tested_at = _to_time_str(updated.get('last_test_at')) if updated else None
    return {'ok': ok, 'error': error, 'tested_at': tested_at}


def get_settings(user_id) -> dict:
    """返回该用户自备通道总开关 {'use_own_provider': bool}"""
    row = UserAiSettingsModel().get_or_create(user_id)
    return {'use_own_provider': bool(row.get('use_own_provider')) if row else False}


def set_use_own_provider(user_id, enabled) -> dict:
    """设置自备通道总开关，返回 {'use_own_provider': bool}"""
    row = UserAiSettingsModel().set_use_own_provider(user_id, enabled)
    return {'use_own_provider': bool(row.get('use_own_provider')) if row else False}


# ========== 通道解析与号池 ==========

@dataclass
class ChannelEntry:
    api_base: str
    api_key: str
    model_name: str
    provider_id: int = None      # None 表示平台通道
    name: str = ''               # 备注名；平台通道为 '平台默认'


def _platform_entry(category) -> ChannelEntry:
    """构造平台默认通道条目（取值与现有业务代码逐字节一致）"""
    if category == CATEGORY_MULTIMODAL:
        return ChannelEntry(
            api_base=AIConfig.MULTIMODAL_API_BASE or 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            api_key=AIConfig.MULTIMODAL_API_KEY or 'sk-placeholder',
            model_name=AIConfig.MULTIMODAL_MODEL_NAME,
            provider_id=None,
            name='平台默认',
        )
    if category == CATEGORY_LLM:
        return ChannelEntry(
            api_base=AIConfig.LLM_API_BASE or 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            api_key=AIConfig.LLM_API_KEY or 'sk-placeholder',
            model_name=AIConfig.LLM_MODEL_NAME,
            provider_id=None,
            name='平台默认',
        )
    # 默认按生图通道处理
    return ChannelEntry(
        api_base=(AIConfig.IMAGE_GEN_API_BASE or 'https://api.qiuqiutoken.com/v1').rstrip('/'),
        api_key=AIConfig.IMAGE_GEN_API_KEY or 'sk-placeholder',
        model_name=AIConfig.IMAGE_GEN_MODEL_NAME,
        provider_id=None,
        name='平台默认',
    )


def _platform_result(category) -> dict:
    """平台单条通道结果"""
    return {'source': 'platform', 'entries': [_platform_entry(category)]}


def resolve_channel(user_id, category) -> dict:
    """解析某分类下应使用的通道号池

    返回 {'source': 'user'|'platform', 'entries': [ChannelEntry, ...]}。
    用户未开启总开关、该分类下无启用条目、或查库异常时，一律回退为平台单条通道。
    """
    if not user_id:
        return _platform_result(category)

    try:
        if not UserAiSettingsModel().is_own_provider_enabled(user_id):
            return _platform_result(category)
        rows = UserAiProviderModel().list_enabled_by_user_category(user_id, category) or []
    except Exception as exc:
        print(f'[resolve_channel] 查询用户自备通道失败，回退平台通道: '
              f'user_id={user_id}, category={category}, error={exc}', flush=True)
        return _platform_result(category)

    if not rows:
        return _platform_result(category)

    entries = []
    for row in rows:
        try:
            api_key = decrypt_key(row.get('api_key_cipher'))
        except Exception as exc:
            print(f'[resolve_channel] 自备通道 Key 解密失败，已跳过该条: '
                  f'user_id={user_id}, category={category}, provider_id={row.get("id")}, '
                  f'error={exc}', flush=True)
            continue
        entries.append(ChannelEntry(
            api_base=row.get('api_base') or '',
            api_key=api_key,
            model_name=row.get('model_name') or '',
            provider_id=row.get('id'),
            name=row.get('name') or '',
        ))

    if not entries:
        return _platform_result(category)
    return {'source': 'user', 'entries': entries}


def iter_channel_entries(user_id, category):
    """按号池顺序逐个产出 ChannelEntry；用户未启用自备通道时只产出 1 条平台条目"""
    for entry in resolve_channel(user_id, category)['entries']:
        yield entry


# ========== 失败上报 ==========

def report_entry_failure(provider_id, error) -> None:
    """上报一次调用失败（provider_id 为 None 表示平台通道，不做任何事）"""
    if not provider_id:
        return
    error_text = None if error is None else str(error)[:_ERROR_MAX_LENGTH]
    try:
        UserAiProviderModel().update_stats(provider_id, False, error_text)
    except Exception as exc:
        print(f'[report_entry_failure] 统计写库失败（已忽略）: provider_id={provider_id}, error={exc}',
              flush=True)


def report_entry_success(provider_id) -> None:
    """上报一次调用成功（provider_id 为 None 表示平台通道，不做任何事）"""
    if not provider_id:
        return
    try:
        UserAiProviderModel().update_stats(provider_id, True)
    except Exception as exc:
        print(f'[report_entry_success] 统计写库失败（已忽略）: provider_id={provider_id}, error={exc}',
              flush=True)


# ========== 计费判定 ==========

FEATURE_CHANNEL_MAP = {
    'toolbox.text_to_image': frozenset({CATEGORY_IMAGE_GEN}),
    'toolbox.image_merge': frozenset({CATEGORY_IMAGE_GEN, CATEGORY_MULTIMODAL}),
    'toolbox.chat_gen': frozenset({CATEGORY_IMAGE_GEN, CATEGORY_MULTIMODAL}),
    'toolbox.product_replace': frozenset({CATEGORY_IMAGE_GEN, CATEGORY_MULTIMODAL}),
    'toolbox.ai_model': frozenset({CATEGORY_IMAGE_GEN}),
    'toolbox.model_product': frozenset({CATEGORY_IMAGE_GEN, CATEGORY_MULTIMODAL}),
    'toolbox.plan_analysis': frozenset({CATEGORY_MULTIMODAL}),
    'toolbox.prompt_reverse': frozenset({CATEGORY_MULTIMODAL}),
    'ai_product_image.smart_mode': frozenset({CATEGORY_IMAGE_GEN, CATEGORY_MULTIMODAL}),
    'ai_product_image.pro_mode': frozenset({CATEGORY_IMAGE_GEN, CATEGORY_MULTIMODAL, CATEGORY_LLM}),
    'ai_product_image.batch': frozenset({CATEGORY_IMAGE_GEN, CATEGORY_MULTIMODAL}),
}
DEFAULT_FEATURE_CATEGORIES = frozenset({CATEGORY_IMAGE_GEN})


def get_feature_categories(feature_key) -> set:
    """返回 feature_key 对应的通道分类集合；未命中映射时返回默认集合"""
    return set(FEATURE_CHANNEL_MAP.get(feature_key, DEFAULT_FEATURE_CATEGORIES))


def is_feature_byok(user_id, feature_key) -> bool:
    """判断该功能是否完全走用户自备通道（总开关开启，且功能涉及的全部分类下都存在启用条目）"""
    if not user_id:
        return False

    try:
        if not UserAiSettingsModel().is_own_provider_enabled(user_id):
            return False
        rows = UserAiProviderModel().list_enabled_by_user(user_id) or []
        enabled_categories = {row.get('category') for row in rows}
        return get_feature_categories(feature_key) <= enabled_categories
    except Exception as exc:
        # 查库异常时安全降级：视为未自备，照常扣费
        print(f'[is_feature_byok] 查询自备通道失败，按未自备处理: '
              f'user_id={user_id}, feature_key={feature_key}, error={exc}', flush=True)
        return False


def calculate_effective_cost(user_id, feature_key) -> int:
    """计算实际应扣灵感币：命中自备通道返回 0，否则返回平台原价"""
    from services.feature_pricing_service import calculate_per_use_cost

    if is_feature_byok(user_id, feature_key):
        return 0
    return calculate_per_use_cost(feature_key)
