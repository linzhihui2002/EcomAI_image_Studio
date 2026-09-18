-- ============================================
-- 迁移 001：新增团队邀请码模块
-- 创建 team_invitations 和 team_invitation_usage_logs 表
-- ============================================

USE ecomai_auth;

CREATE TABLE IF NOT EXISTS team_invitations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    team_id INT NOT NULL,
    invite_code_hash VARCHAR(64) NOT NULL COMMENT 'SHA-256 哈希，用于快速查找',
    invite_code_encrypted VARCHAR(255) NOT NULL COMMENT 'AES-256-CBC 加密的原始邀请码',
    created_by INT NOT NULL COMMENT '创建者用户 ID',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL COMMENT '过期时间',
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否有效',
    max_usage INT DEFAULT 5 COMMENT '最大使用次数',
    usage_count INT DEFAULT 0 COMMENT '已使用次数',
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_team_active (team_id, is_active),
    INDEX idx_code_hash (invite_code_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS team_invitation_usage_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    invitation_id INT NOT NULL,
    used_by INT NOT NULL COMMENT '使用者用户 ID',
    used_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (invitation_id) REFERENCES team_invitations(id) ON DELETE CASCADE,
    FOREIGN KEY (used_by) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_invitation_id (invitation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;