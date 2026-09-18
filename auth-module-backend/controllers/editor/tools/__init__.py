"""
编辑器工具包
- imaging.py: PIL 纯函数（PIL Image → PIL Image，bytes 编解码由 tasks.py 负责）
- registry.py: 工具注册表（前端工具栏与后续 Agent 的单一数据来源）
- tasks.py: 通用工具执行异步任务（ARQ worker 消费）
"""
