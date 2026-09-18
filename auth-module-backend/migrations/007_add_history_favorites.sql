-- 007: 扩展 favorites 表以支持收藏历史记录
-- 在原有图片收藏基础上，新增 target_type 区分收藏类型（image/history），
-- 新增 history_record_id 关联 history_records 表，
-- 新增 source_user_id 记录团队分享历史记录的原始所有者（便于展示来源）。
-- 同时调整唯一键：由 (user_id, image_url) 改为 (user_id, history_record_id)，
-- 由于 MySQL 中多个 NULL 值在唯一键中不冲突，image 类型收藏（history_record_id 为 NULL）不受影响。

-- 1. 新增三列
ALTER TABLE favorites
    ADD COLUMN target_type ENUM('image','history') NOT NULL DEFAULT 'image' AFTER user_id,
    ADD COLUMN history_record_id INT NULL AFTER batch_id,
    ADD COLUMN source_user_id INT NULL COMMENT 'For team-shared history favorites: original owner user_id' AFTER history_record_id;

-- 2. 删除原唯一键
ALTER TABLE favorites DROP INDEX unique_user_image;

-- 3. 新增唯一键（user_id + history_record_id）
ALTER TABLE favorites ADD UNIQUE KEY unique_user_history (user_id, history_record_id);

-- 4. 添加索引（按 history_record_id 查询用）
ALTER TABLE favorites ADD INDEX idx_history_record (history_record_id);

-- 5. 添加外键约束（history_record_id 引用 history_records(id)，级联删除）
ALTER TABLE favorites
    ADD CONSTRAINT fk_fav_history
    FOREIGN KEY (history_record_id) REFERENCES history_records(id) ON DELETE CASCADE;
