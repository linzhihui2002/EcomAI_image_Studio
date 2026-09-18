-- 用户自备模型服务商（BYOK）配置表 + 用户级开关表
-- 本文件仅包含幂等的 CREATE TABLE IF NOT EXISTS 语句，可被 app.py 的朴素分号拆分器安全重复执行

CREATE TABLE IF NOT EXISTS user_ai_settings (
    user_id INT NOT NULL PRIMARY KEY COMMENT '用户ID',
    use_own_provider TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否优先使用用户自备模型通道',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_user_ai_settings_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='用户自备模型通道开关';

CREATE TABLE IF NOT EXISTS user_ai_providers (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL COMMENT '所属用户',
    category VARCHAR(32) NOT NULL COMMENT '通道分类: image_gen/multimodal/llm',
    name VARCHAR(64) NOT NULL COMMENT '用户自定义备注名',
    api_base VARCHAR(255) NOT NULL COMMENT 'API 基址，如 https://api.openai.com/v1',
    api_key_cipher TEXT NOT NULL COMMENT 'AES 加密后的 API Key',
    model_name VARCHAR(128) NOT NULL COMMENT '模型名',
    priority INT NOT NULL DEFAULT 0 COMMENT '号池优先级（升序尝试）',
    is_enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用',
    last_test_ok TINYINT(1) NULL COMMENT '最近一次连通性测试结果',
    last_test_at DATETIME NULL COMMENT '最近一次测试时间',
    last_test_error VARCHAR(500) NULL COMMENT '最近一次测试失败原因',
    last_used_at DATETIME NULL COMMENT '最近一次实际调用时间',
    failure_count INT NOT NULL DEFAULT 0 COMMENT '累计调用失败次数',
    last_error VARCHAR(500) NULL COMMENT '最近一次调用失败原因',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_user_category (user_id, category, priority),
    CONSTRAINT fk_user_ai_provider_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='用户自备模型服务商配置（号池）';
