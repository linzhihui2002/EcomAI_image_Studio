-- 012: 创建 favorites 表（完整 schema，合并 init_db.sql 原始定义 + 007 迁移新增字段）
-- 背景：服务器部署时未运行 init_db.sql，导致 favorites 表缺失。
-- 007_add_history_favorites.sql 假设表已存在（执行 ALTER TABLE），因此也失败了。
-- 本迁移直接创建包含所有字段的完整表，并标记 007 为已执行。

CREATE TABLE IF NOT EXISTS favorites (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    target_type ENUM('image','history') NOT NULL DEFAULT 'image' COMMENT '收藏类型: image=单张图片, history=整条历史记录',
    image_url VARCHAR(500) NOT NULL COMMENT '图片URL（image 类型必填；history 类型存缩略图URL）',
    batch_id INT NULL,
    history_record_id INT NULL COMMENT '关联的历史记录ID（仅 history 类型使用）',
    source_user_id INT NULL COMMENT '团队分享历史记录的原始所有者 user_id（仅 history 类型使用）',
    config JSON NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_user_history (user_id, history_record_id),
    INDEX idx_history_record (history_record_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_fav_history FOREIGN KEY (history_record_id) REFERENCES history_records(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 标记 007 迁移为已执行（其 schema 变更已包含在上方 CREATE TABLE 中）
INSERT IGNORE INTO _migrations (filename) VALUES ('007_add_history_favorites.sql');