-- ============================================
-- EcomAI Auth 模块 - MySQL 初始化脚本
-- ============================================

CREATE DATABASE IF NOT EXISTS ecomai_auth
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE ecomai_auth;

-- 创建 users 表
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('admin', 'user') DEFAULT 'user' NOT NULL,
    personal_points INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 插入开发测试账号（密码以 bcrypt 哈希存储，本文件不记录明文）
-- 安全提示：这两个账号仅供本地开发与自动化测试使用，
-- 对外部署前必须修改密码或删除，详见 docs/SECURITY.md
INSERT INTO users (email, password_hash, role) VALUES
    ('admin@ecomai.local', '$2b$12$lP2Z4qVlhGbYbcLdAszFv.SL6kLNA96p0PulKcDxc9XGziSyF1GpC', 'admin');

INSERT INTO users (email, password_hash, role) VALUES
    ('user@ecomai.local', '$2b$12$85CIqQJEjiVJdiHC7Ofpm.DThBnRu0SJuqgCznL6dpBmZ8APIIgPm', 'user');

-- 创建 verification_codes 表（验证码存储）
CREATE TABLE IF NOT EXISTS verification_codes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    code VARCHAR(6) NOT NULL,
    purpose ENUM('login', 'register', 'reset_password') NOT NULL DEFAULT 'register',
    expires_at DATETIME NOT NULL,
    used TINYINT(1) NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_email_purpose (email, purpose),
    INDEX idx_expires_at (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 用户资产模块 - 新增表
-- ============================================

-- 1. 用户收藏表（定义已移至 history_records 表之后，因其外键引用 history_records）
-- 2. 积分流水记录表
CREATE TABLE IF NOT EXISTS points_records (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    amount INT NOT NULL,
    type ENUM('consume','refund','bonus','topup') NOT NULL,
    source_wallet ENUM('personal','team') NOT NULL,
    team_id INT NULL,
    related_batch_id VARCHAR(64) NULL COMMENT '关联批次/任务ID（字符串）',
    description VARCHAR(255) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_type (type),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. 定价方案表
CREATE TABLE IF NOT EXISTS pricing_plans (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    price DECIMAL(10,2) NOT NULL CHECK (price > 0),
    coins INT NOT NULL CHECK (coins > 0),
    bonus_coins INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    sort_order INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6. 兑换码表
CREATE TABLE IF NOT EXISTS redemption_codes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,
    coins INT NOT NULL CHECK (coins > 0),
    expires_at DATETIME NOT NULL,
    is_used BOOLEAN DEFAULT FALSE,
    used_by INT NULL,
    used_at DATETIME NULL,
    max_uses INT NOT NULL DEFAULT 1 COMMENT '总使用次数上限',
    max_uses_per_user INT NOT NULL DEFAULT 1 COMMENT '单账号使用次数上限',
    use_count INT NOT NULL DEFAULT 0 COMMENT '当前已使用次数',
    remark VARCHAR(255) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (used_by) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_code (code),
    INDEX idx_use_count (use_count)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6a. 兑换码使用记录明细表
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

-- ============================================
-- 初始数据：定价方案
-- ============================================
INSERT INTO pricing_plans (name, price, coins, bonus_coins, is_active, sort_order) VALUES
    ('体验包', 29.90, 100, 10, TRUE, 1),
    ('入门包', 99.00, 500, 80, TRUE, 2),
    ('进阶包', 199.00, 1200, 250, TRUE, 3),
    ('专业包', 499.00, 3500, 800, TRUE, 4),
    ('企业包', 999.00, 8000, 2000, FALSE, 5);

-- ============================================
-- 初始数据：示例兑换码
-- ============================================
INSERT INTO redemption_codes (code, coins, expires_at, is_used, remark) VALUES
    ('WELCOME2026', 100, '2026-12-31 23:59:59', FALSE, '新用户欢迎礼包'),
    ('VIPGIFT50', 500, '2026-08-31 23:59:59', FALSE, 'VIP 用户专属'),
    ('BETA88', 88, '2026-07-31 23:59:59', FALSE, '内测用户回馈');

-- ============================================
-- 管理后台模块 - 新增表
-- ============================================

-- 7. 团队表（如不存在）
CREATE TABLE IF NOT EXISTS teams (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    owner_id INT NOT NULL,
    member_count INT DEFAULT 1,
    pool_balance INT DEFAULT 0,
    invite_code VARCHAR(20) UNIQUE NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE INDEX idx_team_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 7a. 团队成员表
CREATE TABLE IF NOT EXISTS team_members (
    id INT AUTO_INCREMENT PRIMARY KEY,
    team_id INT NOT NULL,
    user_id INT NOT NULL,
    role ENUM('owner', 'admin', 'member') DEFAULT 'member',
    joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE KEY unique_team_user (team_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 8. API 请求日志表（用于仪表盘统计）
CREATE TABLE IF NOT EXISTS api_request_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    model_name VARCHAR(20) NOT NULL COMMENT 'qwen / gpt',
    status ENUM('success','failed') NOT NULL,
    latency_ms INT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_model_name (model_name),
    INDEX idx_created_at (created_at),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 9. 公告表
CREATE TABLE IF NOT EXISTS announcements (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    type ENUM('info','warning','success','important') DEFAULT 'info',
    is_pinned BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_by VARCHAR(255) NULL,
    expires_at DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_is_active (is_active),
    INDEX idx_is_pinned (is_pinned),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 初始数据：示例团队
-- ============================================
INSERT INTO teams (name, category, owner_id, member_count, pool_balance, invite_code) VALUES
    ('星辰出海工作室', '服装/鞋包', 2, 5, 50000, 'A1B2C3'),
    ('环球优选', '家居园艺', 2, 3, 25000, 'D4E5F6'),
    ('3C出海联盟', '3C电子', 2, 8, 80000, 'G7H8I9'),
    ('美妆跨境', '美妆个护', 2, 4, 35000, 'J1K2L3'),
    ('运动优选', '运动户外', 2, 6, 45000, 'M4N5O6');

-- ============================================
-- 初始数据：示例团队成员（为 seed 数据中的团队建立 member 关联）
-- ============================================
INSERT INTO team_members (team_id, user_id, role) VALUES
    (1, 2, 'owner'),
    (2, 2, 'owner'),
    (3, 2, 'owner'),
    (4, 2, 'owner'),
    (5, 2, 'owner');

-- ============================================
-- 初始数据：示例公告
-- ============================================
INSERT INTO announcements (title, content, type, is_pinned, is_active, created_by, expires_at) VALUES
    ('⚠️ 系统维护通知', '为提升服务质量，系统将于 2026年6月2日 凌晨 2:00 - 4:00 进行例行维护，届时服务将暂时不可用。请提前安排好您的使用时间，给您带来的不便敬请谅解。', 'warning', TRUE, TRUE, 'admin@ecomai.com', '2026-06-02 04:00:00'),
    ('💰 充值优惠活动进行中', '即日起至6月底，充值任意套餐即享额外 20% 灵感币赠送！企业包用户还可获得专属客服支持。活动详情请查看充值页面或联系客服咨询。', 'info', FALSE, TRUE, 'admin@ecomai.com', '2026-06-30 23:59:59'),
    ('📢 用户协议更新通知', '平台用户协议和服务条款已更新，主要变更包括：新增数据安全条款、优化退款政策说明、明确知识产权归属。请您在使用前仔细阅读最新版本的用户协议。', 'important', FALSE, TRUE, 'admin@ecomai.com', NULL);

-- ============================================
-- 初始数据：示例 API 请求日志（用于仪表盘展示）
-- ============================================
-- 插入近24小时的模拟日志数据
INSERT INTO api_request_logs (model_name, status, latency_ms, created_at) VALUES
    ('qwen', 'success', 310, DATE_SUB(NOW(), INTERVAL 23 HOUR)),
    ('qwen', 'success', 280, DATE_SUB(NOW(), INTERVAL 23 HOUR)),
    ('qwen', 'success', 350, DATE_SUB(NOW(), INTERVAL 23 HOUR)),
    ('qwen', 'failed', 1200, DATE_SUB(NOW(), INTERVAL 23 HOUR)),
    ('gpt', 'success', 430, DATE_SUB(NOW(), INTERVAL 23 HOUR)),
    ('gpt', 'success', 460, DATE_SUB(NOW(), INTERVAL 23 HOUR)),
    ('qwen', 'success', 290, DATE_SUB(NOW(), INTERVAL 22 HOUR)),
    ('qwen', 'success', 330, DATE_SUB(NOW(), INTERVAL 22 HOUR)),
    ('qwen', 'success', 310, DATE_SUB(NOW(), INTERVAL 22 HOUR)),
    ('gpt', 'success', 450, DATE_SUB(NOW(), INTERVAL 22 HOUR)),
    ('gpt', 'failed', 800, DATE_SUB(NOW(), INTERVAL 22 HOUR)),
    ('gpt', 'success', 440, DATE_SUB(NOW(), INTERVAL 22 HOUR)),
    ('qwen', 'success', 300, DATE_SUB(NOW(), INTERVAL 20 HOUR)),
    ('qwen', 'success', 340, DATE_SUB(NOW(), INTERVAL 20 HOUR)),
    ('qwen', 'failed', 1100, DATE_SUB(NOW(), INTERVAL 20 HOUR)),
    ('gpt', 'success', 470, DATE_SUB(NOW(), INTERVAL 20 HOUR)),
    ('gpt', 'success', 420, DATE_SUB(NOW(), INTERVAL 20 HOUR)),
    ('qwen', 'success', 320, DATE_SUB(NOW(), INTERVAL 18 HOUR)),
    ('qwen', 'success', 280, DATE_SUB(NOW(), INTERVAL 18 HOUR)),
    ('qwen', 'success', 350, DATE_SUB(NOW(), INTERVAL 18 HOUR)),
    ('gpt', 'success', 460, DATE_SUB(NOW(), INTERVAL 18 HOUR)),
    ('gpt', 'success', 440, DATE_SUB(NOW(), INTERVAL 18 HOUR)),
    ('gpt', 'success', 430, DATE_SUB(NOW(), INTERVAL 18 HOUR)),
    ('qwen', 'success', 310, DATE_SUB(NOW(), INTERVAL 16 HOUR)),
    ('qwen', 'success', 370, DATE_SUB(NOW(), INTERVAL 16 HOUR)),
    ('qwen', 'failed', 900, DATE_SUB(NOW(), INTERVAL 16 HOUR)),
    ('gpt', 'success', 450, DATE_SUB(NOW(), INTERVAL 16 HOUR)),
    ('gpt', 'failed', 1100, DATE_SUB(NOW(), INTERVAL 16 HOUR)),
    ('gpt', 'success', 480, DATE_SUB(NOW(), INTERVAL 16 HOUR)),
    ('qwen', 'success', 330, DATE_SUB(NOW(), INTERVAL 14 HOUR)),
    ('qwen', 'success', 290, DATE_SUB(NOW(), INTERVAL 14 HOUR)),
    ('qwen', 'success', 340, DATE_SUB(NOW(), INTERVAL 14 HOUR)),
    ('gpt', 'success', 440, DATE_SUB(NOW(), INTERVAL 14 HOUR)),
    ('gpt', 'success', 420, DATE_SUB(NOW(), INTERVAL 14 HOUR)),
    ('qwen', 'success', 300, DATE_SUB(NOW(), INTERVAL 12 HOUR)),
    ('qwen', 'success', 350, DATE_SUB(NOW(), INTERVAL 12 HOUR)),
    ('qwen', 'failed', 1300, DATE_SUB(NOW(), INTERVAL 12 HOUR)),
    ('qwen', 'success', 310, DATE_SUB(NOW(), INTERVAL 12 HOUR)),
    ('gpt', 'success', 450, DATE_SUB(NOW(), INTERVAL 12 HOUR)),
    ('gpt', 'success', 460, DATE_SUB(NOW(), INTERVAL 12 HOUR)),
    ('gpt', 'failed', 950, DATE_SUB(NOW(), INTERVAL 12 HOUR)),
    ('qwen', 'success', 320, DATE_SUB(NOW(), INTERVAL 10 HOUR)),
    ('qwen', 'success', 280, DATE_SUB(NOW(), INTERVAL 10 HOUR)),
    ('qwen', 'success', 360, DATE_SUB(NOW(), INTERVAL 10 HOUR)),
    ('gpt', 'success', 430, DATE_SUB(NOW(), INTERVAL 10 HOUR)),
    ('gpt', 'success', 470, DATE_SUB(NOW(), INTERVAL 10 HOUR)),
    ('qwen', 'success', 310, DATE_SUB(NOW(), INTERVAL 8 HOUR)),
    ('qwen', 'success', 340, DATE_SUB(NOW(), INTERVAL 8 HOUR)),
    ('qwen', 'success', 290, DATE_SUB(NOW(), INTERVAL 8 HOUR)),
    ('qwen', 'failed', 1000, DATE_SUB(NOW(), INTERVAL 8 HOUR)),
    ('gpt', 'success', 450, DATE_SUB(NOW(), INTERVAL 8 HOUR)),
    ('gpt', 'success', 440, DATE_SUB(NOW(), INTERVAL 8 HOUR)),
    ('gpt', 'success', 460, DATE_SUB(NOW(), INTERVAL 8 HOUR)),
    ('qwen', 'success', 330, DATE_SUB(NOW(), INTERVAL 6 HOUR)),
    ('qwen', 'success', 300, DATE_SUB(NOW(), INTERVAL 6 HOUR)),
    ('gpt', 'success', 420, DATE_SUB(NOW(), INTERVAL 6 HOUR)),
    ('gpt', 'success', 450, DATE_SUB(NOW(), INTERVAL 6 HOUR)),
    ('gpt', 'failed', 850, DATE_SUB(NOW(), INTERVAL 6 HOUR)),
    ('qwen', 'success', 320, DATE_SUB(NOW(), INTERVAL 4 HOUR)),
    ('qwen', 'success', 350, DATE_SUB(NOW(), INTERVAL 4 HOUR)),
    ('qwen', 'success', 310, DATE_SUB(NOW(), INTERVAL 4 HOUR)),
    ('gpt', 'success', 440, DATE_SUB(NOW(), INTERVAL 4 HOUR)),
    ('gpt', 'success', 460, DATE_SUB(NOW(), INTERVAL 4 HOUR)),
    ('qwen', 'success', 290, DATE_SUB(NOW(), INTERVAL 2 HOUR)),
    ('qwen', 'success', 370, DATE_SUB(NOW(), INTERVAL 2 HOUR)),
    ('qwen', 'failed', 1200, DATE_SUB(NOW(), INTERVAL 2 HOUR)),
    ('gpt', 'success', 430, DATE_SUB(NOW(), INTERVAL 2 HOUR)),
    ('gpt', 'success', 450, DATE_SUB(NOW(), INTERVAL 2 HOUR)),
    ('qwen', 'success', 320, DATE_SUB(NOW(), INTERVAL 1 HOUR)),
    ('qwen', 'success', 340, DATE_SUB(NOW(), INTERVAL 1 HOUR)),
    ('qwen', 'success', 300, DATE_SUB(NOW(), INTERVAL 1 HOUR)),
    ('gpt', 'success', 440, DATE_SUB(NOW(), INTERVAL 1 HOUR)),
    ('gpt', 'success', 460, DATE_SUB(NOW(), INTERVAL 1 HOUR)),
    ('qwen', 'success', 310, NOW()),
    ('qwen', 'success', 330, NOW()),
    ('qwen', 'success', 280, NOW()),
    ('gpt', 'success', 450, NOW()),
    ('gpt', 'failed', 1000, NOW()),
    ('gpt', 'success', 440, NOW());

-- ============================================
-- 初始数据：示例流水（为新注册用户）
-- ============================================
-- 示例流水将根据实际注册用户动态插入，此处仅提供表结构

-- ============================================
-- 团队邀请码模块 - 新增表
-- ============================================

-- 10. 团队邀请码表
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

-- 11. 团队邀请码使用日志表
CREATE TABLE IF NOT EXISTS team_invitation_usage_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    invitation_id INT NOT NULL,
    used_by INT NOT NULL COMMENT '使用者用户 ID',
    used_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (invitation_id) REFERENCES team_invitations(id) ON DELETE CASCADE,
    FOREIGN KEY (used_by) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_invitation_id (invitation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 历史记录模块 - 新增表
-- ============================================

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

-- 1. 用户收藏表（支持图片收藏与历史记录收藏两种类型）
-- 注：此表必须在 history_records 之后创建，因其外键引用 history_records(id)
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

-- ============================================
-- 功能定价模块 - feature_pricing 表
-- 各功能（AI 商品图、工具箱）的灵感币计价配置
-- ============================================

CREATE TABLE IF NOT EXISTS feature_pricing (
    id INT AUTO_INCREMENT PRIMARY KEY,
    feature_key VARCHAR(100) UNIQUE NOT NULL COMMENT '功能唯一标识，如 ai_product_image.smart_mode / toolbox.plan_analysis',
    display_name VARCHAR(100) NOT NULL COMMENT '展示名称',
    category VARCHAR(50) NOT NULL COMMENT '分组: ai_product_image | ai_toolbox',
    pricing_type ENUM('per_image_resolution','per_use') NOT NULL COMMENT '计价方式',
    config JSON NOT NULL COMMENT '计价配置 JSON',
    description VARCHAR(255) NULL,
    is_active BOOLEAN DEFAULT TRUE,
    sort_order INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_category (category),
    INDEX idx_is_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 默认功能定价数据（INSERT IGNORE，可重复执行）
INSERT IGNORE INTO feature_pricing (feature_key, display_name, category, pricing_type, config, sort_order) VALUES
('ai_product_image.smart_mode', 'AI商品图-简单模式', 'ai_product_image', 'per_image_resolution', '{"tiers":[{"tier":"1K","max_dimension":1024,"coins":5},{"tier":"2K","max_dimension":2048,"coins":10},{"tier":"4K","max_dimension":4096,"coins":15}]}', 1),
('ai_product_image.pro_mode', 'AI商品图-专业模式', 'ai_product_image', 'per_image_resolution', '{"tiers":[{"tier":"1K","max_dimension":1024,"coins":5},{"tier":"2K","max_dimension":2048,"coins":10},{"tier":"4K","max_dimension":4096,"coins":15}]}', 2),
('toolbox.text_to_image', '文生图', 'ai_toolbox', 'per_use', '{"coins":5}', 3),
('toolbox.image_merge', '图片合并', 'ai_toolbox', 'per_use', '{"coins":5}', 4),
('toolbox.plan_analysis', '生图计划分析', 'ai_toolbox', 'per_use', '{"coins":5}', 5),
('toolbox.chat_gen', '对话式生图', 'ai_toolbox', 'per_use', '{"coins":5}', 6),
('toolbox.product_replace', '产品替换', 'ai_toolbox', 'per_use', '{"coins":5}', 7),
('toolbox.ai_model', 'AI模特', 'ai_toolbox', 'per_use', '{"coins":5}', 8),
('toolbox.model_product', '模特商品图', 'ai_toolbox', 'per_use', '{"coins":5}', 9),
('toolbox.prompt_reverse', '反推提示词', 'ai_toolbox', 'per_use', '{"coins":5}', 10);