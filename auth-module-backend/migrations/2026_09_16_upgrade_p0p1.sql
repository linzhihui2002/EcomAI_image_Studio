-- P0+P1 升级迁移：平台合规规则表 + 批量套图编排表
-- 由 app.py _run_migrations 启动时自动执行（基于 _migrations 表去重）
--
-- ⚠️ 文件前缀说明（请勿改回 2026_09_17）：
--   migrations 按文件名升序执行，本文件负责创建 batch_task / batch_task_item 表，
--   而 2026_09_17_batch_item_size.sql 需要为 batch_task_item 增加 size 列。
--   若本文件排在它之后，全新数据库首次部署时 "size" 列会缺失，
--   批量套图落库将因 Unknown column 'size' 直接失败。
--   故前缀固定为 2026_09_16，保证建表先于增列。
--   本文件全部为 CREATE TABLE IF NOT EXISTS，可重复执行，重跑无副作用。

-- 1. 平台合规规则表（P0-2）
CREATE TABLE IF NOT EXISTS platform_compliance_rules (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    platform VARCHAR(32) NOT NULL COMMENT '平台标识（amazon/temu/shopee/tiktok_shop/aliexpress/ozon）',
    image_type VARCHAR(32) NOT NULL COMMENT '图型（main_image/scene_image/detail_image 等）',
    rules JSON COMMENT '图型级规则（背景/占比/文字限制/尺寸等）',
    global_forbidden JSON COMMENT '平台级通用禁元素列表',
    enabled TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_platform_image_type (platform, image_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='平台合规规则表 v1';

-- 2. 批量套图编排任务表（P1-1）
CREATE TABLE IF NOT EXISTS batch_task (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL COMMENT '批次任务ID（batch-uuid）',
    user_id BIGINT NOT NULL COMMENT '所属用户',
    status VARCHAR(16) NOT NULL DEFAULT 'pending' COMMENT '状态机 pending/running/completed/failed/partial',
    total_items INT NOT NULL DEFAULT 0 COMMENT '子任务总数',
    succeeded_items INT NOT NULL DEFAULT 0 COMMENT '成功子任务数',
    failed_items INT NOT NULL DEFAULT 0 COMMENT '失败子任务数',
    feature_key VARCHAR(64) COMMENT '计费功能键',
    coins_locked INT NOT NULL DEFAULT 0 COMMENT '预扣灵感币',
    platform VARCHAR(32) COMMENT '平台',
    params JSON COMMENT '批次参数快照',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_batch_task_task_id (task_id),
    KEY idx_batch_task_user (user_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='批量套图编排任务表';

-- 3. 批量套图编排子任务表（P1-1）
CREATE TABLE IF NOT EXISTS batch_task_item (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    batch_task_id BIGINT NOT NULL COMMENT '所属批次主键',
    item_key VARCHAR(128) NOT NULL COMMENT '幂等键：product_site_imagetype',
    product_id VARCHAR(64) COMMENT '商品ID',
    site VARCHAR(32) COMMENT '站点码（US/DE/JP...）',
    image_type VARCHAR(32) COMMENT '图型',
    prompt TEXT COMMENT '生成的提示词',
    status VARCHAR(16) NOT NULL DEFAULT 'planned' COMMENT '状态机 planned/running/completed/failed',
    error TEXT COMMENT '失败原因',
    result_url VARCHAR(512) COMMENT '成图地址',
    review JSON COMMENT 'AI 合规审查结果',
    coins INT NOT NULL DEFAULT 0 COMMENT '该子任务扣费',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_batch_item_key (item_key),
    KEY idx_batch_item_batch_status (batch_task_id, status),
    CONSTRAINT fk_batch_item_task FOREIGN KEY (batch_task_id) REFERENCES batch_task (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='批量套图编排子任务表';
