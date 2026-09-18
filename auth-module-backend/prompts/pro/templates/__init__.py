"""品类模板加载器 - 加载品类特定模板，不存在时回退到通用模板（专业模式已移除，此文件保留以防止导入错误）"""
import os
from enum import Enum
from typing import Optional, Dict


class ProImageType(str, Enum):
    MAIN_IMAGE = "main_image"
    SCENE = "scene"
    WHITE_BG = "white_bg"
    SELLING_POINT = "selling_point"
    MATERIAL = "material"


TEMPLATES_DIR = os.path.dirname(os.path.abspath(__file__))
FALLBACK_DIR = os.path.dirname(TEMPLATES_DIR)

CATEGORY_IMAGE_TYPES = {
    ProImageType.MAIN_IMAGE: "main_image.txt",
    ProImageType.SCENE: "scene.txt",
    ProImageType.WHITE_BG: "white_bg.txt",
    ProImageType.SELLING_POINT: "selling_point.txt",
    ProImageType.MATERIAL: "material.txt",
}


class CategoryTemplateLoader:

    def __init__(self):
        self._cache: Dict[str, str] = {}

    def _make_cache_key(self, category: str, image_type: ProImageType) -> str:
        return f"{category}:{image_type.value}"

    def load_template(self, category: str, image_type: ProImageType) -> Optional[str]:
        cache_key = self._make_cache_key(category, image_type)
        if cache_key in self._cache:
            return self._cache[cache_key]

        filename = CATEGORY_IMAGE_TYPES.get(image_type)
        if not filename:
            return None

        category_path = os.path.join(TEMPLATES_DIR, category, filename)
        if os.path.exists(category_path):
            with open(category_path, 'r', encoding='utf-8') as f:
                template = f.read().strip()
            self._cache[cache_key] = template
            return template

        fallback_path = os.path.join(FALLBACK_DIR, filename)
        if os.path.exists(fallback_path):
            with open(fallback_path, 'r', encoding='utf-8') as f:
                template = f.read().strip()
            self._cache[cache_key] = template
            return template

        return None

    def has_category_template(self, category: str, image_type: ProImageType) -> bool:
        filename = CATEGORY_IMAGE_TYPES.get(image_type)
        if not filename:
            return False
        return os.path.exists(os.path.join(TEMPLATES_DIR, category, filename))

    def reload(self):
        self._cache.clear()


category_template_loader = CategoryTemplateLoader()
