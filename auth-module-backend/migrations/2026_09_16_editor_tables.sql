-- 2026_09_16: 编辑器模块数据表
-- editor_document: 编辑器图层文档（自动保存，layers 为 JSON 图层数组）
-- editor_task: 编辑器工具异步任务记录（归属校验 + Redis 状态过期后的降级轮询）

CREATE TABLE IF NOT EXISTS editor_document (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL COMMENT '所属用户ID',
    source_image_id VARCHAR(64) NULL COMMENT '来源图片标识（/api/v1/images/ 文件名）',
    title VARCHAR(255) DEFAULT '' COMMENT '文档标题',
    layers JSON NULL COMMENT '图层数据（结构见 controllers/editor/layers.py）',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS editor_task (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL COMMENT '任务ID（task_queue 生成的 uuid hex）',
    user_id BIGINT NOT NULL COMMENT '所属用户ID',
    tool VARCHAR(64) NULL COMMENT '工具名称（registry 中的 name）',
    params JSON NULL COMMENT '工具参数',
    status VARCHAR(16) DEFAULT 'queued' COMMENT '状态: queued | running | completed | failed',
    result_url VARCHAR(512) NULL COMMENT '结果图 URL（完成后回写）',
    error VARCHAR(1024) NULL COMMENT '失败原因',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY uk_task_id (task_id),
    INDEX idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
