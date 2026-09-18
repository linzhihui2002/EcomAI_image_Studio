-- ============================================
-- 转账审计日志模块 - 新增表
-- ============================================

-- 12. 转账审计日志表
CREATE TABLE IF NOT EXISTS transfer_audit_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    transfer_type ENUM('team_to_owner', 'personal_to_team') NOT NULL COMMENT '转账类型',
    from_user_id INT NOT NULL COMMENT '转账发起人',
    from_wallet ENUM('personal', 'team') NOT NULL COMMENT '转出钱包类型',
    team_id INT NULL COMMENT '关联团队ID',
    to_user_id INT NULL COMMENT '接收方用户ID（team_to_owner场景）',
    to_wallet ENUM('personal', 'team') NOT NULL COMMENT '转入钱包类型',
    amount INT NOT NULL COMMENT '转账金额',
    status ENUM('success', 'failed') NOT NULL DEFAULT 'success' COMMENT '转账状态',
    error_msg VARCHAR(500) NULL COMMENT '失败原因',
    ip_address VARCHAR(45) NULL COMMENT '操作IP地址',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (from_user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE SET NULL,
    INDEX idx_team_id (team_id),
    INDEX idx_from_user (from_user_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;