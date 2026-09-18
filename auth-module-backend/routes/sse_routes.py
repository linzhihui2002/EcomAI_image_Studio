"""
SSE 任务进度推送路由
EventSource 无法自定义请求 Header，鉴权 token 通过 ?token= query 参数传递
（Cookie 兜底）。订阅 Redis task-events:{task_id} 频道实时推送任务进度。
"""
import json
import time

from flask import Blueprint, Response, jsonify, request

from utils.security import verify_token

sse_bp = Blueprint('sse', __name__, url_prefix='/api/v1/sse')

# 心跳间隔（秒）：防止代理/浏览器因空闲断开连接
HEARTBEAT_INTERVAL = 15

# Cookie 兜底 token 名称（与前端存储 key 命名保持一致）
_TOKEN_COOKIE = 'ecomai_token'


def _sse_event(event: str, data: dict) -> str:
    """格式化一条 SSE 消息"""
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


@sse_bp.route('/tasks/<task_id>', methods=['GET'])
def stream_task(task_id):
    """
    订阅任务进度事件流
    event 类型：progress（中间状态）/ completed（终态）/ failed（终态），
    推送终态后服务端主动关流；每 15 秒发送一次注释心跳（: ping）
    """
    # 鉴权：优先 query 参数，其次 Cookie 兜底
    token = request.args.get('token') or request.cookies.get(_TOKEN_COOKIE)
    if not token or verify_token(token) is None:
        return jsonify({
            'code': 1002,
            'message': 'Token无效或已过期，请重新登录',
            'data': None
        }), 401

    # 连接建立前的状态不丢失：先读一次当前状态立即下发
    from services.task_queue import get_task, get_sync_redis, event_channel
    initial = get_task(task_id)
    if initial is None:
        return jsonify({
            'code': 5001,
            'message': '任务不存在或已过期',
            'data': None
        }), 404

    pubsub = get_sync_redis().pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(event_channel(task_id))

    def generate():
        try:
            if initial.get('status') in ('completed', 'failed'):
                # 订阅前已是终态：直接下发终态并关流
                yield _sse_event(initial['status'], initial)
                return
            yield _sse_event('progress', initial)

            last_beat = time.time()
            while True:
                message = pubsub.get_message(timeout=1.0)
                if message:
                    try:
                        state = json.loads(message['data'])
                    except (TypeError, ValueError):
                        continue
                    status = state.get('status')
                    if status in ('completed', 'failed'):
                        yield _sse_event(status, state)
                        return
                    yield _sse_event('progress', state)
                    last_beat = time.time()
                elif time.time() - last_beat >= HEARTBEAT_INTERVAL:
                    # SSE 注释行心跳，不触发客户端 message 事件
                    yield ': ping\n\n'
                    last_beat = time.time()
        finally:
            try:
                pubsub.close()
            except Exception:
                pass

    response = Response(generate(), mimetype='text/event-stream')
    # flask-compress 默认只压缩 text/html 等常见 MIME，text/event-stream 不在压缩列表内，
    # 因此流式响应不会被压缩/缓冲；不设置 direct_passthrough，让 Flask 正常将 str 编码为 bytes
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response
