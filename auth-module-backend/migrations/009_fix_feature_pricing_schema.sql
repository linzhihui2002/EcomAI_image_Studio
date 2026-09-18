-- 009: 修复 feature_pricing 表结构（旧表缺少 display_name, category, config 列）
-- 先备份旧数据（如果有的话），再重建表，最后从备份恢复数据
DROP TABLE IF EXISTS feature_pricing_old;
CREATE TABLE IF NOT EXISTS feature_pricing_old LIKE feature_pricing;
INSERT IGNORE INTO feature_pricing_old SELECT * FROM feature_pricing;
DROP TABLE IF EXISTS feature_pricing;
CREATE TABLE feature_pricing (
    id INT AUTO_INCREMENT PRIMARY KEY,
    feature_key VARCHAR(100) NOT NULL COMMENT '功能唯一标识',
    display_name VARCHAR(100) NOT NULL COMMENT '展示名称',
    category VARCHAR(50) NOT NULL COMMENT '分类: ai_product_image | ai_toolbox',
    pricing_type VARCHAR(30) NOT NULL COMMENT '计价方式: per_image_resolution | per_use',
    config JSON NOT NULL COMMENT '定价配置 JSON',
    description VARCHAR(255) NULL COMMENT '备注说明',
    is_active TINYINT(1) DEFAULT 1 COMMENT '启用状态',
    sort_order INT DEFAULT 0 COMMENT '排序',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE INDEX idx_feature_key (feature_key),
    INDEX idx_category_active (category, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
-- 从备份表恢复数据到新表
INSERT INTO feature_pricing (feature_key, display_name, category, pricing_type, config, description, is_active, sort_order, created_at, updated_at)
SELECT feature_key, display_name, category, pricing_type, config, description, is_active, sort_order, created_at, updated_at
FROM feature_pricing_old
ON DUPLICATE KEY UPDATE
    display_name = VALUES(display_name),
    category = VALUES(category),
    pricing_type = VALUES(pricing_type),
    config = VALUES(config),
    description = VALUES(description),
    is_active = VALUES(is_active),
    sort_order = VALUES(sort_order)