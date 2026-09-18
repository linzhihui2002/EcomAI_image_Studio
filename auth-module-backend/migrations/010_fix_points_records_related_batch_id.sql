-- 010: 修复 points_records.related_batch_id 列类型
-- 原定义为 INT，但应用层传入字符串型 batch_id/task_id（如 "batch-a1b2c3d4"），
-- 在 MySQL 严格模式下导致 "Incorrect integer value" 错误，扣费/退款全部失败。
-- 改为 VARCHAR(64) 以匹配实际使用的数据类型。
ALTER TABLE points_records
    MODIFY COLUMN related_batch_id VARCHAR(64) NULL COMMENT '关联批次/任务ID（字符串）';
