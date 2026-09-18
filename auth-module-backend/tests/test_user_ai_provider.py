"""用户自备模型服务商（BYOK）安全基础模块测试

覆盖（不依赖外网 DNS / 不连真实 MySQL，全部通过 monkeypatch 伪造）：
- validate_api_base：公网地址通过并去掉尾部斜杠；按协议补全默认端口；非 http(s)、空值、
  无法解析主机名、内网/回环/链路本地（云元数据）/站点本地/组播/保留地址被拒；
  多解析结果中任一为内网即拒绝；域名解析失败时的中文提示
- mask_key：常规掩码 / 长度<=8 / None / 空串
- encrypt_key / decrypt_key：往返一致、密文不等于明文、解密失败抛业务异常
- USER_AI_KEY_ENCRYPTION_KEY 与邀请码密钥隔离
- 通道配置 CRUD：入参校验、掩码输出（不泄露密文/明文）
- 通道解析 resolve_channel / iter_channel_entries：平台回退、按号池顺序、解密失败跳过、
  数据库异常回退
- 失败上报：provider_id 为 None 时不做任何事、写库异常被吞掉
- 计费判定：get_feature_categories / is_feature_byok（混合分类判定） / calculate_effective_cost
- 退款封顶：全部任务失败时退款额 = min(实际预扣, 单价×失败数)，BYOK 预扣为 0 时不退款
"""
import datetime
import asyncio
import os
import socket
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.feature_pricing_service as feature_pricing_service
from config import AIConfig, get_config
from models.generation_task import TaskStatus
from models.user_ai_provider import UserAiProviderModel, UserAiSettingsModel
from services import user_ai_provider_service as svc
from services.user_ai_provider_service import (
    CATEGORIES,
    CATEGORY_IMAGE_GEN,
    CATEGORY_LLM,
    CATEGORY_MULTIMODAL,
    FEATURE_CHANNEL_MAP,
    ChannelEntry,
    UserAiProviderError,
    calculate_effective_cost,
    create_provider,
    decrypt_key,
    encrypt_key,
    get_feature_categories,
    is_feature_byok,
    iter_channel_entries,
    list_providers,
    mask_key,
    resolve_channel,
    update_provider,
    validate_api_base,
)

PUBLIC_IP = '140.82.112.3'

# 真实工作流模块延迟加载（见 _get_workflows），供退款封顶用例直接调用 ARQ 任务执行体
smart_wf = None
pro_wf = None
_WORKFLOWS_LOADED = False


def _get_workflows():
    """延迟导入真实工作流模块（smart_generation / pro_generation）

    全量回归时 test_generation.py 会把 langgraph / workflows.smart_generation 换成
    MagicMock；本文件在测试执行顺序中位于最后，若在模块导入期清除污染会改变其他
    测试文件执行时所见的 sys.modules 状态。因此仅在用例内临时清除污染、导入真实
    模块后立即恢复 sys.modules 原状，模块对象缓存在本模块全局变量中复用。
    """
    global smart_wf, pro_wf, _WORKFLOWS_LOADED
    if not _WORKFLOWS_LOADED:
        _polluted = ('workflows.smart_generation', 'workflows.pro_generation',
                     'langgraph', 'langgraph.graph')
        saved = {name: sys.modules.get(name) for name in _polluted}
        for name in _polluted:
            sys.modules.pop(name, None)
        try:
            from workflows import smart_generation, pro_generation
            smart_wf = smart_generation
            pro_wf = pro_generation
        finally:
            for name, module in saved.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
        _WORKFLOWS_LOADED = True
    return smart_wf, pro_wf


def _fake_addrinfo(addresses, port):
    """构造 getaddrinfo 返回值：(family, type, proto, canonname, sockaddr)"""
    return [
        (socket.AF_INET6 if ':' in addr else socket.AF_INET,
         socket.SOCK_STREAM, 6, '', (addr, port))
        for addr in addresses
    ]


def _patch_dns(monkeypatch, *addresses, captured=None):
    """替换 socket.getaddrinfo，返回伪造的解析结果，避免测试依赖外网"""
    def _fake(hostname, port, *args, **kwargs):
        if captured is not None:
            captured.append((hostname, port))
        return _fake_addrinfo(addresses, port)

    monkeypatch.setattr(socket, 'getaddrinfo', _fake)


# ============================================================
# validate_api_base：出站地址安全校验（防 SSRF）
# ============================================================

class TestValidateApiBase:
    def test_accepts_public_host_and_strips_trailing_slash(self, monkeypatch):
        _patch_dns(monkeypatch, PUBLIC_IP)
        assert validate_api_base('https://api.openai.com/v1') == 'https://api.openai.com/v1'
        assert validate_api_base('https://api.openai.com/v1/') == 'https://api.openai.com/v1'

    def test_scheme_is_case_insensitive(self, monkeypatch):
        _patch_dns(monkeypatch, PUBLIC_IP)
        assert validate_api_base('HTTPS://api.openai.com/v1') == 'HTTPS://api.openai.com/v1'

    def test_default_port_follows_scheme(self, monkeypatch):
        captured = []
        _patch_dns(monkeypatch, PUBLIC_IP, captured=captured)

        validate_api_base('https://api.openai.com/v1')
        validate_api_base('http://api.openai.com/v1')
        validate_api_base('http://api.openai.com:8080/v1')

        assert captured == [
            ('api.openai.com', 443),
            ('api.openai.com', 80),
            ('api.openai.com', 8080),
        ]

    @pytest.mark.parametrize('api_base', ['ftp://x.com', 'not-a-url', '//api.openai.com/v1'])
    def test_rejects_non_http_scheme(self, monkeypatch, api_base):
        def _no_dns(hostname, port, *args, **kwargs):
            raise AssertionError('协议非法不应触发 DNS 解析')

        monkeypatch.setattr(socket, 'getaddrinfo', _no_dns)
        with pytest.raises(UserAiProviderError) as exc:
            validate_api_base(api_base)
        assert exc.value.message == 'API 地址必须以 http:// 或 https:// 开头'
        assert exc.value.code == 4001
        assert exc.value.http_status == 400

    @pytest.mark.parametrize('api_base', ['', '   ', None])
    def test_rejects_empty(self, api_base):
        with pytest.raises(UserAiProviderError) as exc:
            validate_api_base(api_base)
        assert exc.value.message == 'API 地址必须以 http:// 或 https:// 开头'

    @pytest.mark.parametrize('api_base', ['http://', 'http:///v1'])
    def test_rejects_missing_hostname(self, api_base):
        with pytest.raises(UserAiProviderError) as exc:
            validate_api_base(api_base)
        assert exc.value.message == 'API 地址格式无效'

    @pytest.mark.parametrize('api_base,address', [
        ('http://127.0.0.1:8080/v1', '127.0.0.1'),      # 回环
        ('http://169.254.169.254/v1', '169.254.169.254'),  # 云元数据 / 链路本地
        ('http://10.0.0.1/v1', '10.0.0.1'),             # 私有网段
        ('http://172.16.0.1/v1', '172.16.0.1'),         # 私有网段
        ('http://192.168.1.1/v1', '192.168.1.1'),       # 私有网段
        ('http://0.0.0.0/v1', '0.0.0.0'),               # unspecified
        ('http://224.0.0.1/v1', '224.0.0.1'),           # 组播
        ('http://[::1]:8080/v1', '::1'),                # IPv6 回环
        ('http://[fec0::1]/v1', 'fec0::1'),             # IPv6 站点本地
    ])
    def test_rejects_internal_and_reserved_addresses(self, monkeypatch, api_base, address):
        _patch_dns(monkeypatch, address)
        with pytest.raises(UserAiProviderError) as exc:
            validate_api_base(api_base)
        assert exc.value.message == 'API 地址不允许指向内网或保留地址'

    def test_rejects_when_any_resolved_ip_is_internal(self, monkeypatch):
        """DNS 多结果：只要有一个内网地址即拒绝"""
        _patch_dns(monkeypatch, PUBLIC_IP, '10.0.0.1')
        with pytest.raises(UserAiProviderError) as exc:
            validate_api_base('https://api.example.com/v1')
        assert exc.value.message == 'API 地址不允许指向内网或保留地址'

    def test_allows_fake_ip_proxy_addresses(self, monkeypatch):
        """代理 fake-ip 模式（198.18.0.0/15）解析结果应放行，不视为内网地址"""
        _patch_dns(monkeypatch, '198.18.1.58')
        assert validate_api_base('https://api.example.com/v1') == 'https://api.example.com/v1'

    def test_rejects_fake_ip_mixed_with_internal(self, monkeypatch):
        """fake-ip 与真实内网地址混合解析时，仍应因内网地址拒绝"""
        _patch_dns(monkeypatch, '198.18.1.58', '192.168.1.1')
        with pytest.raises(UserAiProviderError) as exc:
            validate_api_base('https://api.example.com/v1')
        assert exc.value.message == 'API 地址不允许指向内网或保留地址'

    def test_rejects_unresolvable_host(self, monkeypatch):
        def _raise(hostname, port, *args, **kwargs):
            raise socket.gaierror('name or service not known')

        monkeypatch.setattr(socket, 'getaddrinfo', _raise)
        with pytest.raises(UserAiProviderError) as exc:
            validate_api_base('https://no-such-host.invalid/v1')
        assert exc.value.message == 'API 地址域名无法解析，请检查后重试'


# ============================================================
# mask_key：API Key 掩码
# ============================================================

class TestMaskKey:
    def test_normal_mask(self):
        assert mask_key('sk-abcdefghijklmnop') == 'sk-a****mnop'

    @pytest.mark.parametrize('plaintext', ['sk-123', '12345678'])
    def test_short_key_is_fully_masked(self, plaintext):
        assert mask_key(plaintext) == '****'

    @pytest.mark.parametrize('plaintext', [None, ''])
    def test_empty_returns_empty_string(self, plaintext):
        assert mask_key(plaintext) == ''


# ============================================================
# encrypt_key / decrypt_key：Key 加解密
# ============================================================

class TestKeyCipher:
    def test_roundtrip_and_cipher_differs_from_plaintext(self):
        plaintext = 'sk-abcdefghijklmnopqrstuvwx'
        ciphertext = encrypt_key(plaintext)
        assert ciphertext != plaintext
        assert plaintext not in ciphertext
        assert decrypt_key(ciphertext) == plaintext

    def test_encryption_is_randomized_but_decryptable(self):
        plaintext = 'sk-abcdefghijklmnop'
        cipher_1, cipher_2 = encrypt_key(plaintext), encrypt_key(plaintext)
        assert cipher_1 != cipher_2
        assert decrypt_key(cipher_1) == plaintext
        assert decrypt_key(cipher_2) == plaintext

    def test_encryption_key_isolated_from_invite_code_key(self):
        config = get_config()
        assert config.USER_AI_KEY_ENCRYPTION_KEY
        assert config.USER_AI_KEY_ENCRYPTION_KEY != config.INVITE_CODE_ENCRYPTION_KEY

    def test_decrypt_failure_raises_business_error(self):
        with pytest.raises(UserAiProviderError) as exc:
            decrypt_key('not-a-valid-ciphertext')
        assert exc.value.message == 'API Key 解密失败，请重新填写'
        assert exc.value.code == 5001
        assert exc.value.http_status == 500


# ============================================================
# 业务层测试公共桩：全部 monkeypatch 掉模型层，绝不连真实 MySQL
# ============================================================

def _patch_settings(monkeypatch, enabled):
    """替换总开关查询"""
    monkeypatch.setattr(
        UserAiSettingsModel, 'is_own_provider_enabled',
        lambda self, user_id: enabled
    )


def _patch_enabled_rows(monkeypatch, rows):
    """替换某分类下启用号池查询"""
    monkeypatch.setattr(
        UserAiProviderModel, 'list_enabled_by_user_category',
        lambda self, user_id, category: rows
    )


def _patch_enabled_rows_all(monkeypatch, rows):
    """替换该用户全量启用号池查询（is_feature_byok 跨分类一次取回）"""
    monkeypatch.setattr(
        UserAiProviderModel, 'list_enabled_by_user',
        lambda self, user_id: rows
    )


def _provider_row(**overrides):
    """构造一行 user_ai_providers 记录"""
    row = {
        'id': 1,
        'user_id': 7,
        'category': CATEGORY_IMAGE_GEN,
        'name': '通道A',
        'api_base': 'https://api.openai.com/v1',
        'api_key_cipher': encrypt_key('sk-abcdefghijklmnop'),
        'model_name': 'gpt-image-2',
        'priority': 0,
        'is_enabled': 1,
        'last_test_ok': None,
        'last_test_at': None,
        'last_test_error': None,
        'last_used_at': None,
        'failure_count': 0,
        'last_error': None,
        'created_at': datetime.datetime(2026, 1, 1, 12, 0, 0),
        'updated_at': datetime.datetime(2026, 1, 1, 12, 0, 0),
    }
    row.update(overrides)
    return row


# ============================================================
# resolve_channel / iter_channel_entries：通道解析与号池
# ============================================================

class TestResolveChannel:
    def test_platform_when_user_id_missing(self, monkeypatch):
        monkeypatch.setattr(
            UserAiSettingsModel, 'is_own_provider_enabled',
            lambda self, user_id: pytest.fail('user_id 为空时不应查库')
        )
        monkeypatch.setattr(
            UserAiProviderModel, 'list_enabled_by_user_category',
            lambda self, user_id, category: pytest.fail('user_id 为空时不应查库')
        )
        for user_id in (None, 0):
            result = resolve_channel(user_id, CATEGORY_IMAGE_GEN)
            assert result['source'] == 'platform'
            assert len(result['entries']) == 1
            assert isinstance(result['entries'][0], ChannelEntry)
            assert result['entries'][0].provider_id is None
            assert result['entries'][0].name == '平台默认'

    def test_platform_when_switch_disabled(self, monkeypatch):
        _patch_settings(monkeypatch, False)
        monkeypatch.setattr(
            UserAiProviderModel, 'list_enabled_by_user_category',
            lambda self, user_id, category: pytest.fail('总开关关闭时不应查询号池')
        )
        result = resolve_channel(7, CATEGORY_IMAGE_GEN)
        assert result['source'] == 'platform'
        assert len(result['entries']) == 1

    def test_platform_values_match_aiconfig_image_gen(self, monkeypatch):
        _patch_settings(monkeypatch, False)
        entry = resolve_channel(7, CATEGORY_IMAGE_GEN)['entries'][0]
        assert entry.api_base == (AIConfig.IMAGE_GEN_API_BASE
                                  or 'https://api.qiuqiutoken.com/v1').rstrip('/')
        assert entry.api_key == (AIConfig.IMAGE_GEN_API_KEY or 'sk-placeholder')
        assert entry.model_name == AIConfig.IMAGE_GEN_MODEL_NAME

    def test_platform_image_gen_default_and_rstrip(self, monkeypatch):
        monkeypatch.setattr(AIConfig, 'IMAGE_GEN_API_BASE', '')
        monkeypatch.setattr(AIConfig, 'IMAGE_GEN_API_KEY', '')
        monkeypatch.setattr(AIConfig, 'IMAGE_GEN_MODEL_NAME', 'gpt-image-2')
        entry = resolve_channel(None, CATEGORY_IMAGE_GEN)['entries'][0]
        assert entry.api_base == 'https://api.qiuqiutoken.com/v1'
        assert entry.api_key == 'sk-placeholder'
        assert entry.model_name == 'gpt-image-2'

        monkeypatch.setattr(AIConfig, 'IMAGE_GEN_API_BASE', 'https://img.example.com/v1/')
        assert resolve_channel(None, CATEGORY_IMAGE_GEN)['entries'][0].api_base == \
            'https://img.example.com/v1'

    def test_platform_multimodal_keeps_trailing_slash(self, monkeypatch):
        monkeypatch.setattr(AIConfig, 'MULTIMODAL_API_BASE', '')
        monkeypatch.setattr(AIConfig, 'MULTIMODAL_API_KEY', '')
        _patch_settings(monkeypatch, False)
        entry = resolve_channel(7, CATEGORY_MULTIMODAL)['entries'][0]
        assert entry.api_base == 'https://dashscope.aliyuncs.com/compatible-mode/v1'
        assert entry.api_key == 'sk-placeholder'
        assert entry.model_name == AIConfig.MULTIMODAL_MODEL_NAME

        # 非空时不做 rstrip，保持与现有 f"{api_base}/chat/completions" 一致
        monkeypatch.setattr(AIConfig, 'MULTIMODAL_API_BASE',
                            'https://dashscope.aliyuncs.com/compatible-mode/v1/')
        assert resolve_channel(None, CATEGORY_MULTIMODAL)['entries'][0].api_base == \
            'https://dashscope.aliyuncs.com/compatible-mode/v1/'

    def test_platform_llm_default(self, monkeypatch):
        monkeypatch.setattr(AIConfig, 'LLM_API_BASE', '')
        monkeypatch.setattr(AIConfig, 'LLM_API_KEY', '')
        entry = resolve_channel(0, CATEGORY_LLM)['entries'][0]
        assert entry.api_base == 'https://dashscope.aliyuncs.com/compatible-mode/v1'
        assert entry.api_key == 'sk-placeholder'
        assert entry.model_name == AIConfig.LLM_MODEL_NAME

    def test_platform_when_no_enabled_rows(self, monkeypatch):
        _patch_settings(monkeypatch, True)
        _patch_enabled_rows(monkeypatch, [])
        result = resolve_channel(7, CATEGORY_IMAGE_GEN)
        assert result['source'] == 'platform'
        assert len(result['entries']) == 1

    def test_user_entries_follow_priority_order(self, monkeypatch):
        rows = [
            _provider_row(id=11, priority=1,
                          api_key_cipher=encrypt_key('sk-first-key-1234'), name='通道A'),
            _provider_row(id=12, priority=4,
                          api_key_cipher=encrypt_key('sk-second-key-5678'), name='通道B'),
        ]
        _patch_settings(monkeypatch, True)
        _patch_enabled_rows(monkeypatch, rows)

        result = resolve_channel(7, CATEGORY_IMAGE_GEN)
        assert result['source'] == 'user'
        assert [entry.provider_id for entry in result['entries']] == [11, 12]
        assert [entry.api_key for entry in result['entries']] == \
            ['sk-first-key-1234', 'sk-second-key-5678']
        assert [entry.name for entry in result['entries']] == ['通道A', '通道B']
        assert [entry.model_name for entry in result['entries']] == ['gpt-image-2', 'gpt-image-2']

    def test_falls_back_to_platform_on_db_error(self, monkeypatch):
        _patch_settings(monkeypatch, True)

        def _boom(self, user_id, category):
            raise RuntimeError('mysql is down')

        monkeypatch.setattr(UserAiProviderModel, 'list_enabled_by_user_category', _boom)
        result = resolve_channel(7, CATEGORY_IMAGE_GEN)
        assert result['source'] == 'platform'
        assert len(result['entries']) == 1
        assert result['entries'][0].provider_id is None

    def test_falls_back_to_platform_when_settings_query_fails(self, monkeypatch):
        def _boom(self, user_id):
            raise RuntimeError('mysql is down')

        monkeypatch.setattr(UserAiSettingsModel, 'is_own_provider_enabled', _boom)
        result = resolve_channel(7, CATEGORY_IMAGE_GEN)
        assert result['source'] == 'platform'
        assert len(result['entries']) == 1

    def test_skips_entry_when_key_decrypt_fails(self, monkeypatch):
        rows = [
            _provider_row(id=1, priority=0, api_key_cipher='bad-cipher', name='坏通道'),
            _provider_row(id=2, priority=1, api_key_cipher='good-cipher', name='好通道'),
        ]
        _patch_settings(monkeypatch, True)
        _patch_enabled_rows(monkeypatch, rows)

        def _decrypt(ciphertext):
            if ciphertext == 'bad-cipher':
                raise UserAiProviderError('API Key 解密失败，请重新填写', 5001, 500)
            return 'sk-decrypted-key-0001'

        monkeypatch.setattr(svc, 'decrypt_key', _decrypt)

        result = resolve_channel(7, CATEGORY_IMAGE_GEN)
        assert result['source'] == 'user'
        assert [entry.provider_id for entry in result['entries']] == [2]
        assert result['entries'][0].api_key == 'sk-decrypted-key-0001'
        assert result['entries'][0].name == '好通道'

    def test_falls_back_to_platform_when_all_keys_fail(self, monkeypatch):
        rows = [
            _provider_row(id=1, priority=0, api_key_cipher='bad-1'),
            _provider_row(id=2, priority=1, api_key_cipher='bad-2'),
        ]
        _patch_settings(monkeypatch, True)
        _patch_enabled_rows(monkeypatch, rows)

        def _decrypt(ciphertext):
            raise UserAiProviderError('API Key 解密失败，请重新填写', 5001, 500)

        monkeypatch.setattr(svc, 'decrypt_key', _decrypt)

        result = resolve_channel(7, CATEGORY_IMAGE_GEN)
        assert result['source'] == 'platform'
        assert len(result['entries']) == 1
        assert result['entries'][0].provider_id is None


class TestIterChannelEntries:
    def test_yields_single_platform_entry(self, monkeypatch):
        _patch_settings(monkeypatch, False)
        entries = list(iter_channel_entries(7, CATEGORY_IMAGE_GEN))
        assert len(entries) == 1
        assert isinstance(entries[0], ChannelEntry)
        assert entries[0].provider_id is None
        assert entries[0].name == '平台默认'

    def test_yields_all_user_entries_in_order(self, monkeypatch):
        rows = [
            _provider_row(id=1, priority=0, api_key_cipher=encrypt_key('sk-aaaaaaaaaaaa')),
            _provider_row(id=2, priority=1, api_key_cipher=encrypt_key('sk-bbbbbbbbbbbb')),
        ]
        _patch_settings(monkeypatch, True)
        _patch_enabled_rows(monkeypatch, rows)
        entries = list(iter_channel_entries(7, CATEGORY_IMAGE_GEN))
        assert [entry.provider_id for entry in entries] == [1, 2]


# ============================================================
# 通道 CRUD：入参校验与对外输出（不泄露 Key）
# ============================================================

class TestCreateProviderValidation:
    def test_invalid_category(self):
        with pytest.raises(UserAiProviderError) as exc:
            create_provider(7, 'video_gen', '通道A', 'https://api.openai.com/v1',
                            'sk-abcdefghijklmnop', 'gpt-image-2')
        assert exc.value.message == '模型分类无效'

    @pytest.mark.parametrize('name', ['', '   ', None, 'x' * 65])
    def test_invalid_name(self, name):
        with pytest.raises(UserAiProviderError) as exc:
            create_provider(7, CATEGORY_IMAGE_GEN, name, 'https://api.openai.com/v1',
                            'sk-abcdefghijklmnop', 'gpt-image-2')
        assert exc.value.message == '配置名称不能为空且不超过 64 个字符'

    @pytest.mark.parametrize('model_name', ['', '   ', None, 'm' * 129])
    def test_invalid_model_name(self, model_name):
        with pytest.raises(UserAiProviderError) as exc:
            create_provider(7, CATEGORY_IMAGE_GEN, '通道A', 'https://api.openai.com/v1',
                            'sk-abcdefghijklmnop', model_name)
        assert exc.value.message == '模型名不能为空且不超过 128 个字符'

    def test_invalid_api_base(self):
        with pytest.raises(UserAiProviderError) as exc:
            create_provider(7, CATEGORY_IMAGE_GEN, '通道A', 'not-a-url',
                            'sk-abcdefghijklmnop', 'gpt-image-2')
        assert exc.value.message == 'API 地址必须以 http:// 或 https:// 开头'

    @pytest.mark.parametrize('api_key', ['', '   ', None])
    def test_empty_api_key(self, monkeypatch, api_key):
        _patch_dns(monkeypatch, PUBLIC_IP)
        with pytest.raises(UserAiProviderError) as exc:
            create_provider(7, CATEGORY_IMAGE_GEN, '通道A', 'https://api.openai.com/v1',
                            api_key, 'gpt-image-2')
        assert exc.value.message == 'API Key 不能为空'

    def test_create_success_masks_key_and_hides_cipher(self, monkeypatch):
        _patch_dns(monkeypatch, PUBLIC_IP)
        captured = {}

        def _create(self, user_id, category, name, api_base, api_key_cipher, model_name):
            captured.update({
                'user_id': user_id, 'category': category, 'name': name,
                'api_base': api_base, 'api_key_cipher': api_key_cipher,
                'model_name': model_name,
            })
            return _provider_row(name=name, api_base=api_base,
                                 api_key_cipher=api_key_cipher, model_name=model_name)

        monkeypatch.setattr(UserAiProviderModel, 'create', _create)

        result = create_provider(7, CATEGORY_IMAGE_GEN, ' 通道A ', 'https://api.openai.com/v1/',
                                 'sk-abcdefghijklmnop', ' gpt-image-2 ')

        assert captured['name'] == '通道A'
        assert captured['model_name'] == 'gpt-image-2'
        assert captured['api_base'] == 'https://api.openai.com/v1'
        assert captured['api_key_cipher'] != 'sk-abcdefghijklmnop'
        assert decrypt_key(captured['api_key_cipher']) == 'sk-abcdefghijklmnop'
        assert 'api_key_cipher' not in result
        assert 'api_key' not in result
        assert result['api_key_masked'] == 'sk-a****mnop'


class TestUpdateProvider:
    def _patch_find(self, monkeypatch, row):
        monkeypatch.setattr(UserAiProviderModel, 'find_by_id_and_user',
                            lambda self, provider_id, user_id: row)

    def test_missing_provider_raises_4004(self, monkeypatch):
        self._patch_find(monkeypatch, None)
        with pytest.raises(UserAiProviderError) as exc:
            update_provider(7, 1, name='新名字')
        assert exc.value.message == '配置不存在'
        assert exc.value.code == 4004
        assert exc.value.http_status == 404

    @pytest.mark.parametrize('api_key', [None, '', '   '])
    def test_blank_api_key_keeps_existing_key(self, monkeypatch, api_key):
        row = _provider_row()
        self._patch_find(monkeypatch, row)
        captured = {}

        def _update(self, provider_id, user_id, fields):
            captured['fields'] = fields
            return row

        monkeypatch.setattr(UserAiProviderModel, 'update', _update)

        update_provider(7, 1, api_key=api_key, name='新名字')
        assert 'api_key_cipher' not in captured['fields']
        assert captured['fields']['name'] == '新名字'

    def test_api_key_is_reencrypted(self, monkeypatch):
        row = _provider_row()
        self._patch_find(monkeypatch, row)
        captured = {}

        def _update(self, provider_id, user_id, fields):
            captured['fields'] = fields
            return row

        monkeypatch.setattr(UserAiProviderModel, 'update', _update)

        update_provider(7, 1, api_key='sk-new-secret-key-01')
        assert decrypt_key(captured['fields']['api_key_cipher']) == 'sk-new-secret-key-01'

    def test_is_enabled_accepts_bool_and_int(self, monkeypatch):
        row = _provider_row()
        self._patch_find(monkeypatch, row)
        captured = {}

        def _update(self, provider_id, user_id, fields):
            captured['fields'] = fields
            return row

        monkeypatch.setattr(UserAiProviderModel, 'update', _update)

        update_provider(7, 1, is_enabled=False)
        assert captured['fields']['is_enabled'] == 0
        update_provider(7, 1, is_enabled=1)
        assert captured['fields']['is_enabled'] == 1


class TestListProviders:
    def _patch(self, monkeypatch, rows, enabled=True):
        monkeypatch.setattr(UserAiProviderModel, 'list_by_user',
                            lambda self, user_id: rows)
        _patch_settings(monkeypatch, enabled)

    def test_masks_key_and_hides_cipher(self, monkeypatch):
        self._patch(monkeypatch, [_provider_row()])
        result = list_providers(7)

        assert result['use_own_provider'] is True
        item = result['items'][0]
        assert 'api_key_cipher' not in item
        assert 'api_key' not in item
        assert item['api_key_masked'] == 'sk-a****mnop'
        assert item['is_enabled'] is True
        assert item['last_test_ok'] is None
        assert item['created_at'] == '2026-01-01 12:00:00'
        assert isinstance(item['created_at'], str)
        assert item['last_test_at'] is None

    def test_broken_cipher_is_masked_as_stars(self, monkeypatch):
        self._patch(monkeypatch, [_provider_row(api_key_cipher='broken-cipher')])
        item = list_providers(7)['items'][0]
        assert item['api_key_masked'] == '****'
        assert 'api_key_cipher' not in item

    def test_items_grouped_by_category_then_priority(self, monkeypatch):
        self._patch(monkeypatch, [
            _provider_row(id=3, category=CATEGORY_LLM, priority=0),
            _provider_row(id=1, category=CATEGORY_IMAGE_GEN, priority=3),
            _provider_row(id=2, category=CATEGORY_IMAGE_GEN, priority=1),
            _provider_row(id=4, category=CATEGORY_MULTIMODAL, priority=0),
        ], enabled=False)

        result = list_providers(7)
        assert result['use_own_provider'] is False
        assert [item['id'] for item in result['items']] == [2, 1, 4, 3]
        assert [item['category'] for item in result['items']] == \
            [CATEGORY_IMAGE_GEN, CATEGORY_IMAGE_GEN, CATEGORY_MULTIMODAL, CATEGORY_LLM]


class TestTestProvider:
    def _patch_provider(self, monkeypatch, row):
        monkeypatch.setattr(UserAiProviderModel, 'find_by_id_and_user',
                            lambda self, provider_id, user_id: row)
        captured = {}

        def _update_test_result(self, provider_id, ok, error=None):
            captured['provider_id'] = provider_id
            captured['ok'] = ok
            captured['error'] = error
            return _provider_row(last_test_at=datetime.datetime(2026, 2, 1, 10, 0, 0))

        monkeypatch.setattr(UserAiProviderModel, 'update_test_result', _update_test_result)
        return captured

    def test_success_calls_models_endpoint(self, monkeypatch):
        _patch_dns(monkeypatch, PUBLIC_IP)
        captured = self._patch_provider(monkeypatch, _provider_row())
        calls = {}

        class _Response:
            status_code = 200
            text = '{"data": []}'

        def _get(url, headers=None, timeout=None):
            calls.update({'url': url, 'headers': headers, 'timeout': timeout})
            return _Response()

        monkeypatch.setattr(svc.requests, 'get', _get)

        result = svc.test_provider(7, 1)
        assert result['ok'] is True
        assert result['error'] is None
        assert result['tested_at'] == '2026-02-01 10:00:00'
        assert calls['url'] == 'https://api.openai.com/v1/models'
        assert calls['headers'] == {'Authorization': 'Bearer sk-abcdefghijklmnop'}
        assert calls['timeout'] == 15
        assert captured['ok'] is True
        assert captured['provider_id'] == 1

    def test_http_error_status_is_reported(self, monkeypatch):
        _patch_dns(monkeypatch, PUBLIC_IP)
        captured = self._patch_provider(monkeypatch, _provider_row())

        class _Response:
            status_code = 401
            text = 'invalid api key'

        monkeypatch.setattr(svc.requests, 'get',
                            lambda url, headers=None, timeout=None: _Response())

        result = svc.test_provider(7, 1)
        assert result['ok'] is False
        assert result['error'] == 'HTTP 401: invalid api key'
        assert captured['ok'] is False
        assert captured['error'] == 'HTTP 401: invalid api key'

    def test_timeout_is_mapped_to_chinese_message(self, monkeypatch):
        _patch_dns(monkeypatch, PUBLIC_IP)
        captured = self._patch_provider(monkeypatch, _provider_row())

        def _get(url, headers=None, timeout=None):
            raise svc.requests.exceptions.Timeout('timed out')

        monkeypatch.setattr(svc.requests, 'get', _get)

        result = svc.test_provider(7, 1)
        assert result['ok'] is False
        assert result['error'] == '连接超时'
        assert captured['ok'] is False
        assert captured['error'] == '连接超时'


# ============================================================
# 失败上报：绝不影响主业务
# ============================================================

class TestReportEntryStats:
    def test_failure_truncates_error_and_updates_stats(self, monkeypatch):
        captured = {}

        def _update_stats(self, provider_id, ok, error=None):
            captured.update({'provider_id': provider_id, 'ok': ok, 'error': error})

        monkeypatch.setattr(UserAiProviderModel, 'update_stats', _update_stats)

        svc.report_entry_failure(5, 'x' * 600)
        assert captured['provider_id'] == 5
        assert captured['ok'] is False
        assert len(captured['error']) == 500

        svc.report_entry_success(5)
        assert captured['ok'] is True
        assert captured['error'] is None

    def test_platform_channel_is_noop(self, monkeypatch):
        monkeypatch.setattr(
            UserAiProviderModel, 'update_stats',
            lambda *args, **kwargs: pytest.fail('平台通道不应写统计')
        )
        svc.report_entry_failure(None, 'err')
        svc.report_entry_success(None)

    def test_db_error_is_swallowed(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError('mysql is down')

        monkeypatch.setattr(UserAiProviderModel, 'update_stats', _boom)
        # 不应抛出任何异常
        svc.report_entry_failure(5, 'err')
        svc.report_entry_success(5)


# ============================================================
# 计费判定
# ============================================================

class TestGetFeatureCategories:
    def test_unmapped_key_returns_default(self):
        # 未命中映射时返回默认集合（image_gen），不再返回单一分类字符串
        assert get_feature_categories('unknown.feature') == {CATEGORY_IMAGE_GEN}
        assert get_feature_categories(None) == {CATEGORY_IMAGE_GEN}
        assert get_feature_categories('') == {CATEGORY_IMAGE_GEN}

    def test_mapped_keys_single_category(self):
        assert get_feature_categories('toolbox.text_to_image') == {CATEGORY_IMAGE_GEN}
        assert get_feature_categories('toolbox.ai_model') == {CATEGORY_IMAGE_GEN}
        assert get_feature_categories('toolbox.plan_analysis') == {CATEGORY_MULTIMODAL}
        assert get_feature_categories('toolbox.prompt_reverse') == {CATEGORY_MULTIMODAL}

    def test_mapped_keys_mixed_categories(self):
        assert get_feature_categories('toolbox.image_merge') == \
            {CATEGORY_IMAGE_GEN, CATEGORY_MULTIMODAL}
        assert get_feature_categories('toolbox.chat_gen') == \
            {CATEGORY_IMAGE_GEN, CATEGORY_MULTIMODAL}
        assert get_feature_categories('toolbox.product_replace') == \
            {CATEGORY_IMAGE_GEN, CATEGORY_MULTIMODAL}
        assert get_feature_categories('toolbox.model_product') == \
            {CATEGORY_IMAGE_GEN, CATEGORY_MULTIMODAL}
        assert get_feature_categories('ai_product_image.smart_mode') == \
            {CATEGORY_IMAGE_GEN, CATEGORY_MULTIMODAL}
        assert get_feature_categories('ai_product_image.batch') == \
            {CATEGORY_IMAGE_GEN, CATEGORY_MULTIMODAL}

    def test_mapped_keys_all_categories(self):
        assert get_feature_categories('ai_product_image.pro_mode') == \
            {CATEGORY_IMAGE_GEN, CATEGORY_MULTIMODAL, CATEGORY_LLM}

    def test_map_values_are_valid_categories(self):
        # 每个映射值都是分类组成的 frozenset，且并集 ⊆ 全部分类
        all_categories = set(CATEGORIES)
        for value in FEATURE_CHANNEL_MAP.values():
            assert isinstance(value, frozenset)
            assert value <= all_categories
        assert len(FEATURE_CHANNEL_MAP) == 11


class TestIsFeatureByok:
    def test_false_when_switch_disabled(self, monkeypatch):
        _patch_settings(monkeypatch, False)
        monkeypatch.setattr(
            UserAiProviderModel, 'list_enabled_by_user',
            lambda self, user_id: pytest.fail('总开关关闭时不应查询号池')
        )
        assert is_feature_byok(7, 'toolbox.text_to_image') is False

    def test_true_when_enabled_and_has_entry(self, monkeypatch):
        _patch_settings(monkeypatch, True)
        _patch_enabled_rows_all(monkeypatch, [_provider_row()])
        assert is_feature_byok(7, 'toolbox.text_to_image') is True

    def test_false_when_no_entry(self, monkeypatch):
        _patch_settings(monkeypatch, True)
        _patch_enabled_rows_all(monkeypatch, [])
        assert is_feature_byok(7, 'toolbox.text_to_image') is False

    def test_false_when_user_id_missing(self, monkeypatch):
        monkeypatch.setattr(
            UserAiSettingsModel, 'is_own_provider_enabled',
            lambda self, user_id: pytest.fail('user_id 为空时不应查库')
        )
        assert is_feature_byok(None, 'toolbox.text_to_image') is False
        assert is_feature_byok(0, 'toolbox.text_to_image') is False

    def test_false_on_db_error(self, monkeypatch):
        def _boom(self, user_id):
            raise RuntimeError('mysql is down')

        monkeypatch.setattr(UserAiSettingsModel, 'is_own_provider_enabled', _boom)
        assert is_feature_byok(7, 'toolbox.text_to_image') is False

    def test_false_on_provider_query_error(self, monkeypatch):
        # 号池查询异常时安全降级：视为未自备，照常扣费
        _patch_settings(monkeypatch, True)

        def _boom(self, user_id):
            raise RuntimeError('mysql is down')

        monkeypatch.setattr(UserAiProviderModel, 'list_enabled_by_user', _boom)
        assert is_feature_byok(7, 'toolbox.text_to_image') is False

    def test_queries_all_enabled_rows_for_user(self, monkeypatch):
        # is_feature_byok 跨分类一次取回该用户全部启用条目（不再按分类逐次查询）
        _patch_settings(monkeypatch, True)
        captured = {}

        def _list(self, user_id):
            captured['user_id'] = user_id
            return [_provider_row()]

        monkeypatch.setattr(UserAiProviderModel, 'list_enabled_by_user', _list)
        assert is_feature_byok(7, 'toolbox.text_to_image') is True
        assert captured['user_id'] == 7


class TestIsFeatureByokMixedCategories:
    """混合分类判定：功能涉及的全部分类下都有启用条目才算完全自备"""

    def test_multimodal_only(self, monkeypatch):
        # 仅启用 multimodal 条目：单 multimodal 功能命中，混合分类功能不命中
        _patch_settings(monkeypatch, True)
        _patch_enabled_rows_all(
            monkeypatch,
            [_provider_row(id=2, category=CATEGORY_MULTIMODAL, name='多模态通道')]
        )
        assert is_feature_byok(7, 'toolbox.plan_analysis') is True
        assert is_feature_byok(7, 'toolbox.prompt_reverse') is True
        # smart_mode / chat_gen 需要 image_gen + multimodal，缺 image_gen
        assert is_feature_byok(7, 'ai_product_image.smart_mode') is False
        assert is_feature_byok(7, 'toolbox.chat_gen') is False
        assert is_feature_byok(7, 'toolbox.text_to_image') is False

    def test_image_gen_only(self, monkeypatch):
        # 仅启用 image_gen 条目：单 image_gen 功能命中，缺 multimodal 的混合功能不命中
        _patch_settings(monkeypatch, True)
        _patch_enabled_rows_all(monkeypatch, [_provider_row()])
        assert is_feature_byok(7, 'toolbox.text_to_image') is True
        assert is_feature_byok(7, 'toolbox.ai_model') is True
        assert is_feature_byok(7, 'ai_product_image.smart_mode') is False
        assert is_feature_byok(7, 'toolbox.plan_analysis') is False
        assert is_feature_byok(7, 'ai_product_image.pro_mode') is False

    def test_all_three_categories(self, monkeypatch):
        # 三分类全配：需要全部分类的 pro_mode 命中
        _patch_settings(monkeypatch, True)
        _patch_enabled_rows_all(monkeypatch, [
            _provider_row(),
            _provider_row(id=2, category=CATEGORY_MULTIMODAL, name='多模态通道'),
            _provider_row(id=3, category=CATEGORY_LLM, name='文本通道'),
        ])
        assert is_feature_byok(7, 'ai_product_image.pro_mode') is True
        assert is_feature_byok(7, 'ai_product_image.smart_mode') is True

    def test_no_rows_at_all(self, monkeypatch):
        # 未配置任何启用条目：即使总开关开启也全部视为平台通道
        _patch_settings(monkeypatch, True)
        _patch_enabled_rows_all(monkeypatch, [])
        assert is_feature_byok(7, 'toolbox.text_to_image') is False
        assert is_feature_byok(7, 'toolbox.plan_analysis') is False
        assert is_feature_byok(7, 'ai_product_image.pro_mode') is False

    def test_switch_off_mixed_features(self, monkeypatch):
        # 总开关关闭：混合分类功能一律按平台通道处理
        _patch_settings(monkeypatch, False)
        _patch_enabled_rows_all(
            monkeypatch,
            [_provider_row(),
             _provider_row(id=2, category=CATEGORY_MULTIMODAL, name='多模态通道'),
             _provider_row(id=3, category=CATEGORY_LLM, name='文本通道')]
        )
        assert is_feature_byok(7, 'ai_product_image.pro_mode') is False
        assert is_feature_byok(7, 'ai_product_image.smart_mode') is False


class TestCalculateEffectiveCost:
    def test_zero_when_byok_hit(self, monkeypatch):
        monkeypatch.setattr(svc, 'is_feature_byok', lambda user_id, feature_key: True)
        monkeypatch.setattr(
            feature_pricing_service, 'calculate_per_use_cost',
            lambda feature_key: pytest.fail('命中自备通道不应查询平台定价')
        )
        assert calculate_effective_cost(7, 'toolbox.text_to_image') == 0

    def test_platform_price_when_miss(self, monkeypatch):
        monkeypatch.setattr(svc, 'is_feature_byok', lambda user_id, feature_key: False)
        monkeypatch.setattr(feature_pricing_service, 'calculate_per_use_cost',
                            lambda feature_key: 30)
        assert calculate_effective_cost(7, 'toolbox.text_to_image') == 30

    def test_platform_price_when_user_id_missing(self, monkeypatch):
        monkeypatch.setattr(feature_pricing_service, 'calculate_per_use_cost',
                            lambda feature_key: 12)
        assert calculate_effective_cost(None, 'toolbox.text_to_image') == 12
        assert calculate_effective_cost(0, 'toolbox.text_to_image') == 12


# ============================================================
# 退款封顶：全部任务失败时退款额 = min(实际预扣, 单价×失败数)
# （直接调用 ARQ 任务执行体，模块依赖全部 mock，不触达 Redis / MySQL）
# ============================================================

async def _noop_progress(ctx, task_id, *args, **kwargs):
    """替换 set_progress / complete_task / fail_task 的异步空操作"""
    return None


def _smart_payload(task_ids, prepaid_coins=0, user_id=7):
    """构造 generation_smart_task 的最小可执行 ARQ payload"""
    return {
        'product_images': ['aGk='],
        'reference_image': None,
        'reference_text': None,
        'platform': 'amazon',
        'region': 'US',
        'target_language': 'en',
        'size': '1024x1024',
        'product_info_json': None,
        'image_groups': [],
        'batch_id': 'batch-refund',
        'task_ids': task_ids,
        'user_id': user_id,
        'history_input_data': {},
        'history_config_snapshot': None,
        'site': None,
        'scene': None,
        'prepaid_coins': prepaid_coins,
    }


def _patch_smart_task_env(monkeypatch, task_ids):
    """为 generation_smart_task 构造运行环境：内存 task_store + 全链路 mock"""
    _get_workflows()
    task_store = {
        tid: {'task_id': tid, 'status': TaskStatus.PENDING.value}
        for tid in task_ids
    }
    refund_calls = []

    monkeypatch.setattr(smart_wf, 'get_task_store', lambda: task_store)
    monkeypatch.setattr(smart_wf, 'set_progress', _noop_progress)
    monkeypatch.setattr(smart_wf, 'complete_task', _noop_progress)
    monkeypatch.setattr(smart_wf, 'fail_task', _noop_progress)
    monkeypatch.setattr(smart_wf, 'save_history', lambda **kwargs: None)
    # 单张图成本固定 8 灵感币
    monkeypatch.setattr(smart_wf, 'calculate_image_cost', lambda feature_key, size: 8)
    monkeypatch.setattr(
        smart_wf, 'refund_coins', lambda **kwargs: refund_calls.append(kwargs)
    )
    return task_store, refund_calls


def _patch_smart_graph_error(monkeypatch):
    """把工作流图打成返回错误状态（触发全部失败分支）"""
    _get_workflows()
    monkeypatch.setattr(
        smart_wf, 'smart_generation_graph',
        SimpleNamespace(invoke=lambda state: {'error': '模拟工作流失败'}),
    )


def _patch_pro_task_env(monkeypatch, task_ids):
    """为 generation_pro_confirm_task 构造运行环境：内存 task_store + 全链路 mock"""
    _get_workflows()
    task_store = {
        tid: {'task_id': tid, 'status': TaskStatus.PENDING.value}
        for tid in task_ids
    }
    refund_calls = []
    context = {
        'size': '1024x1024',
        'locked': True,
        'tasks': [{'task_id': tid} for tid in task_ids],
    }

    monkeypatch.setattr(pro_wf, 'get_pro_batch', lambda batch_id: context)
    monkeypatch.setattr(pro_wf, 'set_pro_batch', lambda batch_id, ctx: None)
    monkeypatch.setattr(pro_wf, 'get_task_store', lambda: task_store)
    monkeypatch.setattr(pro_wf, 'set_progress', _noop_progress)
    monkeypatch.setattr(pro_wf, 'complete_task', _noop_progress)
    monkeypatch.setattr(pro_wf, 'fail_task', _noop_progress)
    monkeypatch.setattr(pro_wf, 'save_history', lambda **kwargs: None)
    # 单张图成本固定 8 灵感币
    monkeypatch.setattr(pro_wf, 'calculate_image_cost', lambda feature_key, size: 8)
    monkeypatch.setattr(
        pro_wf, 'refund_coins', lambda **kwargs: refund_calls.append(kwargs)
    )

    def _boom(*args, **kwargs):
        raise RuntimeError('模拟生图失败')

    monkeypatch.setattr(pro_wf, '_execute_generation', _boom)
    return task_store, refund_calls


class TestRefundCapOnAllFailed:
    def test_smart_no_refund_when_prepaid_zero(self, monkeypatch):
        # BYOK 命中（预扣为 0）且全部任务失败：不退款
        task_ids = ['st1', 'st2', 'st3']
        task_store, refund_calls = _patch_smart_task_env(monkeypatch, task_ids)
        _patch_smart_graph_error(monkeypatch)

        asyncio.run(smart_wf.generation_smart_task(
            None, _smart_payload(task_ids, prepaid_coins=0), 'arq-1'))

        assert all(
            task_store[tid]['status'] == TaskStatus.FAILED.value
            for tid in task_ids
        )
        assert refund_calls == []

    def test_smart_refund_capped_by_prepaid(self, monkeypatch):
        # 预扣 100 > 应退 24（单价 8 × 3 张全部失败）：按应退额 24 退款
        task_ids = ['st1', 'st2', 'st3']
        _, refund_calls = _patch_smart_task_env(monkeypatch, task_ids)
        _patch_smart_graph_error(monkeypatch)

        asyncio.run(smart_wf.generation_smart_task(
            None, _smart_payload(task_ids, prepaid_coins=100), 'arq-1'))

        assert len(refund_calls) == 1
        assert refund_calls[0]['user_id'] == 7
        assert refund_calls[0]['amount'] == 24
        assert refund_calls[0]['feature_key'] == 'ai_product_image.smart_mode'
        assert refund_calls[0]['related_batch_id'] == 'batch-refund'

    def test_smart_refund_capped_by_total_cost(self, monkeypatch):
        # 预扣 10 < 应退 24：以实际预扣 10 封顶（防止超预扣退款）
        task_ids = ['st1', 'st2', 'st3']
        _, refund_calls = _patch_smart_task_env(monkeypatch, task_ids)
        _patch_smart_graph_error(monkeypatch)

        asyncio.run(smart_wf.generation_smart_task(
            None, _smart_payload(task_ids, prepaid_coins=10), 'arq-1'))

        assert len(refund_calls) == 1
        assert refund_calls[0]['amount'] == 10

    def test_pro_no_refund_when_prepaid_zero(self, monkeypatch):
        # BYOK 命中（预扣为 0）且全部任务失败：不退款
        task_ids = ['pt1', 'pt2', 'pt3']
        task_store, refund_calls = _patch_pro_task_env(monkeypatch, task_ids)

        asyncio.run(pro_wf.generation_pro_confirm_task(
            None,
            {'batch_id': 'batch-refund', 'task_ids': task_ids,
             'user_id': 7, 'prepaid_coins': 0},
            'arq-pro'))

        assert all(
            task_store[tid]['status'] == TaskStatus.FAILED.value
            for tid in task_ids
        )
        assert refund_calls == []

    def test_pro_refund_capped_by_prepaid(self, monkeypatch):
        # 预扣 100 > 应退 24（单价 8 × 3 张全部失败）：按应退额 24 退款
        task_ids = ['pt1', 'pt2', 'pt3']
        _, refund_calls = _patch_pro_task_env(monkeypatch, task_ids)

        asyncio.run(pro_wf.generation_pro_confirm_task(
            None,
            {'batch_id': 'batch-refund', 'task_ids': task_ids,
             'user_id': 7, 'prepaid_coins': 100},
            'arq-pro'))

        assert len(refund_calls) == 1
        assert refund_calls[0]['user_id'] == 7
        assert refund_calls[0]['amount'] == 24
        assert refund_calls[0]['feature_key'] == 'ai_product_image.pro_mode'
        assert refund_calls[0]['related_batch_id'] == 'batch-refund'


class TestPrepaidCoinsPassthrough:
    @pytest.mark.parametrize('prepaid_coins', [0, 100])
    def test_smart_async_payload_carries_prepaid_coins(self, monkeypatch, prepaid_coins):
        # run_smart_generation_async 经 ARQ payload 透传 prepaid_coins
        _get_workflows()
        captured = {}

        def _fake_submit(name, payload, module=''):
            captured['payload'] = payload
            return 'arq-task-id'

        monkeypatch.setattr(smart_wf, 'submit_task', _fake_submit)
        result = smart_wf.run_smart_generation_async(
            product_images=['aGk='], platform='amazon', region='US',
            target_language='en', size='1024x1024', image_groups=[],
            task_store={}, batch_store={}, user_id=7,
            prepaid_coins=prepaid_coins,
        )
        assert captured['payload']['prepaid_coins'] == prepaid_coins
        assert result['batch_id'] == captured['payload']['batch_id']

    def test_confirm_and_generate_payload_carries_prepaid_coins(self, monkeypatch):
        # confirm_and_generate 经 ARQ payload 透传 prepaid_coins
        _get_workflows()
        captured = {}

        def _fake_submit(name, payload, module=''):
            captured['payload'] = payload
            return 'arq-task-id'

        monkeypatch.setattr(pro_wf, 'get_pro_batch', lambda batch_id: {
            'size': '1024x1024',
            'locked': False,
            'tasks': [{
                'task_id': 'pt1',
                'status': 'confirmed',
                'image_type': 'main_image',
                'scheme': {'image_name': '主图', 'image_role': ''},
            }],
        })
        monkeypatch.setattr(pro_wf, 'set_pro_batch', lambda batch_id, context: None)
        monkeypatch.setattr(pro_wf, 'submit_task', _fake_submit)

        result = pro_wf.confirm_and_generate(
            'batch-pro', {}, {}, user_id=7, prepaid_coins=100)

        assert captured['payload']['prepaid_coins'] == 100
        assert result['batch_id'] == 'batch-pro'
