"""批量套图编排服务（P1-1）

职责：
- expand_tasks：商品 × 站点 × 图型 笛卡尔积展开，按 item_key（product_site_imagetype）去重
- estimate_cost：按 calculate_image_cost(feature_key, size) 估算总灵感币
- run_batch_task（ARQ 任务 batch_generation）：batch_size=5 分批循环执行子任务，
  失败隔离（单项异常不中断批次）、每项完成/失败后更新 item 与批次计数器并经
  set_progress 发布到 task:{batch_task_id}（前端复用现有 SSE 端点）、
  断点续跑（只跑 failed/planned 项，completed 天然跳过）、失败项即时退款。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【对账口径】（预扣 / 退款 / 重试的资金流，务必与 routes/batch_routes.py 保持一致）
1. 预扣：POST /api/v1/batch/tasks 提交时一次性预扣 coins_locked = ∑item.coins
   （每项 coins = calculate_image_cost(feature_key, size) 单价，同一批次内同 size 单价相同）。
2. 失败退款：worker 执行中子任务失败 → 即时 refund_coins(item.coins) 全额退还该项，
   退款成功后调用 reset_item_coins 把该 item 的 coins 置 0，作为"该项费用已退"标记。
3. 重试（retry）：重新 submit_task 只跑 failed/planned 项，不再预扣——
   - 重试成功：该项费用维持"已退"状态（coins=0），用户免费获得该图作为失败补偿，
     不产生任何新扣费，也不重复退款；
   - 重试再失败：该项 coins 已在首次失败时置 0，不再重复退款（原 coins_locked 早已
     含该项退款，资金已回到用户钱包，重复退款会造成资损）。
   由此恒等式恒成立：用户实付 = coins_locked − ∑退款 = ∑(completed 项的 coins)。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import asyncio
import hashlib
from typing import Any, Dict, List, Optional, Tuple

from services.task_queue import register_task, set_progress, complete_task, fail_task
from services.multilang_engine import build_prompt, normalize_image_type
from services.compliance_service import apply_platform_constraints, normalize_platform
from services.generation_service import call_image_edit_model
from services.feature_pricing_service import calculate_image_cost, refund_coins
from services.style_lock import derive_style_lock
from services.compliance_review_service import review_image
from config import Config
from models.batch_task import BatchTaskModel

# 每批子任务数（分批循环执行）
BATCH_SIZE = 5

# 计费键：优先批量专用键；DB 未配置其定价时回退 smart_mode（同为按分辨率计价）
BATCH_FEATURE_KEY = 'ai_product_image.batch'
FALLBACK_FEATURE_KEY = 'ai_product_image.smart_mode'

# 图组预设（P1-3）：image_group → 固定图型组合与逐图型尺寸
# tiktok_showcase：TikTok 三图组合——白底主图 1:1 / 模特场景图 1:1 / 竖版详情图 9:16
IMAGE_GROUPS: Dict[str, dict] = {
    'tiktok_showcase': {
        'label': 'TikTok 三图组合（主图/场景/详情）',
        'image_types': ['main', 'scene', 'detail'],
        'sizes': {
            'main': '1024x1024',
            'scene': '1024x1024',
            'detail': '1024x1820',
        },
    },
}


def make_item_key(product_id: Any, site: Any, image_type: str) -> str:
    """幂等键：product_site_imagetype（超长时以 md5 兜底，保证 ≤128 且稳定）"""
    raw = f"{str(product_id).strip()}_{str(site).strip().upper()}_{str(image_type).strip().lower()}"
    if len(raw) > 120:
        raw = 'px_' + hashlib.md5(raw.encode('utf-8')).hexdigest()
    return raw


def expand_tasks(products: List[dict], sites: List[Any], image_types: List[str],
                 platform: Any, image_group: Optional[str] = None) -> Tuple[List[dict], List[str]]:
    """展开子任务：products × sites × image_types 笛卡尔积，按 item_key 去重

    Args:
        image_group: 可选图组预设（IMAGE_GROUPS 键）。传入时 image_types 被
            固定为该图组的图型组合，且每项携带图组定义的逐项尺寸（item['size']），
            供 estimate_cost 逐项计价与 worker 逐项生成分辨率使用。
            未知图组抛 ValueError。

    Returns:
        (items, warnings)
        items 元素：{item_key, product_id, site, image_type[, size]}
        warnings：去重提示列表
    Raises:
        ValueError: 图型非法（multilang_engine.normalize_image_type 校验）/
            图组预设未知
    """
    items: List[dict] = []
    warnings: List[str] = []
    seen = set()
    normalize_platform(platform)  # 归一化仅作校验用途，key 生成不依赖平台

    group: Optional[dict] = None
    if image_group:
        group = IMAGE_GROUPS.get(str(image_group).strip().lower())
        if group is None:
            raise ValueError(
                f'未知图组预设: {image_group}（支持 {"/".join(sorted(IMAGE_GROUPS))}）'
            )
        image_types = group['image_types']

    for product in products:
        product_id = str((product or {}).get('product_id') or '').strip()
        for site in sites:
            site_key = str(site or '').strip().upper()
            for image_type in image_types:
                img_type = normalize_image_type(image_type)  # 非法图型抛 ValueError
                key = make_item_key(product_id, site_key, img_type)
                if key in seen:
                    warnings.append(f'重复子任务已去重: {key}')
                    continue
                seen.add(key)
                entry = {
                    'item_key': key,
                    'product_id': product_id,
                    'site': site_key,
                    'image_type': img_type,
                }
                if group is not None:
                    entry['size'] = group['sizes'].get(img_type)
                items.append(entry)
    return items, warnings


def estimate_cost(items: List[dict], feature_key: str, size: str) -> Tuple[int, int]:
    """估算总灵感币：逐项按自身尺寸计价（图组模式 items 各带 size），
    无 size 的项回退默认 size；单项费用同时写回 dict 项的 'coins' 字段
    （非 dict 项仅计数，不写回）。

    预扣口径不变：total = ∑item.coins。

    Returns:
        (unit_cost, total_cost)
        全部子任务同价时 unit_cost 为该单价；价格不唯一（图组逐项计价）时
        unit_cost 为 0，调用方应以 ∑item.coins / 落库行 coins 求和为准。
    """
    total = 0
    prices = set()
    for it in items:
        item_size = it.get('size') if isinstance(it, dict) else None
        cost = int(calculate_image_cost(feature_key, item_size or size) or 0)
        if isinstance(it, dict):
            it['coins'] = cost
        prices.add(cost)
        total += cost
    unit_cost = prices.pop() if len(prices) == 1 else 0
    return unit_cost, total


def resolve_batch_feature_key(size: str, feature_key: Optional[str] = None) -> str:
    """解析批量套图计费键

    优先使用调用方显式传入的 feature_key；未传时使用批量专用键
    ai_product_image.batch，若其定价未配置（calculate_image_cost 返回 0）
    则回退 ai_product_image.smart_mode（同为 per_image_resolution 计价，
    保证存量环境未补种定价数据时计费仍然正确）。
    """
    if feature_key:
        return feature_key
    if calculate_image_cost(BATCH_FEATURE_KEY, size) > 0:
        return BATCH_FEATURE_KEY
    return FALLBACK_FEATURE_KEY


def _chunked(items: List[dict], size: int) -> List[List[dict]]:
    """按 batch_size 切分（分批循环执行）"""
    return [items[i:i + size] for i in range(0, len(items), size)]


def _final_batch_status(total: int, succeeded: int, failed: int) -> str:
    """批次最终状态：全部成功 completed / 全部失败 failed / 部分成功 partial"""
    if total <= 0:
        return 'completed'
    if failed == 0:
        return 'completed'
    if succeeded == 0:
        return 'failed'
    return 'partial'


@register_task('batch_generation')
async def run_batch_task(ctx, payload: dict, task_id: str):
    """批量套图编排 ARQ 任务

    payload: {
        batch_task_id: 'batch-xxx',   # 进度发布与状态写入的 SSE key（task:{batch_task_id}）
        user_id, platform, size, feature_key,
        products: [{product_id, product_image(base64), ...}],
        reference_image?, reference_text?,
        source_wallet?, team_id?,
    }

    - 断点续跑：只执行 failed/planned 子任务（list_retry_items），completed 天然跳过；
      首次执行时全部为 planned，语义一致。
    - 失败隔离：单项异常捕获落 failed 并即时退款，不中断批次。
    - 进度：每项结束后 update_batch_counters + set_progress(task:{batch_task_id})。
    """
    model = BatchTaskModel()
    batch_task_id = str(payload.get('batch_task_id') or '')
    state_key = batch_task_id or task_id  # 进度/终态写入的 Redis key
    user_id = payload.get('user_id')
    platform = payload.get('platform', '')
    size = payload.get('size', '1024x1024')
    feature_key = payload.get('feature_key') or BATCH_FEATURE_KEY
    source_wallet = payload.get('source_wallet') or 'personal'
    team_id = payload.get('team_id')
    reference_image = payload.get('reference_image')
    reference_text = payload.get('reference_text')
    products_by_id = {
        str((p or {}).get('product_id')).strip(): (p or {})
        for p in (payload.get('products') or [])
    }

    batch = model.get_batch_by_task_id(batch_task_id) if batch_task_id else None
    if batch is None:
        await fail_task(ctx, state_key, f'批次不存在: {batch_task_id}')
        return

    try:
        model.update_batch_status(batch.id, 'running')
        await set_progress(ctx, state_key, '开始执行批量套图', pct=0,
                           succeeded=batch.succeeded_items, failed=batch.failed_items)

        # ── Task 7 Style Lock：批次开始时派生一次（确定性），
        #    前置到本批次每项 prompt，保证同批次成图风格统一 ──
        first_product = next(iter(products_by_id.values()), {}) or {}
        style_lock = derive_style_lock(
            first_product,
            first_product.get('scene_zh'),
            platform=platform,
            user_hint=payload.get('style_lock_hint'),
        )

        # 断点续跑：仅取 failed/planned（completed 项跳过；首次执行全为 planned）
        items = model.list_retry_items(batch.id)
        if not items:
            counters = model.update_batch_counters(batch.id)
            final = _final_batch_status(counters['total_items'],
                                        counters['succeeded_items'],
                                        counters['failed_items'])
            model.update_batch_status(batch.id, final)
            await complete_task(ctx, state_key, {
                'batch_task_id': batch.task_id,
                'batch_status': final,
                'message': '无可执行子任务（均已成功或无失败项）',
                **counters,
            })
            return

        for chunk in _chunked(items, BATCH_SIZE):
            for item in chunk:
                await _run_single_item(
                    ctx, model, batch, item, state_key,
                    user_id=user_id, platform=platform, size=size,
                    feature_key=feature_key, source_wallet=source_wallet,
                    team_id=team_id, reference_image=reference_image,
                    reference_text=reference_text,
                    products_by_id=products_by_id,
                    style_lock=style_lock,
                )

        counters = model.update_batch_counters(batch.id)
        final = _final_batch_status(counters['total_items'],
                                    counters['succeeded_items'],
                                    counters['failed_items'])
        model.update_batch_status(batch.id, final)
        result = {
            'batch_task_id': batch.task_id,
            'batch_status': final,
            'message': f'批量套图结束: 成功 {counters["succeeded_items"]}/{counters["total_items"]}',
            **counters,
        }
        if final == 'failed':
            # 全部失败：批次终态 failed（各失败项已即时退款）
            await fail_task(ctx, state_key, result['message'])
        else:
            # 全部成功 / 部分成功：编排任务本身正常结束，计数在 result 中
            await complete_task(ctx, state_key, result)
    except Exception as e:
        # 编排级异常（非单项失败）：批次置 failed；已扣费用的子任务各自状态保持，
        # 可通过 retry 续跑（failed/planned 仍会被拾起）
        print(f'[批量套图] 编排任务异常 batch={batch.task_id}: {e}', flush=True)
        import traceback
        print(traceback.format_exc(), flush=True)
        try:
            model.update_batch_counters(batch.id)
            model.update_batch_status(batch.id, 'failed')
        except Exception:
            pass
        await fail_task(ctx, state_key, f'批量套图编排失败: {e}')


async def _run_single_item(ctx, model: BatchTaskModel, batch, item, state_key: str, *,
                           user_id, platform, size, feature_key, source_wallet,
                           team_id, reference_image, reference_text, products_by_id,
                           style_lock: str = ''):
    """执行单个子任务：running → 生图 → completed/failed（失败隔离 + 即时退款 + 进度发布）"""
    try:
        model.update_item_status(item.id, 'running')

        product = products_by_id.get(str(item.product_id or '').strip()) or {}
        product_image = product.get('product_image')
        if not product_image:
            raise ValueError(f'商品图缺失: product_id={item.product_id}')

        # prompt 已在提交时预生成；此处再做平台约束增强（apply 幂等，不重复注入）
        prompt = apply_platform_constraints(platform, item.image_type, item.prompt or '')
        # Task 7 Style Lock：同批次每图 prompt 前置同一锁定文本
        # （置于引擎/平台约束文本之前、主体描述之前；已含则不重复，幂等）
        if style_lock and style_lock not in (item.prompt or ''):
            prompt = f'{style_lock} {prompt}'

        # Task 8 图组模式：逐项使用自身尺寸（无 size 的项回退批次默认尺寸）
        item_size = getattr(item, 'size', None) or size

        result = await asyncio.to_thread(
            call_image_edit_model, product_image, prompt, item_size,
            reference_image, reference_text,
            user_id=user_id,
        )
        result = result or {}
        result_url = result.get('url') or ''
        if not result_url and result.get('b64_json'):
            # b64 结果落盘为本地 URL（result_url 列 VARCHAR(512)，不能存 base64）
            from services.image_storage_service import save_base64_image
            result_url = save_base64_image(result['b64_json'], user_id, prefix='batch')
        if not result_url:
            raise ValueError('生图结果缺少 URL/b64_json')

        model.update_item_status(item.id, 'completed', result_url=result_url)

        # ── Task 9 AI 视觉合规审查：completed 后、更新计数器前触发；
        #    开关关闭或无平台时跳过；审查异常不阻断批次（记 unknown）──
        if Config.COMPLIANCE_REVIEW_ENABLED and str(platform or '').strip():
            try:
                review = await asyncio.to_thread(
                    review_image, result_url, platform, item.image_type,
                    user_id=user_id)
            except Exception as review_err:
                print(f'[批量套图] 合规审查异常（记 unknown，不阻断）'
                      f'batch={batch.task_id} item={item.item_key}: {review_err}',
                      flush=True)
                review = {
                    'riskLevel': 'unknown',
                    'issues': [{'rule': 'review_error',
                                'detail': str(review_err)[:300]}],
                    'fixSuggestions': [],
                }
            try:
                model.set_item_review(item.id, review)
            except Exception as store_err:
                print(f'[批量套图] 审查结果落库失败 item={item.item_key}: '
                      f'{store_err}', flush=True)
    except Exception as e:
        # 失败隔离：单项异常不中断批次
        err = str(e)[:500]
        print(f'[批量套图] 子任务失败 batch={batch.task_id} item={item.item_key}: {err}', flush=True)
        try:
            model.update_item_status(item.id, 'failed', error=err)
        except Exception as mark_err:
            print(f'[批量套图] 标记失败状态异常 item={item.id}: {mark_err}', flush=True)
        # 失败即时退款（对账口径见模块注释）：
        # 仅当 item.coins > 0（未退过；已退款项 coins 已被置 0）才退，防重复退款
        if item.coins and int(item.coins) > 0:
            try:
                refund_coins(
                    user_id, int(item.coins),
                    source_wallet=source_wallet, team_id=team_id,
                    feature_key=feature_key,
                    description='批量套图-子任务失败退款',
                    related_batch_id=batch.task_id,
                )
                model.reset_item_coins(item.id)
            except Exception as refund_err:
                print(f'[批量套图] 退款失败 batch={batch.task_id} item={item.id}: '
                      f'{refund_err}', flush=True)

    # 每项结束：重算计数器并发布批次级进度（前端复用现有 SSE 端点）
    counters = model.update_batch_counters(batch.id)
    done = counters['succeeded_items'] + counters['failed_items']
    total = counters['total_items'] or 0
    pct = int(done * 100 / total) if total > 0 else 100
    await set_progress(
        ctx, state_key, f'已完成 {done}/{total} 项', pct=pct,
        succeeded=counters['succeeded_items'], failed=counters['failed_items'],
        batch_status='running',
    )
