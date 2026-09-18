-- P1-3 图组预设（tiktok_showcase）：batch_task_item 增加逐项尺寸列
-- 由 app.py _run_migrations 启动时自动执行（基于 _migrations 表按文件名去重）
-- 注意：请勿把该列合并进已应用的旧迁移文件（旧文件不会重跑，会导致存量库缺列）
-- 图组模式下每商品 3 图的逐项尺寸：
--   main   1024x1024（1:1 白底主图）
--   scene  1024x1024（1:1 模特/场景图）
--   detail 1024x1820（9:16 竖版详情图）
-- 非图组模式该列为 NULL，生成分辨率回退批次级 size。

ALTER TABLE batch_task_item
    ADD COLUMN size VARCHAR(16) NULL COMMENT '该子任务生成分辨率（图组模式逐项尺寸，如 1024x1820；NULL 回退批次级 size）' AFTER image_type;
