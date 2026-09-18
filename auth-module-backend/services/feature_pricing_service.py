"""
功能定价与灵感币扣费业务服务模块
功能定价查询 / 费用计算 / 灵感币扣减与退款（含事务管理与行级锁）
"""
import re
import pymysql
from models.feature_pricing import FeaturePricingModel
from services.auth_service import AuthError  # noqa: F401  保持与现有 service 一致的导入
from config import get_config

config = get_config()
feature_pricing_model = FeaturePricingModel()


class FeaturePricingError(Exception):
    """功能定价业务异常"""
    def __init__(self, message, code=3001, http_status=400):
        self.message = message
        self.code = code
        self.http_status = http_status
        super().__init__(message)


def get_feature_pricing(feature_key, active_only=True):
    """
    根据 feature_key 获取功能定价配置
    参数:
        feature_key: 功能唯一标识
        active_only: 是否仅查询启用的定价
    返回:
        dict 或 None
    """
    return feature_pricing_model.find_by_key(feature_key, active_only=active_only)


def list_active_pricings(category=None):
    """
    获取启用的功能定价列表
    参数:
        category: 可选分组过滤 (ai_product_image | ai_toolbox)
    返回:
        list
    """
    return feature_pricing_model.find_active(category=category)


def calculate_image_cost(feature_key, size):
    """
    计算按图片分辨率计价的灵感币费用（就近匹配规则）
    参数:
        feature_key: 功能标识（pricing_type 需为 per_image_resolution）
        size: 尺寸字符串，如 "1024x1024" / "1024X1024" / "1024×1024"
    返回:
        int: 灵感币数量；未找到配置或计价方式不匹配时返回 0
    """
    pricing = get_feature_pricing(feature_key, active_only=True)
    if not pricing:
        print(f'[calculate_image_cost] 未找到功能定价配置: feature_key={feature_key}')
        return 0
    if pricing.get('pricing_type') != 'per_image_resolution':
        print(f'[calculate_image_cost] 计价方式不匹配: feature_key={feature_key}, '
              f'pricing_type={pricing.get("pricing_type")}')
        return 0

    # 解析尺寸字符串 → 最长边
    longest_edge = 1024
    if size:
        match = re.match(r'^\s*(\d+)\s*[xX×]\s*(\d+)\s*$', str(size))
        if match:
            width = int(match.group(1))
            height = int(match.group(2))
            longest_edge = max(width, height)
        else:
            print(f'[calculate_image_cost] 尺寸解析失败，使用默认 1024: size={size}')

    tiers = (pricing.get('config') or {}).get('tiers', [])
    if not tiers:
        print(f'[calculate_image_cost] 未配置计价 tiers: feature_key={feature_key}')
        return 0

    # 就近匹配：选择 |longest_edge - max_dimension| 最小的 tier
    best_tier = min(tiers, key=lambda t: abs(longest_edge - int(t.get('max_dimension', 0))))
    return int(best_tier.get('coins', 0))


def calculate_per_use_cost(feature_key):
    """
    计算按次计价的灵感币费用
    参数:
        feature_key: 功能标识（pricing_type 需为 per_use）
    返回:
        int: 灵感币数量；未找到配置或计价方式不匹配时返回 0
    """
    pricing = get_feature_pricing(feature_key, active_only=True)
    if not pricing:
        print(f'[calculate_per_use_cost] 未找到功能定价配置: feature_key={feature_key}')
        return 0
    if pricing.get('pricing_type') != 'per_use':
        print(f'[calculate_per_use_cost] 计价方式不匹配: feature_key={feature_key}, '
              f'pricing_type={pricing.get("pricing_type")}')
        return 0
    return int((pricing.get('config') or {}).get('coins', 0))


def deduct_coins(user_id, amount, source_wallet='personal', feature_key=None,
                 description='', team_id=None, related_batch_id=None):
    """
    扣减灵感币（单连接事务：锁定余额 → 校验 → 扣减 → 记录流水）
    参数:
        user_id: 用户 ID
        amount: 扣减金额（> 0，<=0 则直接返回当前余额）
        source_wallet: 钱包类型 (personal/team)
        feature_key: 功能标识（写入流水描述）
        description: 业务描述
        team_id: 团队 ID（team 钱包必填）
        related_batch_id: 关联批次 ID
    返回:
        int: 扣减后新余额
    异常:
        FeaturePricingError(3001): 灵感币余额不足
        FeaturePricingError(3002): 配置/参数错误
    """
    amount = int(amount)
    if amount <= 0:
        # 无需扣减，返回当前余额
        return _read_balance(user_id, source_wallet, team_id)

    if source_wallet == 'team' and not team_id:
        raise FeaturePricingError('团队钱包扣费需要 team_id', code=3002, http_status=400)

    # 组装流水描述
    if feature_key:
        desc = f'[{feature_key}] {description}' if description else f'[{feature_key}] 扣减 {amount} 灵感币'
    else:
        desc = description or f'扣减 {amount} 灵感币'

    conn = pymysql.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with conn.cursor() as cursor:
            # 1. 锁定余额行（FOR UPDATE 防止并发扣减）
            if source_wallet == 'team':
                cursor.execute(
                    'SELECT pool_balance FROM teams WHERE id = %s FOR UPDATE',
                    (team_id,)
                )
            else:
                cursor.execute(
                    'SELECT personal_points FROM users WHERE id = %s FOR UPDATE',
                    (user_id,)
                )
            row = cursor.fetchone()
            if not row:
                msg = '团队不存在，无法扣费' if source_wallet == 'team' else '用户不存在，无法扣费'
                raise FeaturePricingError(msg, code=3008, http_status=404)

            balance = int(row['pool_balance'] if source_wallet == 'team' else row['personal_points'])

            # 2. 余额校验
            if balance < amount:
                raise FeaturePricingError('灵感币余额不足', code=3001, http_status=400)

            # 3. 扣减余额
            if source_wallet == 'team':
                cursor.execute(
                    'UPDATE teams SET pool_balance = pool_balance - %s WHERE id = %s',
                    (amount, team_id)
                )
            else:
                cursor.execute(
                    'UPDATE users SET personal_points = personal_points - %s WHERE id = %s',
                    (amount, user_id)
                )

            # 4. 插入积分流水（consume，amount 为负）
            cursor.execute(
                '''INSERT INTO points_records
                   (user_id, amount, type, source_wallet, team_id, related_batch_id, description)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                (user_id, -amount, 'consume', source_wallet, team_id, related_batch_id, desc)
            )

            # 5. 查询新余额
            if source_wallet == 'team':
                cursor.execute(
                    'SELECT COALESCE(pool_balance, 0) AS balance FROM teams WHERE id = %s',
                    (team_id,)
                )
            else:
                cursor.execute(
                    'SELECT COALESCE(personal_points, 0) AS balance FROM users WHERE id = %s',
                    (user_id,)
                )
            new_balance = int(cursor.fetchone()['balance'])

            conn.commit()
            return new_balance

    except FeaturePricingError:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        import traceback
        print(f'[deduct_coins] 扣费失败: user_id={user_id}, amount={amount}, '
              f'source_wallet={source_wallet}, team_id={team_id}, '
              f'error_type={type(e).__name__}, error={e}', flush=True)
        print(f'[deduct_coins] 堆栈: {traceback.format_exc()}', flush=True)
        raise FeaturePricingError('扣费失败，请稍后重试', code=3009, http_status=500)
    finally:
        conn.close()


def refund_coins(user_id, amount, source_wallet='personal', feature_key=None,
                 description='', team_id=None, related_batch_id=None):
    """
    退还灵感币（单连接事务：锁定余额 → 增加 → 记录流水）
    参数:
        user_id: 用户 ID
        amount: 退还金额（> 0，<=0 则直接返回当前余额）
        source_wallet: 钱包类型 (personal/team)
        feature_key: 功能标识（写入流水描述）
        description: 业务描述
        team_id: 团队 ID（team 钱包必填）
        related_batch_id: 关联批次 ID
    返回:
        int: 退还后新余额
    异常:
        FeaturePricingError(3002): 配置/参数错误或目标行不存在
    """
    amount = int(amount)
    if amount <= 0:
        return _read_balance(user_id, source_wallet, team_id)

    if source_wallet == 'team' and not team_id:
        raise FeaturePricingError('团队钱包退款需要 team_id', code=3002, http_status=400)

    # 组装流水描述（确保包含“退款”）
    if feature_key:
        desc = f'[{feature_key}] {description}' if description else f'[{feature_key}] 生成失败退款 {amount} 灵感币'
    else:
        desc = description or f'退款 {amount} 灵感币'

    conn = pymysql.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with conn.cursor() as cursor:
            # 1. 锁定余额行（同时校验目标行存在）
            if source_wallet == 'team':
                cursor.execute(
                    'SELECT pool_balance FROM teams WHERE id = %s FOR UPDATE',
                    (team_id,)
                )
            else:
                cursor.execute(
                    'SELECT personal_points FROM users WHERE id = %s FOR UPDATE',
                    (user_id,)
                )
            row = cursor.fetchone()
            if not row:
                msg = '团队不存在，无法退款' if source_wallet == 'team' else '用户不存在，无法退款'
                raise FeaturePricingError(msg, code=3002, http_status=404)

            # 2. 增加余额
            if source_wallet == 'team':
                cursor.execute(
                    'UPDATE teams SET pool_balance = pool_balance + %s WHERE id = %s',
                    (amount, team_id)
                )
            else:
                cursor.execute(
                    'UPDATE users SET personal_points = personal_points + %s WHERE id = %s',
                    (amount, user_id)
                )

            # 3. 插入积分流水（refund，amount 为正）
            cursor.execute(
                '''INSERT INTO points_records
                   (user_id, amount, type, source_wallet, team_id, related_batch_id, description)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                (user_id, amount, 'refund', source_wallet, team_id, related_batch_id, desc)
            )

            # 4. 查询新余额
            if source_wallet == 'team':
                cursor.execute(
                    'SELECT COALESCE(pool_balance, 0) AS balance FROM teams WHERE id = %s',
                    (team_id,)
                )
            else:
                cursor.execute(
                    'SELECT COALESCE(personal_points, 0) AS balance FROM users WHERE id = %s',
                    (user_id,)
                )
            new_balance = int(cursor.fetchone()['balance'])

            conn.commit()
            return new_balance

    except FeaturePricingError:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        import traceback
        print(f'[refund_coins] 退款失败: user_id={user_id}, amount={amount}, '
              f'source_wallet={source_wallet}, team_id={team_id}, '
              f'error_type={type(e).__name__}, error={e}', flush=True)
        print(f'[refund_coins] 堆栈: {traceback.format_exc()}', flush=True)
        raise FeaturePricingError('退款失败，请稍后重试', code=3002, http_status=500)
    finally:
        conn.close()


def get_display_name(feature_key):
    """
    获取功能展示名称
    参数:
        feature_key: 功能标识
    返回:
        str: display_name，找不到则返回 feature_key 本身
    """
    pricing = get_feature_pricing(feature_key, active_only=False)
    if pricing:
        return pricing.get('display_name') or feature_key
    return feature_key


def _read_balance(user_id, source_wallet='personal', team_id=None):
    """
    读取当前余额（无锁，用于 amount<=0 的快速返回场景）
    与 points_record_service.get_balance 数据源一致
    """
    conn = pymysql.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with conn.cursor() as cursor:
            if source_wallet == 'team' and team_id:
                cursor.execute(
                    'SELECT COALESCE(pool_balance, 0) AS balance FROM teams WHERE id = %s',
                    (team_id,)
                )
            else:
                cursor.execute(
                    'SELECT COALESCE(personal_points, 0) AS balance FROM users WHERE id = %s',
                    (user_id,)
                )
            row = cursor.fetchone()
            return int(row['balance']) if row else 0
    finally:
        conn.close()


# ============================================================
# 功能标识注册表 —— 所有可用的 feature_key 及元数据
# 与后端路由/工作流中硬编码的 feature_key 一一对应
# ============================================================
FEATURE_KEY_REGISTRY = [
    {
        'feature_key': 'ai_product_image.smart_mode',
        'display_name': '智能商品图',
        'description': 'AI 智能商品图生成（智能模式），按图片分辨率计费，支持 1K/2K/4K 三档',
        'category': 'ai_product_image',
        'pricing_type': 'per_image_resolution',
    },
    {
        'feature_key': 'ai_product_image.pro_mode',
        'display_name': '专业商品图',
        'description': 'AI 专业商品图生成（专业模式），按图片分辨率计费，支持 1K/2K/4K 三档',
        'category': 'ai_product_image',
        'pricing_type': 'per_image_resolution',
    },
    {
        'feature_key': 'ai_product_image.batch',
        'display_name': '批量套图',
        'description': 'AI 批量套图编排生成（批量模式），按图片分辨率计费，支持 1K/2K/4K 三档',
        'category': 'ai_product_image',
        'pricing_type': 'per_image_resolution',
    },
    {
        'feature_key': 'toolbox.text_to_image',
        'display_name': '文生图',
        'description': 'AI 工具箱 — 根据文字描述生成图片，按次计费',
        'category': 'ai_toolbox',
        'pricing_type': 'per_use',
    },
    {
        'feature_key': 'toolbox.image_merge',
        'display_name': '图片合并',
        'description': 'AI 工具箱 — 将 2-10 张图片合并为一张，按次计费',
        'category': 'ai_toolbox',
        'pricing_type': 'per_use',
    },
    {
        'feature_key': 'toolbox.plan_analysis',
        'display_name': '生图计划分析',
        'description': 'AI 工具箱 — 分析商品图片并生成优化方案，按次计费',
        'category': 'ai_toolbox',
        'pricing_type': 'per_use',
    },
    {
        'feature_key': 'toolbox.chat_gen',
        'display_name': '对话式生图',
        'description': 'AI 工具箱 — 通过多轮对话逐步生成图片，按次计费',
        'category': 'ai_toolbox',
        'pricing_type': 'per_use',
    },
    {
        'feature_key': 'toolbox.product_replace',
        'display_name': '产品替换',
        'description': 'AI 工具箱 — 替换图片中的产品，按次计费',
        'category': 'ai_toolbox',
        'pricing_type': 'per_use',
    },
    {
        'feature_key': 'toolbox.ai_model',
        'display_name': 'AI模特',
        'description': 'AI 工具箱 — 生成 AI 模特穿着商品图，按次计费',
        'category': 'ai_toolbox',
        'pricing_type': 'per_use',
    },
    {
        'feature_key': 'toolbox.model_product',
        'display_name': '模特商品图',
        'description': 'AI 工具箱 — 使用模特生成商品展示图，按次计费',
        'category': 'ai_toolbox',
        'pricing_type': 'per_use',
    },
    {
        'feature_key': 'toolbox.prompt_reverse',
        'display_name': '反推提示词',
        'description': 'AI 工具箱 — 根据图片反推生成提示词，按次计费',
        'category': 'ai_toolbox',
        'pricing_type': 'per_use',
    },
]


def get_feature_key_options():
    """返回所有可用的功能标识选项列表，供管理员创建定价时选择"""
    return FEATURE_KEY_REGISTRY
