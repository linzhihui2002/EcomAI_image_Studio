"""平台合规规则数据模型（P0-2）

platform_compliance_rules 表：每平台 × 图型一行，rules 为图型级规则 JSON，
global_forbidden 为平台级禁元素 JSON（{"items": [{name, severity, keywords}]}）。
"""
import json
from dataclasses import dataclass
from typing import List, Optional

import pymysql

from config import get_config


@dataclass
class ComplianceRule:
    """单条平台合规规则"""
    platform: str
    image_type: str
    rules: dict
    global_forbidden: dict
    enabled: bool = True
    id: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "platform": self.platform,
            "image_type": self.image_type,
            "rules": self.rules,
            "global_forbidden": self.global_forbidden,
            "enabled": self.enabled,
        }


def _parse_json(value) -> dict:
    """pymysql 默认把 JSON 列作为字符串返回，统一解析为 dict"""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return {}
    return {}


class ComplianceRuleModel:
    """platform_compliance_rules 表 CRUD（pymysql 裸 SQL）"""

    def __init__(self):
        self.config = get_config()

    def _get_connection(self):
        return pymysql.connect(
            host=self.config.MYSQL_HOST,
            port=self.config.MYSQL_PORT,
            user=self.config.MYSQL_USER,
            password=self.config.MYSQL_PASSWORD,
            database=self.config.MYSQL_DATABASE,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
        )

    @staticmethod
    def _to_rule(row: dict) -> ComplianceRule:
        return ComplianceRule(
            id=row.get('id'),
            platform=row.get('platform', ''),
            image_type=row.get('image_type', ''),
            rules=_parse_json(row.get('rules')),
            global_forbidden=_parse_json(row.get('global_forbidden')),
            enabled=bool(row.get('enabled', 1)),
        )

    def get_rules(self, platform: str) -> List[ComplianceRule]:
        """查询指定平台的所有启用规则"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT * FROM platform_compliance_rules '
                    'WHERE platform = %s AND enabled = 1',
                    (platform,)
                )
                rows = cursor.fetchall()
                return [self._to_rule(r) for r in rows]
        finally:
            conn.close()

    def get_global_forbidden(self, platform: str) -> List[dict]:
        """查询平台级禁元素列表（取任一行 global_forbidden.items）"""
        rules = self.get_rules(platform)
        for rule in rules:
            items = rule.global_forbidden.get('items')
            if isinstance(items, list):
                return items
        return []
