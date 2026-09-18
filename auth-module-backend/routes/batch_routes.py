"""批量套图编排路由（P1-1）

POST /api/v1/batch/tasks                提交批次（dry-run 预检 + 预扣 + 建批 + 入队）
GET  /api/v1/batch/tasks/<id>/manifest  批次清单（批次头 + 子任务分页/状态筛选）
POST /api/v1/batch/tasks/<id>/retry     断点续跑（仅重跑 failed/planned 项，不重复扣费）

进度订阅：批次级进度经 services.task_queue.set_progress 发布到 task:{batch_task_id}，
前端复用现有 SSE 端点 GET /api/v1/sse/tasks/<batch_task_id>，无新增 SSE 端点。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【对账口径】（与 services/batch_orchestrator.py 模块注释一致）
1. 预扣：本路由提交时一次性预扣 coins_locked = ∑item.coins（每项单价
   calculate_image_cost(feature_key, size)，同批次同 size 单价一致）。
2. 幂等去重：item_key（product_site_imagetype）全局唯一，INSERT IGNORE 落库；
   实际落库子任务数少于展开数（重复提交同商品/同站点/同图型）时，差额立即退款，
   重复部分不重复计费；全部重复（0 项落库）则全额退款并返回 400。
3. 失败退款：worker 中子任务失败即时 refund_coins(item.coins)，退款后该项 coins 置 0。
4. 重试：重新 submit_task 只跑 failed/planned 项，不再预扣——
   重试成功不退不扣（费用已在首次失败时退还，用户免费获图作为补偿）；
   重试再失败不再退款（coins 已为 0，防止对同一笔预扣重复退款造成资损）。
   恒等式：用户实付 = coins_locked − ∑退款 = ∑(completed 项的 coins)。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import uuid

from flask import Blueprint, request, jsonify, g

from middleware.auth_middleware import token_required
from services.multilang_engine import (
    build_prompt, validate_selling_points, SUPPORTED_SITES,
)
from services.compliance_service import apply_platform_constraints, normalize_platform
from services.feature_pricing_service import (
    calculate_image_cost, deduct_coins, refund_coins, FeaturePricingError,
)
from services.user_ai_provider_service import is_feature_byok
from services.task_queue import submit_task, seed_task_state
from services.batch_orchestrator import (
    expand_tasks, estimate_cost, resolve_batch_feature_key, IMAGE_GROUPS,
)
from models.batch_task import BatchTaskModel, ITEM_STATUSES

batch_bp = Blueprint('batch', __name__, url_prefix='/api/v1/batch')

# 入参规模上限（防止误操作超大批次）
MAX_PRODUCTS = 50
MAX_SITES = 20
MAX_IMAGE_TYPES = 10
MAX_ITEMS = 500


def _err(code, message, http_status=400):
    return jsonify({'code': code, 'message': message, 'data': None}), http_status


def _user_id():
    return g.current_user['user_id']


@batch_bp.route('/tasks', methods=['POST'])
@token_required
def create_batch_task_api():
    """提交批量套图批次

    Request Body:
    {
        "products": [{
            "product_id": "p1",
            "product_name": "商品名（中文可选）",
            "product_image": "base64 商品图（必填，非空）",
            "title_en": "英文商品名（可选）",
            "selling_points": [{zh_title, zh_desc, en_title, en_desc, visual_keywords}],
            "scene_zh": "中文场景（可选）",
            "include_model": false
        }],
        "sites": ["US", "DE"],
        "image_types": ["main", "scene", "detail"],
        "image_group": "可选图组预设（如 tiktok_showcase，传入时覆盖 image_types 并逐项定尺寸）",
        "style_lock_hint": "可选批次级风格提示（Style Lock，透传给编排器派生统一风格约束）",
        "platform": "amazon",
        "size": "1024x1024",
        "feature_key": "可选，缺省 ai_product_image.batch（未配置定价时回退 smart_mode）",
        "reference_image": "可选风格参考图 base64",
        "reference_text": "可选参考维度描述"
    }

    Response data: {batch_task_id, total_items, coins_locked, unit_cost,
                    feature_key, image_group, task_id(ARQ), warnings}
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return _err(4001, '请求参数不能为空')

        products = data.get('products') or []
        sites = data.get('sites') or []
        image_types = data.get('image_types') or []
        platform = normalize_platform(data.get('platform', ''))
        size = data.get('size', '1024x1024')
        reference_image = data.get('reference_image')
        reference_text = data.get('reference_text')
        image_group = data.get('image_group') or None
        style_lock_hint = data.get('style_lock_hint')

        if not products:
            return _err(4001, 'products 不能为空')
        if len(products) > MAX_PRODUCTS:
            return _err(4001, f'商品数量超出上限 {MAX_PRODUCTS}')
        if not sites:
            return _err(4001, 'sites 不能为空')
        if len(sites) > MAX_SITES:
            return _err(4001, f'站点数量超出上限 {MAX_SITES}')
        # 图组模式下 image_types 可省略（由图组预设固定）；非图组模式仍必填
        if not image_types and not image_group:
            return _err(4001, 'image_types 不能为空')
        if image_group and str(image_group).strip().lower() not in IMAGE_GROUPS:
            return _err(4001,
                        f'未知图组预设: {image_group}'
                        f'（支持 {"/".join(sorted(IMAGE_GROUPS))}）')
        if not image_group and len(image_types) > MAX_IMAGE_TYPES:
            return _err(4001, f'图型数量超出上限 {MAX_IMAGE_TYPES}')

        # ── dry-run 预检 1：商品字段核对（product_id / 商品图非空 / 卖点结构）──
        for p in products:
            p = p or {}
            pid = str(p.get('product_id') or '').strip()
            if not pid:
                return _err(4001, 'products[].product_id 不能为空')
            if not str(p.get('product_image') or '').strip():
                return _err(4001, f'商品 {pid} 缺少商品图（product_image 不能为空）')
            _valid_sps, sp_errors = validate_selling_points(p.get('selling_points'))
            if sp_errors:
                return _err(4001, f'商品 {pid} 卖点校验失败: {sp_errors[0]}')

        # ── dry-run 预检 2：站点核对（批量涉及预扣费，严格校验不静默回退）──
        for site in sites:
            if str(site or '').strip().upper() not in SUPPORTED_SITES:
                return _err(4001, f'站点 {site} 不受支持，请检查站点码')

        # ── dry-run 预检 3：展开计数 + 费用预估（图型非法在 expand 中抛 ValueError）──
        try:
            items, warnings = expand_tasks(products, sites, image_types, platform,
                                           image_group=image_group)
        except ValueError as e:
            return _err(4001, str(e))
        if not items:
            return _err(4001, '展开后无有效子任务')
        if len(items) > MAX_ITEMS:
            return _err(4001, f'子任务总数超出上限 {MAX_ITEMS}（当前 {len(items)}）')

        feature_key = resolve_batch_feature_key(size, data.get('feature_key'))
        unit_cost, total_cost = estimate_cost(items, feature_key, size)

        user_id = _user_id()
        batch_task_id = f'batch-{uuid.uuid4().hex[:12]}'

        # ── BYOK：命中用户自备生图通道时全程不扣费（单价/总价/各项 coins 均置 0，
        #    据此跳过预扣、幂等差额退款与 worker 中的子任务失败退款）──
        if is_feature_byok(user_id, 'ai_product_image.batch'):
            unit_cost = 0
            total_cost = 0
            for it in items:
                it['coins'] = 0

        # ── 预扣灵感币（一次扣 ∑item.coins；子任务失败在 worker 内即时退款；
        #    retry 不再预扣，详见文件头对账口径）──
        deducted = False
        if total_cost > 0:
            try:
                deduct_coins(
                    user_id=user_id,
                    amount=total_cost,
                    feature_key=feature_key,
                    description=f'批量套图预扣 {len(items)} 张',
                    related_batch_id=batch_task_id,
                )
                deducted = True
            except FeaturePricingError as e:
                return _err(e.code, e.message, e.http_status)

        # ── 预生成每项 prompt（引擎组装 + 平台约束增强）──
        products_by_id = {str((p or {}).get('product_id')).strip(): (p or {})
                          for p in products}
        item_rows = []
        for it in items:
            p = products_by_id[it['product_id']]
            valid_sps, _ = validate_selling_points(p.get('selling_points'))
            prompt = build_prompt(
                {
                    'title_en': p.get('title_en') or p.get('product_name_en') or '',
                    'include_model': p.get('include_model'),
                },
                valid_sps,
                p.get('scene_zh'),
                it['site'],
                it['image_type'],
            )
            prompt = apply_platform_constraints(platform, it['image_type'], prompt)
            # coins 由 estimate_cost 逐项写回（图组按各自 size 计价；非图组=unit_cost）
            item_rows.append({**it, 'prompt': prompt,
                              'coins': it.get('coins', unit_cost)})

        # ── 建批 + 子任务落库（INSERT IGNORE 幂等去重）+ 入队 ARQ ──
        payload = {
            'batch_task_id': batch_task_id,
            'user_id': user_id,
            'platform': platform,
            'size': size,
            'feature_key': feature_key,
            'products': products,
            'reference_image': reference_image,
            'reference_text': reference_text,
            'image_group': image_group,
            'style_lock_hint': style_lock_hint,
            'source_wallet': 'personal',
            'team_id': None,
        }
        model = BatchTaskModel()
        batch = model.create_batch_task(
            task_id=batch_task_id, user_id=user_id, items=item_rows,
            feature_key=feature_key, coins_locked=total_cost,
            platform=platform or None, params=payload,
        )

        # ── 幂等去重对账：实际落库数 < 展开数 → 差额立即退款（重复提交不重复计费）──
        actual_items = batch.total_items
        if image_group:
            # 图组逐项计价：实际预扣以落库行 coins 求和为准（INSERT IGNORE 去重后）
            actual_coins = model.sum_items_coins(batch.id)
        else:
            actual_coins = unit_cost * actual_items
        if actual_items == 0:
            # 全部子任务已存在（重复提交）：全额退款，批次不可执行
            if deducted:
                refund_coins(
                    user_id, total_cost, feature_key=feature_key,
                    description='批量套图-幂等去重退款（子任务全部已存在）',
                    related_batch_id=batch_task_id,
                )
            model.update_batch_status(batch.id, 'failed')
            return _err(4001, '所有子任务均已存在（幂等去重），请勿重复提交同一商品/站点/图型')

        if actual_coins < total_cost:
            refund_coins(
                user_id, total_cost - actual_coins, feature_key=feature_key,
                description='批量套图-幂等去重退款（重复子任务差额）',
                related_batch_id=batch_task_id,
            )
            model.update_coins_locked(batch.id, actual_coins)
            total_cost = actual_coins
            warnings.append('部分子任务已存在（幂等去重），差额灵感币已退还')

        # 预置批次级 SSE 初始状态（queued），worker 领取前前端即可订阅
        seed_task_state(batch_task_id, module='batch')
        arq_task_id = submit_task('batch_generation', payload, module='batch')

        return jsonify({
            'code': 0,
            'message': 'success',
            'data': {
                'batch_task_id': batch_task_id,
                'total_items': actual_items,
                'coins_locked': total_cost,
                'unit_cost': unit_cost,
                'feature_key': feature_key,
                'image_group': image_group,
                'task_id': arq_task_id,
                'warnings': warnings,
            },
        })

    except FeaturePricingError as e:
        return _err(e.code, e.message, e.http_status)
    except Exception as e:
        return _err(5001, f'批量任务提交失败: {e}', 500)


@batch_bp.route('/tasks/<task_id>/manifest', methods=['GET'])
@token_required
def get_batch_manifest(task_id):
    """批次清单：批次头 + 子任务列表

    Query: ?status=planned|running|completed|failed&page=1&page_size=50
    注意：failed 项 coins=0 表示该项费用已退款（对账口径见文件头）。
    """
    try:
        model = BatchTaskModel()
        batch = model.get_batch_by_task_id(task_id)
        # 归属校验：非本人批次与不存在批次同样返回 404（不泄露存在性）
        if batch is None or batch.user_id != _user_id():
            return _err(4004, '批次不存在或已删除', 404)

        status = request.args.get('status') or None
        if status is not None and status not in ITEM_STATUSES:
            return _err(4001, f'非法状态筛选: {status}（支持 {"/".join(ITEM_STATUSES)}）')
        try:
            page = max(1, int(request.args.get('page', 1)))
            page_size = max(1, min(int(request.args.get('page_size', 50)), 200))
        except (TypeError, ValueError):
            return _err(4001, 'page/page_size 必须为整数')

        items = model.list_items(
            batch.id, status=status,
            limit=page_size, offset=(page - 1) * page_size,
        )
        total = model.count_items(batch.id, status=status)
        counts = model.count_items_by_status(batch.id)

        return jsonify({
            'code': 0,
            'message': 'success',
            'data': {
                'batch': batch.to_dict(),
                'items': [i.to_dict() for i in items],
                'page': page,
                'page_size': page_size,
                'total': total,
                'counts': counts,
            },
        })

    except Exception as e:
        return _err(5001, f'批次清单查询失败: {e}', 500)


@batch_bp.route('/tasks/<task_id>/retry', methods=['POST'])
@token_required
def retry_batch_task(task_id):
    """断点续跑：重新入队 batch_generation，只执行 failed/planned 项

    - 不重复扣费：原 coins_locked 已含失败项退款（失败即退、退款后 coins 置 0），
      重试成功则不退不扣（免费补偿），重试再失败也不再退款（防止重复退款），
      详见文件头对账口径。
    - completed 批次且无失败/待执行项 → 400。
    """
    try:
        model = BatchTaskModel()
        batch = model.get_batch_by_task_id(task_id)
        if batch is None or batch.user_id != _user_id():
            return _err(4004, '批次不存在或已删除', 404)

        if batch.status == 'running':
            return _err(4001, '批次正在执行中，无需重试')

        retry_items = model.list_retry_items(batch.id)
        if not retry_items:
            return _err(4001, '批次无失败/待执行子任务，无需重试')

        # 复用提交时的参数快照（含商品图/参考图），worker 端只跑 failed/planned 项
        payload = dict(batch.params or {})
        if not payload:
            return _err(5001, '批次参数快照缺失，无法重试', 500)
        payload['batch_task_id'] = batch.task_id
        payload.setdefault('user_id', batch.user_id)

        seed_task_state(batch.task_id, module='batch')
        arq_task_id = submit_task('batch_generation', payload, module='batch')

        return jsonify({
            'code': 0,
            'message': 'success',
            'data': {
                'batch_task_id': batch.task_id,
                'retry_items': len(retry_items),
                'task_id': arq_task_id,
            },
        })

    except FeaturePricingError as e:
        return _err(e.code, e.message, e.http_status)
    except Exception as e:
        return _err(5001, f'批次重试失败: {e}', 500)
