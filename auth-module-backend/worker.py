"""
ARQ 异步任务 Worker
启动方式：cd auth-module-backend && python worker.py

任务注册：业务模块中使用 services.task_queue.register_task 装饰器注册任务函数，
并在本文件 import 业务模块以确保注册表生效，WorkerSettings.functions 自动收集。
"""
import asyncio

from arq import func, run_worker
from arq.connections import RedisSettings, create_pool

from services.task_queue import (
    REDIS_URL,
    TASK_REGISTRY,
    register_task,
    set_progress,
    complete_task,
)

# ── Task 7 迁移：业务任务模块导入（触发 register_task 注册到 TASK_REGISTRY）──
import services.toolbox_service        # noqa: F401  toolbox_image_merge / toolbox_product_replace
import services.plan_analysis_queue    # noqa: F401  toolbox_plan_analysis
import services.model_product_service  # noqa: F401  toolbox_model_product
import services.batch_orchestrator     # noqa: F401  batch_generation
import workflows.smart_generation      # noqa: F401  generation_smart
import workflows.pro_generation        # noqa: F401  generation_pro_confirm
import routes.generation               # noqa: F401  generation_retry

# 编辑器工具执行任务注册（import 触发 controllers/editor/tools/tasks.py 的 @register_task）
import controllers.editor.tools.tasks  # noqa: F401

# 编辑器 Agent 计划执行任务注册（Task 10）
import controllers.editor.agent.executor  # noqa: F401  editor_agent_execute


@register_task('demo_progress')
async def demo_progress(ctx, payload: dict, task_id: str):
    """
    内置演示任务：按 payload.steps 分步推进进度，用于验证 Redis + ARQ + SSE 全链路
    payload 示例：{'steps': 5, '任意回显字段': '...'}
    """
    steps = max(1, int(payload.get('steps', 5)))
    for i in range(1, steps + 1):
        await set_progress(ctx, task_id, f'执行第 {i}/{steps} 步', pct=int(i * 100 / steps))
        await asyncio.sleep(0.5)
    await complete_task(ctx, task_id, {'echo': payload})


async def on_startup(ctx):
    """Worker 启动：创建 Redis 连接池并放入 ctx（供 set_progress 等使用）"""
    ctx['redis'] = await create_pool(RedisSettings.from_dsn(REDIS_URL))


async def on_shutdown(ctx):
    """Worker 关闭：释放 Redis 连接池"""
    pool = ctx.get('redis')
    if pool is not None:
        await pool.aclose()


class WorkerSettings:
    """ARQ Worker 配置（run_worker 入口）"""
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    on_startup = on_startup
    on_shutdown = on_shutdown
    # 注册表中的任务名可能与函数名不同，用 arq.func 显式指定 job name
    functions = [func(fn, name=name) for name, fn in TASK_REGISTRY.items()]


if __name__ == '__main__':
    # 直接调用 run_worker 不会自动配置日志（默认只有 WARNING 以上才会输出），
    # 显式配置后容器内 `docker compose logs worker` 才能看到 worker 启动与任务执行日志
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s in %(name)s: %(message)s',
    )
    run_worker(WorkerSettings)
