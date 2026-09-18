"""商品图生成模块单元测试"""
import os
import sys
import json
import pytest
from unittest.mock import MagicMock

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- mock 缺失的依赖，避免 routes/generation.py 导入时因 langgraph 报错 ----
_mock_langgraph = MagicMock()
_mock_langgraph_graph = MagicMock()
sys.modules['langgraph'] = _mock_langgraph
sys.modules['langgraph.graph'] = _mock_langgraph_graph
sys.modules['workflows.smart_generation'] = MagicMock()

from config import AIConfig
from models.generation_task import ProductInfo, GenerationTask, ImageType, TaskStatus
from prompts.builder import PromptBuilder
from routes.generation import _is_valid_base64_image


class TestAIConfig:
    """测试 AIConfig 环境变量读取"""
    
    def test_default_values(self, monkeypatch):
        """测试默认值 - 移除所有环境变量后检查默认值"""
        env_vars = [
            'LLM_MODEL_NAME', 'LLM_API_BASE', 'LLM_API_KEY',
            'MULTIMODAL_MODEL_NAME', 'MULTIMODAL_API_BASE', 'MULTIMODAL_API_KEY',
            'IMAGE_GEN_MODEL_NAME', 'IMAGE_GEN_API_BASE', 'IMAGE_GEN_API_KEY',
            'IMAGE_GEN_MAX_RETRIES', 'IMAGE_GEN_TIMEOUT',
        ]
        for var in env_vars:
            monkeypatch.delenv(var, raising=False)
        # 重新导入触发默认值
        import importlib
        import config
        importlib.reload(config)
        from config import AIConfig as FreshAIConfig
        
        assert FreshAIConfig.LLM_MODEL_NAME == 'qwen3.6-plus'
        assert FreshAIConfig.MULTIMODAL_MODEL_NAME == 'qwen3.5-omni-plus'
        assert FreshAIConfig.IMAGE_GEN_MODEL_NAME == 'gpt-image-2'
        assert FreshAIConfig.IMAGE_GEN_MAX_RETRIES == 2
        assert FreshAIConfig.IMAGE_GEN_TIMEOUT == 120
    
    def test_env_override_string(self, monkeypatch):
        """测试字符串类型环境变量覆盖"""
        monkeypatch.setenv('LLM_MODEL_NAME', 'custom-model-v2')
        monkeypatch.setenv('LLM_API_KEY', 'sk-test-key-123')
        
        import importlib
        import config
        importlib.reload(config)
        from config import AIConfig as FreshAIConfig
        
        assert FreshAIConfig.LLM_MODEL_NAME == 'custom-model-v2'
        assert FreshAIConfig.LLM_API_KEY == 'sk-test-key-123'
    
    def test_env_override_int(self, monkeypatch):
        """测试整数类型环境变量覆盖"""
        monkeypatch.setenv('IMAGE_GEN_MAX_RETRIES', '5')
        monkeypatch.setenv('IMAGE_GEN_TIMEOUT', '180')
        
        import importlib
        import config
        importlib.reload(config)
        from config import AIConfig as FreshAIConfig
        
        assert FreshAIConfig.IMAGE_GEN_MAX_RETRIES == 5
        assert FreshAIConfig.IMAGE_GEN_TIMEOUT == 180


class TestProductInfo:
    """测试 ProductInfo 数据模型"""
    
    def test_empty_product_info(self):
        info = ProductInfo()
        assert info.product_name == ""
        assert info.is_complete() == False
    
    def test_partial_product_info(self):
        info = ProductInfo(product_name="Test Product")
        assert info.is_complete() == False
    
    def test_complete_product_info(self):
        info = ProductInfo(
            product_name="Wireless Headphones",
            target_audience="Young adults",
            selling_points="Noise cancellation/Long battery",
            usage_scenario="Commute/Office",
            product_category="Electronics/Headphones",
        )
        assert info.is_complete() == True
    
    def test_to_dict(self):
        info = ProductInfo(
            product_name="Test",
            target_audience="Everyone",
            selling_points="Great quality",
            usage_scenario="Daily use",
            product_category="General",
        )
        d = info.to_dict()
        assert d["product_name"] == "Test"
        assert d["target_audience"] == "Everyone"
        assert "product_name" in d


class TestGenerationTask:
    """测试 GenerationTask 数据模型"""
    
    def test_default_task(self):
        task = GenerationTask()
        assert task.task_id.startswith("task-")
        assert task.status == TaskStatus.PENDING
        assert task.image_type == ImageType.WHITE_BG
        assert task.slot_index == 0
    
    def test_custom_task(self):
        task = GenerationTask(
            batch_id="batch-test123",
            image_type=ImageType.SCENE,
            slot_index=2,
            slot_name="Beach Scene",
        )
        assert task.batch_id == "batch-test123"
        assert task.image_type == ImageType.SCENE
        assert task.slot_index == 2
    
    def test_to_dict(self):
        task = GenerationTask(
            batch_id="batch-abc",
            image_type=ImageType.SELLING_POINT,
            status=TaskStatus.SUCCESS,
            prompt_used="test prompt",
            image_url="https://example.com/img.png",
        )
        d = task.to_dict()
        assert d["batch_id"] == "batch-abc"
        assert d["image_type"] == "selling_point"
        assert d["status"] == "success"
        assert d["prompt_used"] == "test prompt"
        assert d["image_url"] == "https://example.com/img.png"


class TestPromptBuilder:
    """测试 PromptBuilder 提示词构建"""
    
    def test_builder_init(self):
        builder = PromptBuilder()
        assert builder is not None
    
    def test_build_white_bg(self):
        builder = PromptBuilder()
        variables = {
            "product_name": "Wireless Earbuds",
            "platform": "Amazon",
            "region": "US",
            "target_language": "English",
        }
        result = builder.build(ImageType.WHITE_BG, variables)
        assert "Wireless Earbuds" in result
        assert "pure white background" in result
        assert "8K" in result
        assert "commercial grade" in result.lower()
    
    def test_build_scene(self):
        builder = PromptBuilder()
        variables = {
            "product_name": "Yoga Mat",
            "usage_scenario": "home gym and outdoor park",
            "platform": "Amazon",
            "region": "Germany",
            "target_language": "German",
        }
        result = builder.build(ImageType.SCENE, variables)
        assert "Yoga Mat" in result
        assert "home gym and outdoor park" in result
        assert "lifestyle" in result.lower()
        assert "8K" in result
    
    def test_build_selling_point(self):
        builder = PromptBuilder()
        variables = {
            "product_name": "Smart Watch",
            "selling_points": "Heart Rate/SPO2/GPS",
            "platform": "AliExpress",
            "region": "Brazil",
            "target_language": "Portuguese",
        }
        result = builder.build(ImageType.SELLING_POINT, variables)
        assert "Smart Watch" in result
        assert "Heart Rate/SPO2/GPS" in result
        assert "Portuguese" in result
        assert "promotional visual" in result.lower()
    
    def test_build_other(self):
        builder = PromptBuilder()
        variables = {
            "product_name": "Keyboard",
            "platform": "Shopee",
            "region": "Thailand",
            "target_language": "Thai",
        }
        extra = {
            "slot_name": "Size Comparison Chart",
            "slot_desc": "showing keyboard size compared to a standard A4 paper",
        }
        result = builder.build(ImageType.OTHER, variables, extra)
        assert "Size Comparison Chart" in result
        assert "showing keyboard size" in result
        assert "Keyboard" in result
    
    def test_missing_variable_placeholder_preserved(self):
        """缺失变量时保留占位符，不崩溃"""
        builder = PromptBuilder()
        variables = {"product_name": "Test Product"}
        result = builder.build(ImageType.SCENE, variables)
        assert "Test Product" in result
        # 缺失的变量不应导致崩溃
    
    def test_invalid_image_type(self):
        """无效图片类型抛出异常"""
        builder = PromptBuilder()
        with pytest.raises((ValueError, AttributeError)):
            builder.build("invalid_type", {})


class TestRouteHelpers:
    """测试路由辅助函数"""
    
    def test_valid_base64_with_prefix(self):
        assert _is_valid_base64_image("data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==")
        assert _is_valid_base64_image("data:image/jpeg;base64,/9j/4AAQSkZJRg==")
        assert _is_valid_base64_image("data:image/webp;base64,UklGRiQAAABXRUJQVlA4")
    
    def test_invalid_base64_prefix(self):
        assert _is_valid_base64_image("data:image/gif;base64,R0lGODlh") == False
        assert _is_valid_base64_image("data:image/bmp;base64,Qk1mAAAAAAAA") == False
    
    def test_raw_base64_no_prefix(self):
        """纯 base64 无前缀，长度足够则通过"""
        long_base64 = "A" * 200
        assert _is_valid_base64_image(long_base64) == True
    
    def test_short_base64(self):
        """太短的 base64 不通过"""
        assert _is_valid_base64_image("abc") == False
        assert _is_valid_base64_image("") == False


class TestDeleteOperations:
    """测试删除操作（在 Flask app context 中调用核心逻辑，绕过 @token_required 装饰器）"""

    @pytest.fixture(autouse=True)
    def _setup_app_context(self):
        """每个测试提供 Flask 应用上下文"""
        from flask import Flask
        app = Flask(__name__)
        with app.app_context():
            yield

    def setup_method(self):
        """每个测试前重置内存存储"""
        import routes.generation as gen_module
        gen_module._task_store.clear()
        gen_module._batch_store.clear()

    def _register_test_data(self, gen_module, batch_id="batch-test-del", task_count=3):
        """注册测试数据到内存存储"""
        tasks = []
        for i in range(task_count):
            task = {
                "task_id": f"task-del-{i}",
                "batch_id": batch_id,
                "image_type": "white_bg",
                "slot_index": i,
                "slot_name": "",
                "slot_desc": "",
                "status": "success",
                "prompt_used": f"test prompt {i}",
                "image_url": f"https://example.com/img{i}.png",
                "error_msg": None,
            }
            tasks.append(task)
        gen_module._register_batch(batch_id, tasks)

    def test_delete_existing_task(self):
        """删除存在的任务，验证从 _task_store 和 _batch_store 中正确移除"""
        import routes.generation as gen_module
        self._register_test_data(gen_module, batch_id="batch-del-1", task_count=3)

        assert "task-del-0" in gen_module._task_store
        assert "task-del-0" in gen_module._batch_store["batch-del-1"]

        # 使用 __wrapped__ 绕过 @token_required 装饰器，直接测试核心逻辑
        from routes.generation import delete_task
        resp = delete_task.__wrapped__("task-del-0")

        data = resp.get_json()
        assert data["code"] == 0
        assert data["data"]["task_id"] == "task-del-0"
        assert data["data"]["batch_id"] == "batch-del-1"

        # 验证任务已从 _task_store 移除
        assert "task-del-0" not in gen_module._task_store
        # 验证任务已从批次中移除，但其他任务仍在
        assert "task-del-0" not in gen_module._batch_store["batch-del-1"]
        assert "task-del-1" in gen_module._batch_store["batch-del-1"]
        assert "task-del-2" in gen_module._batch_store["batch-del-1"]

    def test_delete_nonexistent_task(self):
        """删除不存在的任务，验证返回 404"""
        from routes.generation import delete_task
        resp, status_code = delete_task.__wrapped__("task-notexist")

        data = resp.get_json()
        assert data["code"] == 4004
        assert "任务不存在" in data["message"]

    def test_delete_existing_batch(self):
        """删除存在批次，验证批次和其下所有任务都被清理"""
        import routes.generation as gen_module
        self._register_test_data(gen_module, batch_id="batch-del-b", task_count=3)

        assert "batch-del-b" in gen_module._batch_store
        assert "task-del-0" in gen_module._task_store

        from routes.generation import delete_batch
        resp = delete_batch.__wrapped__("batch-del-b")

        data = resp.get_json()
        assert data["code"] == 0
        assert data["data"]["batch_id"] == "batch-del-b"
        assert data["data"]["deleted_tasks"] == 3

        # 验证批次已删除
        assert "batch-del-b" not in gen_module._batch_store
        # 验证所有任务已删除
        assert "task-del-0" not in gen_module._task_store
        assert "task-del-1" not in gen_module._task_store
        assert "task-del-2" not in gen_module._task_store

    def test_delete_nonexistent_batch(self):
        """删除不存在的批次，验证返回 404"""
        from routes.generation import delete_batch
        resp, status_code = delete_batch.__wrapped__("batch-notexist")

        data = resp.get_json()
        assert data["code"] == 4004
        assert "批次不存在" in data["message"]

    def test_delete_task_cleans_empty_batch(self):
        """删除批次中最后一个任务后，验证空批次也被清理"""
        import routes.generation as gen_module
        self._register_test_data(gen_module, batch_id="batch-solo", task_count=1)

        assert "batch-solo" in gen_module._batch_store

        from routes.generation import delete_task
        resp = delete_task.__wrapped__("task-del-0")

        data = resp.get_json()
        assert data["code"] == 0

        # 验证空批次已被清理
        assert "batch-solo" not in gen_module._batch_store
        assert "task-del-0" not in gen_module._task_store

    def test_delete_batch_cascades_tasks(self):
        """删除批次后验证所有关联任务都被移除"""
        import routes.generation as gen_module
        self._register_test_data(gen_module, batch_id="batch-cascade", task_count=5)

        assert len(gen_module._batch_store["batch-cascade"]) == 5

        from routes.generation import delete_batch
        resp = delete_batch.__wrapped__("batch-cascade")

        data = resp.get_json()
        assert data["code"] == 0
        assert data["data"]["deleted_tasks"] == 5

        # 验证全部清理
        for i in range(5):
            assert f"task-del-{i}" not in gen_module._task_store
        assert "batch-cascade" not in gen_module._batch_store