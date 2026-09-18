"""
编辑器通用工具执行异步任务

流程：加载图片 → registry 分发到工具纯函数 → 结果图存盘 → complete_task
worker.py 通过 import 本模块触发 @register_task 注册。
"""
import io
import os
import base64

from PIL import Image

from services.task_queue import register_task, set_progress, complete_task, fail_task
from services.image_storage_service import save_image_bytes, get_image_path
from controllers.editor.tools.registry import get_tool
from models.editor_task import EditorTaskModel

# 本服务图片 URL 标识（image_storage_service.URL_PREFIX）
_URL_MARKER = '/api/v1/images/'


def _load_image_bytes(image_url):
    """
    按 image_url 加载原图字节
    支持两种来源：
    - 本服务图片地址：/api/v1/images/<filename>（允许带域名前缀）
    - data URI：data:image/xxx;base64,...
    """
    if not isinstance(image_url, str) or not image_url.strip():
        raise ValueError('图片地址不能为空')
    url = image_url.strip()

    if url.startswith('data:image/'):
        # data URI → 解码 base64
        _, _, b64_data = url.partition(',')
        if not b64_data:
            raise ValueError('data URI 缺少 base64 数据')
        try:
            image_bytes = base64.b64decode(b64_data)
        except Exception as e:
            raise ValueError(f'base64 解码失败: {e}')
        if not image_bytes:
            raise ValueError('解码后的图片数据为空')
        return image_bytes

    # 本服务图片：截取 /api/v1/images/ 之后的部分（兼容带域名前缀的完整 URL）
    idx = url.find(_URL_MARKER)
    if idx < 0:
        raise ValueError('仅支持本服务图片地址或 data URI')
    filename = url[idx + len(_URL_MARKER):]
    # 文件名安全检查：存储目录为扁平结构，禁止路径分隔符与目录穿越
    if not filename or '..' in filename or '/' in filename or '\\' in filename:
        raise ValueError('无效的图片地址')
    file_path = get_image_path(filename)
    if not os.path.isfile(file_path):
        raise ValueError('来源图片不存在或已被清理')
    with open(file_path, 'rb') as f:
        return f.read()


def _update_task_record(task_id, status, result_url=None, error=None):
    """尽力回写 editor_task 记录（持久化结果；Redis 状态过期后仍可从 DB 查到）"""
    try:
        EditorTaskModel().update_result(task_id, status, result_url=result_url, error=error)
    except Exception as db_err:
        print(f'[编辑器] 任务记录回写失败: task_id={task_id}, error={db_err}', flush=True)


@register_task('editor_tool_execute')
async def editor_tool_execute(ctx, payload: dict, task_id: str):
    """
    通用编辑器工具执行任务

    payload: {tool: str, image_url: str, params: dict, user_id: int}
    成功 result: {image_url, width, height, tool}
    """
    tool_name = payload.get('tool') or ''
    image_url = payload.get('image_url') or ''
    params = payload.get('params') if isinstance(payload.get('params'), dict) else {}
    user_id = payload.get('user_id')
    try:
        tool = get_tool(tool_name)
        if tool is None:
            raise ValueError(f'未知工具: {tool_name}')

        # 1. 加载原图字节
        await set_progress(ctx, task_id, '加载图片', pct=5)
        image_bytes = _load_image_bytes(image_url)

        # 2. 执行工具纯函数并编码为 PNG（保留透明通道）
        # AI 工具（module='ai'）耗时较长（调生图通道约 10-30 秒），步骤文案区分提示
        process_text = ('AI 处理中（约 10-30 秒）'
                        if tool.get('module') == 'ai' else '处理中')
        await set_progress(ctx, task_id, process_text, pct=40)
        try:
            img = Image.open(io.BytesIO(image_bytes))
        except Exception:
            raise ValueError('无法识别的图片文件')
        with img:
            # AI 工具（module='ai'）额外透传 user_id 供 BYOK 通道解析；基础工具保持原 (image, params) 协议
            if tool.get('module') == 'ai':
                result_img = tool['func'](img, params, user_id=user_id)
            else:
                result_img = tool['func'](img, params)
            buf = io.BytesIO()
            result_img.save(buf, format='PNG')
        result_bytes = buf.getvalue()
        out_width, out_height = result_img.width, result_img.height

        # 3. 保存结果图（复用图片存储服务）
        result_url = save_image_bytes(result_bytes, user_id, 'png', prefix='editor')

        await complete_task(ctx, task_id, {
            'image_url': result_url,
            'width': out_width,
            'height': out_height,
            'tool': tool_name,
        })
        _update_task_record(task_id, 'completed', result_url=result_url)
    except Exception as e:
        await fail_task(ctx, task_id, str(e) or '未知错误')
        _update_task_record(task_id, 'failed', error=str(e) or '未知错误')
