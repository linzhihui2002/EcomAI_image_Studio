-- ============================================
-- Migration 011: 兑换码功能扩展 - 新增总使用次数和单账号次数限制
-- ============================================

-- 1. 给 redemption_codes 表新增字段
ALTER TABLE redemption_codes
    ADD COLUMN max_uses INT NOT NULL DEFAULT 1 COMMENT '总使用次数上限',
    ADD COLUMN max_uses_per_user INT NOT NULL DEFAULT 1 COMMENT '单账号使用次数上限',
    ADD COLUMN use_count INT NOT NULL DEFAULT 0 COMMENT '当前已使用次数',
    ADD INDEX idx_use_count (use_count);

-- 2. 同步更新现有数据的 is_used 字段（确保 use_count 与 is_used 一致）
UPDATE redemption_codes SET use_count = 1 WHERE is_used = 1;

-- 3. 创建兑换码使用记录明细表
CREATE TABLE IF NOT EXISTS redemption_code_usages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    redemption_code_id INT NOT NULL COMMENT '关联兑换码ID',
    user_id INT NOT NULL COMMENT '使用用户ID',
    used_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '使用时间',
    wallet_type VARCHAR(20) NOT NULL COMMENT '钱包类型: personal / team',
    team_id INT NULL COMMENT '团队ID（team 钱包时）',
    coins_awarded INT NOT NULL COMMENT '实际发放灵感币数',
    FOREIGN KEY (redemption_code_id) REFERENCES redemption_codes(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE KEY uk_code_user_time (redemption_code_id, user_id, used_at),
    INDEX idx_redemption_code (redemption_code_id),
    INDEX idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;