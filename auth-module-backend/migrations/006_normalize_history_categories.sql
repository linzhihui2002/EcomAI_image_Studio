-- 006: 归一化 history_records.category 字段
--
-- 问题: 部分历史记录的 category 字段值为非标准值（如中文标签 'AI商品图'、
--   简写 'product_image' 等），导致前端按 category 筛选时无法匹配。
--   标准值应为 'ai_product_image' 或 'ai_toolbox'。
--
-- 执行前建议先运行诊断脚本确认实际数据:
--   python scripts/diagnose_history_categories.py
--
-- 执行后再次运行诊断脚本验证修复结果。

-- 1. 已知非标准值 → ai_product_image
UPDATE history_records
SET category = 'ai_product_image'
WHERE category IN (
    'AI商品图',
    'ai_product',
    'product_image',
    'smart',
    'pro',
    '简单模式',
    '专业模式',
    'AIProductImage',
    'ai-product-image'
);

-- 2. 已知非标准值 → ai_toolbox
UPDATE history_records
SET category = 'ai_toolbox'
WHERE category IN (
    'AI工具箱',
    'toolbox',
    'ai_tool',
    '工具箱',
    'AIToolbox',
    'ai-toolbox'
);

-- 3. 根据 sub_category 兜底推断（处理 NULL / 空字符串 / 其他未知值）
--    AI商品图的子类目
UPDATE history_records
SET category = 'ai_product_image'
WHERE category NOT IN ('ai_product_image', 'ai_toolbox')
  AND sub_category IN ('smart_mode', 'pro_mode');

--    AI工具箱的子类目
UPDATE history_records
SET category = 'ai_toolbox'
WHERE category NOT IN ('ai_product_image', 'ai_toolbox')
  AND sub_category IN (
      'plan_analysis', 'image_merge', 'text_to_image', 'chat_gen',
      'product_replace', 'ai_model', 'model_product', 'prompt_reverse'
  );

-- 4. 验证: 修复后应只剩两个标准值
SELECT category, COUNT(*) AS cnt
FROM history_records
GROUP BY category
ORDER BY cnt DESC;
