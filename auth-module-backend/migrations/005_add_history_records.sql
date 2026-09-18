-- 005: 新增历史记录表
CREATE TABLE IF NOT EXISTS history_records (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL COMMENT '所属用户ID',
    category VARCHAR(50) NOT NULL COMMENT '一级类目: ai_product_image | ai_toolbox',
    sub_category VARCHAR(50) NOT NULL COMMENT '二级类目标识符',
    title VARCHAR(255) NOT NULL COMMENT '记录标题（用于列表展示）',
    thumbnail_url VARCHAR(500) NULL COMMENT '缩略图URL（列表展示用）',
    input_data JSON NOT NULL COMMENT '输入数据（图片、提示词、配置等）',
    output_data JSON NOT NULL COMMENT '输出数据（生成的图片、分析结果等）',
    config_snapshot JSON NULL COMMENT '配置快照（用于"再次生成"功能）',
    shared_to_team TINYINT(1) DEFAULT 0 COMMENT '是否已分享到团队',
    shared_team_id INT NULL COMMENT '分享到的团队ID',
    shared_at DATETIME NULL COMMENT '分享时间',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_category (user_id, category),
    INDEX idx_user_sub_category (user_id, sub_category),
    INDEX idx_user_created (user_id, created_at DESC),
    INDEX idx_shared_team (shared_team_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;