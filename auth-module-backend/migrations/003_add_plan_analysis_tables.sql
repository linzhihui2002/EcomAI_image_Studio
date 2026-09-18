-- 003: 生图计划分析数据表
-- 创建 plan_analysis_tasks 和 plan_analysis_files 表

CREATE TABLE IF NOT EXISTS plan_analysis_tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT 'pending/processing/completed/failed',
    input_hash VARCHAR(64) NOT NULL DEFAULT '' COMMENT '请求内容哈希（用于缓存）',
    result_json TEXT NULL COMMENT '分析结果 JSON',
    error_message TEXT NULL COMMENT '错误信息',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_input_hash (input_hash),
    INDEX idx_status (status),
    INDEX idx_user_created (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS plan_analysis_files (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_id INT NOT NULL,
    file_name VARCHAR(255) NOT NULL COMMENT '文件名',
    file_size BIGINT NOT NULL DEFAULT 0 COMMENT '文件大小（字节）',
    file_type VARCHAR(50) NOT NULL DEFAULT '' COMMENT '文件类型/扩展名',
    storage_path VARCHAR(500) NOT NULL DEFAULT '' COMMENT '存储路径',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_task_id (task_id),
    CONSTRAINT fk_plan_files_task FOREIGN KEY (task_id) REFERENCES plan_analysis_tasks(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;