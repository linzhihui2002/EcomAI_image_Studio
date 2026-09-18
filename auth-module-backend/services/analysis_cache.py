import json
from models.plan_analysis import PlanAnalysisTaskModel
from config import AIConfig


def get_cached_result(input_hash: str) -> dict or None:
    cached = PlanAnalysisTaskModel().find_by_hash(
        input_hash, ttl_seconds=AIConfig.ANALYSIS_CACHE_TTL
    )
    if cached and cached.get('result_json') is not None:
        return json.loads(cached['result_json'])
    return None


def set_cache_result(task_id: int, result: dict) -> None:
    json_str = json.dumps(result, ensure_ascii=False)
    PlanAnalysisTaskModel().update_status(task_id, 'completed', result_json=json_str)