"""
商品图生成模块集成测试
"""
import os
import sys
import json
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from utils.security import rate_limiter


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """每个测试前重置限流器"""
    rate_limiter._requests.clear()


@pytest.fixture
def app(monkeypatch):
    """创建测试 Flask 应用（Mock 数据库迁移以避免依赖真实数据库）"""
    import app as app_module
    monkeypatch.setattr(app_module, '_run_migrations', lambda config, app: None)
    app = create_app(env='testing')
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    """创建测试客户端"""
    return app.test_client()


@pytest.fixture
def auth_headers():
    """获取带认证 Token 的请求头（直接生成 JWT 避免数据库依赖）"""
    from utils.security import generate_token
    token = generate_token(user_id=9999, email="test_generation@example.com", role="user")
    return {"Authorization": f"Bearer {token}"}


# ── 鉴权拦截测试 ──

class TestAuthRequired:
    """测试 generation 路由鉴权"""

    def test_analyze_product_without_token(self, client):
        resp = client.post('/api/v1/generation/analyze-product', json={
            "image_base64": "test_base64_data",
        })
        data = resp.get_json()
        assert resp.status_code == 401
        assert data["code"] == 1001

    def test_smart_generate_without_token(self, client):
        resp = client.post('/api/v1/generation/smart-generate', json={
            "product_images": ["test_base64"],
            "image_groups": [{"key": "white", "slots": [{"id": "s1"}]}],
        })
        data = resp.get_json()
        assert resp.status_code == 401
        assert data["code"] == 1001

    def test_get_task_without_token(self, client):
        resp = client.get('/api/v1/generation/tasks/task-nonexistent')
        data = resp.get_json()
        assert resp.status_code == 401
        assert data["code"] == 1001


# ── API 响应格式测试 ──

class TestApiResponseFormat:
    """测试 API 响应格式"""

    def test_analyze_product_missing_image(self, client, auth_headers):
        """缺少图片参数时返回 400"""
        resp = client.post('/api/v1/generation/analyze-product',
                          json={},
                          headers=auth_headers)
        data = resp.get_json()
        assert "code" in data
        assert "message" in data
        assert "data" in data
        assert data["code"] == 4001
        assert resp.status_code == 400

    def test_analyze_product_empty_image(self, client, auth_headers):
        """空图片参数时返回 400"""
        resp = client.post('/api/v1/generation/analyze-product',
                          json={"image_base64": ""},
                          headers=auth_headers)
        data = resp.get_json()
        assert data["code"] == 4001

    def test_analyze_product_invalid_base64(self, client, auth_headers):
        """非法 base64 格式时返回错误"""
        resp = client.post('/api/v1/generation/analyze-product',
                          json={"image_base64": "x"},
                          headers=auth_headers)
        data = resp.get_json()
        assert data["code"] == 4001
        assert "图片格式不支持" in data["message"]

    def test_smart_generate_no_images(self, client, auth_headers):
        """无商品图片时返回 400"""
        resp = client.post('/api/v1/generation/smart-generate',
                          json={
                              "product_images": [],
                              "image_groups": [{"key": "white", "slots": [{"id": "s1"}]}],
                          },
                          headers=auth_headers)
        data = resp.get_json()
        assert data["code"] == 4001
        assert "请至少上传一张商品图片" in data["message"]

    def test_smart_generate_no_image_groups(self, client, auth_headers):
        """无图片类型配置时返回 400"""
        resp = client.post('/api/v1/generation/smart-generate',
                          json={
                              "product_images": ["test_base64_data_content_here"],
                              "image_groups": [],
                          },
                          headers=auth_headers)
        data = resp.get_json()
        assert data["code"] == 4001
        assert "请至少配置一种图片类型" in data["message"]

    def test_smart_generate_all_empty_slots(self, client, auth_headers):
        """所有图片类型 slots 为空时返回 400"""
        resp = client.post('/api/v1/generation/smart-generate',
                          json={
                              "product_images": ["test_base64_data_content_here"],
                              "image_groups": [
                                  {"key": "white", "slots": []},
                                  {"key": "scene", "slots": []},
                              ],
                          },
                          headers=auth_headers)
        data = resp.get_json()
        assert data["code"] == 4001

    def test_task_not_found(self, client, auth_headers):
        """查询不存在的任务返回 404"""
        resp = client.get('/api/v1/generation/tasks/task-notexist',
                         headers=auth_headers)
        data = resp.get_json()
        assert data["code"] == 4004
        assert "任务不存在" in data["message"]

    def test_batch_not_found(self, client, auth_headers):
        """查询不存在的批次返回 404"""
        resp = client.get('/api/v1/generation/batches/batch-notexist',
                         headers=auth_headers)
        data = resp.get_json()
        assert data["code"] == 4004
        assert "批次不存在" in data["message"]


# ── 完整工作流测试（使用 mock）──

class TestSmartGenerateWorkflow:
    """测试完整生成工作流（Mock 模式）"""

    def test_smart_generate_success_flow(self, client, auth_headers, monkeypatch):
        """测试从请求到响应的完整流程（mock 掉实际 AI 调用）"""
        # Mock run_smart_generation 以跳过实际 AI 调用
        mock_result = {
            "batch_id": "batch-testmock",
            "tasks": [
                {
                    "task_id": "task-mock-1",
                    "batch_id": "batch-testmock",
                    "image_type": "white_bg",
                    "slot_index": 0,
                    "slot_name": "",
                    "slot_desc": "",
                    "status": "success",
                    "prompt_used": "test prompt for white bg",
                    "image_url": "https://example.com/generated.png",
                    "error_msg": None,
                },
            ],
            "error": None,
        }

        from routes import generation as gen_module
        monkeypatch.setattr(gen_module, 'run_smart_generation', lambda **kwargs: mock_result)

        resp = client.post('/api/v1/generation/smart-generate',
                          json={
                              "product_images": ["test_base64_image_data_long_enough_to_pass_validation_check_1234567890"],
                              "platform": "Amazon",
                              "region": "美国",
                              "target_language": "英语",
                              "size": "1024x1024",
                              "product_info": {
                                  "product_name": "Test Product",
                                  "target_audience": "Everyone",
                                  "selling_points": "Great/Amazing",
                                  "usage_scenario": "Daily use",
                                  "product_category": "Test/General",
                              },
                              "image_groups": [
                                  {
                                      "key": "white",
                                      "slots": [{"id": "s1", "name": "", "desc": ""}],
                                  },
                              ],
                          },
                          headers=auth_headers)

        data = resp.get_json()
        assert data["code"] == 0
        assert data["data"]["batch_id"] == "batch-testmock"
        assert len(data["data"]["tasks"]) == 1
        assert data["data"]["tasks"][0]["status"] == "success"

    def test_smart_generate_with_custom_other_type(self, client, auth_headers, monkeypatch):
        """测试自定义其他类型图的生成"""
        mock_result = {
            "batch_id": "batch-custom",
            "tasks": [
                {
                    "task_id": "task-custom-1",
                    "batch_id": "batch-custom",
                    "image_type": "other",
                    "slot_index": 0,
                    "slot_name": "对比图",
                    "slot_desc": "与竞品对比展示优势",
                    "status": "success",
                    "prompt_used": "对比图 for Test Product, 与竞品对比展示优势",
                    "image_url": "https://example.com/custom.png",
                    "error_msg": None,
                },
            ],
            "error": None,
        }

        from routes import generation as gen_module
        monkeypatch.setattr(gen_module, 'run_smart_generation', lambda **kwargs: mock_result)

        resp = client.post('/api/v1/generation/smart-generate',
                          json={
                              "product_images": ["test_base64_long_enough_data_12345678901234567890"],
                              "platform": "Temu",
                              "region": "英国",
                              "target_language": "英语",
                              "size": "2048x2048",
                              "image_groups": [
                                  {
                                      "key": "other",
                                      "slots": [
                                          {"id": "c1", "name": "对比图", "desc": "与竞品对比展示优势"},
                                      ],
                                  },
                              ],
                          },
                          headers=auth_headers)

        data = resp.get_json()
        assert data["code"] == 0
        assert data["data"]["tasks"][0]["image_type"] == "other"
        assert data["data"]["tasks"][0]["slot_name"] == "对比图"

    def test_get_batch_after_generation(self, client, auth_headers, monkeypatch):
        """测试生成后可查询批次状态"""
        batch_id_test = "batch-querytest"
        mock_result = {
            "batch_id": batch_id_test,
            "tasks": [
                {
                    "task_id": "task-qt-1",
                    "batch_id": batch_id_test,
                    "image_type": "white_bg",
                    "slot_index": 0,
                    "slot_name": "",
                    "slot_desc": "",
                    "status": "success",
                    "prompt_used": "test",
                    "image_url": "https://example.com/img.png",
                    "error_msg": None,
                },
            ],
            "error": None,
        }

        from routes import generation as gen_module
        monkeypatch.setattr(gen_module, 'run_smart_generation', lambda **kwargs: mock_result)

        # 先执行生成
        gen_resp = client.post('/api/v1/generation/smart-generate',
                              json={
                                  "product_images": ["test_base64_content_long_enough_12345678901234567890"],
                                  "image_groups": [{"key": "white", "slots": [{"id": "s1"}]}],
                              },
                              headers=auth_headers)
        assert gen_resp.get_json()["code"] == 0

        # 查询批次
        batch_resp = client.get(f'/api/v1/generation/batches/{batch_id_test}',
                               headers=auth_headers)
        batch_data = batch_resp.get_json()
        assert batch_data["code"] == 0
        assert batch_data["data"]["batch_id"] == batch_id_test
        assert len(batch_data["data"]["tasks"]) == 1

    def test_get_task_after_generation(self, client, auth_headers, monkeypatch):
        """测试生成后可查询单个任务状态"""
        task_id_test = "task-qt-single"
        mock_result = {
            "batch_id": "batch-single",
            "tasks": [
                {
                    "task_id": task_id_test,
                    "batch_id": "batch-single",
                    "image_type": "scene",
                    "slot_index": 0,
                    "slot_name": "",
                    "slot_desc": "",
                    "status": "success",
                    "prompt_used": "test scene prompt",
                    "image_url": "https://example.com/scene.png",
                    "error_msg": None,
                },
            ],
            "error": None,
        }

        from routes import generation as gen_module
        monkeypatch.setattr(gen_module, 'run_smart_generation', lambda **kwargs: mock_result)

        # 执行生成
        gen_resp = client.post('/api/v1/generation/smart-generate',
                              json={
                                  "product_images": ["test_base64_content_that_is_long_enough_12345678901234567890"],
                                  "image_groups": [{"key": "scene", "slots": [{"id": "s1"}]}],
                              },
                              headers=auth_headers)
        assert gen_resp.get_json()["code"] == 0

        # 查询任务
        task_resp = client.get(f'/api/v1/generation/tasks/{task_id_test}',
                              headers=auth_headers)
        task_data = task_resp.get_json()
        assert task_data["code"] == 0
        assert task_data["data"]["task_id"] == task_id_test
        assert task_data["data"]["image_type"] == "scene"


# ── 删除 API 测试 ──

class TestDeleteApi:
    """测试删除 API 端点"""

    def test_delete_task_without_token(self, client):
        """无Token时删除任务返回 401"""
        resp = client.delete('/api/v1/generation/tasks/task-123')
        data = resp.get_json()
        assert resp.status_code == 401
        assert data["code"] == 1001

    def test_delete_batch_without_token(self, client):
        """无Token时删除批次返回 401"""
        resp = client.delete('/api/v1/generation/batches/batch-123')
        data = resp.get_json()
        assert resp.status_code == 401
        assert data["code"] == 1001

    def test_delete_nonexistent_task(self, client, auth_headers):
        """删除不存在的任务返回 404"""
        resp = client.delete('/api/v1/generation/tasks/task-notexist',
                            headers=auth_headers)
        data = resp.get_json()
        assert data["code"] == 4004
        assert "任务不存在" in data["message"]

    def test_delete_nonexistent_batch(self, client, auth_headers):
        """删除不存在的批次返回 404"""
        resp = client.delete('/api/v1/generation/batches/batch-notexist',
                            headers=auth_headers)
        data = resp.get_json()
        assert data["code"] == 4004
        assert "批次不存在" in data["message"]

    def test_delete_task_full_flow(self, client, auth_headers, monkeypatch):
        """完整流程：生成 → 删除任务 → 验证任务不可查"""
        batch_id_test = "batch-delflow-task"
        task_id_test = "task-delflow-0"
        mock_result = {
            "batch_id": batch_id_test,
            "tasks": [
                {
                    "task_id": task_id_test,
                    "batch_id": batch_id_test,
                    "image_type": "white_bg",
                    "slot_index": 0,
                    "slot_name": "",
                    "slot_desc": "",
                    "status": "success",
                    "prompt_used": "test",
                    "image_url": "https://example.com/img.png",
                    "error_msg": None,
                },
            ],
            "error": None,
        }

        from routes import generation as gen_module
        monkeypatch.setattr(gen_module, 'run_smart_generation', lambda **kwargs: mock_result)

        # 先生成
        gen_resp = client.post('/api/v1/generation/smart-generate',
                              json={
                                  "product_images": ["test_base64_long_enough_data_12345678901234567890"],
                                  "image_groups": [{"key": "white", "slots": [{"id": "s1"}]}],
                              },
                              headers=auth_headers)
        assert gen_resp.get_json()["code"] == 0

        # 删除任务
        del_resp = client.delete(f'/api/v1/generation/tasks/{task_id_test}',
                                headers=auth_headers)
        del_data = del_resp.get_json()
        assert del_data["code"] == 0
        assert del_data["data"]["task_id"] == task_id_test

        # 验证任务不可查
        get_resp = client.get(f'/api/v1/generation/tasks/{task_id_test}',
                             headers=auth_headers)
        get_data = get_resp.get_json()
        assert get_data["code"] == 4004
        assert "任务不存在" in get_data["message"]

    def test_delete_batch_full_flow(self, client, auth_headers, monkeypatch):
        """完整流程：生成 → 删除批次 → 验证批次和任务都不可查"""
        batch_id_test = "batch-delflow-full"
        mock_result = {
            "batch_id": batch_id_test,
            "tasks": [
                {
                    "task_id": "task-delflow-b0",
                    "batch_id": batch_id_test,
                    "image_type": "white_bg",
                    "slot_index": 0,
                    "slot_name": "",
                    "slot_desc": "",
                    "status": "success",
                    "prompt_used": "test",
                    "image_url": "https://example.com/img.png",
                    "error_msg": None,
                },
                {
                    "task_id": "task-delflow-b1",
                    "batch_id": batch_id_test,
                    "image_type": "scene",
                    "slot_index": 0,
                    "slot_name": "",
                    "slot_desc": "",
                    "status": "success",
                    "prompt_used": "test scene",
                    "image_url": "https://example.com/scene.png",
                    "error_msg": None,
                },
            ],
            "error": None,
        }

        from routes import generation as gen_module
        monkeypatch.setattr(gen_module, 'run_smart_generation', lambda **kwargs: mock_result)

        # 先生成
        gen_resp = client.post('/api/v1/generation/smart-generate',
                              json={
                                  "product_images": ["test_base64_long_enough_12345678901234567890"],
                                  "image_groups": [
                                      {"key": "white", "slots": [{"id": "s1"}]},
                                      {"key": "scene", "slots": [{"id": "s2"}]},
                                  ],
                              },
                              headers=auth_headers)
        assert gen_resp.get_json()["code"] == 0

        # 删除批次
        del_resp = client.delete(f'/api/v1/generation/batches/{batch_id_test}',
                                headers=auth_headers)
        del_data = del_resp.get_json()
        assert del_data["code"] == 0
        assert del_data["data"]["batch_id"] == batch_id_test
        assert del_data["data"]["deleted_tasks"] == 2

        # 验证批次不可查
        get_batch = client.get(f'/api/v1/generation/batches/{batch_id_test}',
                              headers=auth_headers)
        assert get_batch.get_json()["code"] == 4004

        # 验证任务不可查
        get_task = client.get('/api/v1/generation/tasks/task-delflow-b0',
                             headers=auth_headers)
        assert get_task.get_json()["code"] == 4004

    def test_delete_task_then_remaining_tasks_intact(self, client, auth_headers, monkeypatch):
        """删除批次中一个任务后，验证同批次其他任务仍可查"""
        batch_id_test = "batch-delflow-partial"
        mock_result = {
            "batch_id": batch_id_test,
            "tasks": [
                {
                    "task_id": "task-keep-0",
                    "batch_id": batch_id_test,
                    "image_type": "white_bg",
                    "slot_index": 0,
                    "slot_name": "",
                    "slot_desc": "",
                    "status": "success",
                    "prompt_used": "keep",
                    "image_url": "https://example.com/keep.png",
                    "error_msg": None,
                },
                {
                    "task_id": "task-keep-1",
                    "batch_id": batch_id_test,
                    "image_type": "scene",
                    "slot_index": 0,
                    "slot_name": "",
                    "slot_desc": "",
                    "status": "success",
                    "prompt_used": "keep scene",
                    "image_url": "https://example.com/scene.png",
                    "error_msg": None,
                },
            ],
            "error": None,
        }

        from routes import generation as gen_module
        monkeypatch.setattr(gen_module, 'run_smart_generation', lambda **kwargs: mock_result)

        # 先生成
        gen_resp = client.post('/api/v1/generation/smart-generate',
                              json={
                                  "product_images": ["test_base64_long_enough_data_here_12345678901234567890"],
                                  "image_groups": [
                                      {"key": "white", "slots": [{"id": "s1"}]},
                                      {"key": "scene", "slots": [{"id": "s2"}]},
                                  ],
                              },
                              headers=auth_headers)
        assert gen_resp.get_json()["code"] == 0

        # 删除第一个任务
        del_resp = client.delete('/api/v1/generation/tasks/task-keep-0',
                                headers=auth_headers)
        assert del_resp.get_json()["code"] == 0

        # 验证被删除的任务不可查
        get_deleted = client.get('/api/v1/generation/tasks/task-keep-0',
                                headers=auth_headers)
        assert get_deleted.get_json()["code"] == 4004

        # 验证剩余任务仍可查
        get_remaining = client.get('/api/v1/generation/tasks/task-keep-1',
                                  headers=auth_headers)
        remaining_data = get_remaining.get_json()
        assert remaining_data["code"] == 0
        assert remaining_data["data"]["task_id"] == "task-keep-1"

        # 验证批次仍存在
        get_batch = client.get(f'/api/v1/generation/batches/{batch_id_test}',
                              headers=auth_headers)
        batch_data = get_batch.get_json()
        assert batch_data["code"] == 0
        assert len(batch_data["data"]["tasks"]) == 1