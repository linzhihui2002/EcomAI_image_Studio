"""
EcomAI Studio 认证模块 - 应用入口
"""
import sys
import os
from decimal import Decimal
from datetime import datetime, date

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify
from flask.json.provider import DefaultJSONProvider
from flask_cors import CORS
from flask_compress import Compress
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import get_config
from routes.auth import auth_bp
from routes.purchase import purchase_bp
from routes.favorite import favorite_bp
from routes.admin import admin_bp
from routes.announcement import announcement_bp
from routes.team import team_bp
from routes.generation import generation_bp
from routes.toolbox import toolbox_bp
from routes.history import history_bp
from routes.images import images_bp
from routes.feature_pricing import feature_pricing_bp
from routes.sse_routes import sse_bp
from routes.editor_routes import editor_bp
from routes.template_routes import template_bp
from routes.compliance_routes import compliance_bp
from routes.batch_routes import batch_bp
from routes.user_ai_provider import user_ai_provider_bp
from services.auth_service import AuthError


def _run_migrations(config, app):
    """启动时执行 migrations 目录下未执行过的 SQL 文件（基于 _migrations 追踪表）"""
    import glob as _glob
    import pymysql

    migrations_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'migrations')
    if not os.path.isdir(migrations_dir):
        app.logger.info('[Migration] migrations 目录不存在，跳过迁移')
        return

    sql_files = sorted(_glob.glob(os.path.join(migrations_dir, '*.sql')))
    if not sql_files:
        app.logger.info('[Migration] 无迁移文件，跳过')
        return

    conn = pymysql.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
        charset='utf8mb4',
    )
    try:
        with conn.cursor() as cursor:
            # 1. 创建迁移追踪表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS _migrations (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    filename VARCHAR(255) NOT NULL UNIQUE,
                    executed_at DATETIME DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            ''')
            conn.commit()

            # 2. 查询已执行的迁移
            cursor.execute('SELECT filename FROM _migrations')
            executed = {row[0] for row in cursor.fetchall()}

            # 3. 执行未执行过的迁移
            for sql_file in sql_files:
                filename = os.path.basename(sql_file)
                if filename in executed:
                    app.logger.info(f'[Migration] 跳过已执行: {filename}')
                    continue

                try:
                    with open(sql_file, 'r', encoding='utf-8') as f:
                        sql_content = f.read()
                    # 按分号拆分多条语句，跳过空语句
                    raw_statements = [s.strip() for s in sql_content.split(';') if s.strip()]
                    for stmt in raw_statements:
                        # 移除所有注释行后，若剩余内容为空则跳过
                        pure_sql = '\n'.join(
                            line for line in stmt.split('\n')
                            if line.strip() and not line.strip().startswith('--')
                        ).strip()
                        if not pure_sql:
                            continue
                        cursor.execute(pure_sql)
                    # 记录已执行
                    cursor.execute(
                        'INSERT INTO _migrations (filename) VALUES (%s)',
                        (filename,)
                    )
                    conn.commit()
                    app.logger.info(f'[Migration] 已执行: {filename}')
                except pymysql.err.OperationalError as e:
                    app.logger.warning(f'[Migration] {filename} 执行警告: {e}')
                except Exception as e:
                    app.logger.error(f'[Migration] {filename} 执行失败: {e}')
                    # 不阻断启动，只记录错误
    finally:
        conn.close()


def _seed_feature_pricing(config, app):
    """启动时若 feature_pricing 表为空，自动插入默认定价数据"""
    import pymysql

    conn = pymysql.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
        charset='utf8mb4',
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) AS cnt FROM feature_pricing')
            row = cursor.fetchone()
            if row and row[0] > 0:
                app.logger.info('[Seed] feature_pricing 表已有数据，跳过种子')
                return

            # 从 FEATURE_KEY_REGISTRY 读取默认定价
            from services.feature_pricing_service import FEATURE_KEY_REGISTRY
            import json

            for item in FEATURE_KEY_REGISTRY:
                pricing_type = item['pricing_type']
                if pricing_type == 'per_image_resolution':
                    config_json = json.dumps({
                        'tiers': [
                            {'tier': '1K', 'max_dimension': 1024, 'coins': 5},
                            {'tier': '2K', 'max_dimension': 2048, 'coins': 10},
                            {'tier': '4K', 'max_dimension': 4096, 'coins': 15},
                        ]
                    }, ensure_ascii=False)
                else:
                    config_json = json.dumps({'coins': 5}, ensure_ascii=False)

                cursor.execute(
                    '''INSERT IGNORE INTO feature_pricing
                       (feature_key, display_name, category, pricing_type, config, description, sort_order)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                    (
                        item['feature_key'],
                        item['display_name'],
                        item['category'],
                        pricing_type,
                        config_json,
                        item.get('description', ''),
                        FEATURE_KEY_REGISTRY.index(item) + 1,
                    )
                )
            conn.commit()
            app.logger.info(f'[Seed] 已插入 {len(FEATURE_KEY_REGISTRY)} 条默认定价数据')
    except Exception as e:
        app.logger.error(f'[Seed] 种子数据插入失败: {e}')
    finally:
        conn.close()


# 平台合规规则种子数据（P0-2）：依据公开平台政策常识自行编写
# rules: 图型级规则；global_forbidden: 平台级禁元素（含严重度 warning/block）
_COMPLIANCE_SEED_GLOBAL_FORBIDDEN = [
    {"name": "竞品品牌词/Logo", "severity": "block",
     "keywords": ["competitor logo", "other brand logo", "brand wordmark of another company"]},
    {"name": "二维码", "severity": "block", "keywords": ["qr code", "barcode"]},
    {"name": "水印", "severity": "block", "keywords": ["watermark", "semi-transparent logo overlay"]},
    {"name": "联系方式/网址", "severity": "block",
     "keywords": ["website url", "contact information", "phone number", "social media handle"]},
    {"name": "物流/促销文字", "severity": "warning",
     "keywords": ["free shipping", "fast delivery", "fba", "discount", "sale tag",
                  "best price", "promo code", "coupon badge"]},
    {"name": "夸大宣传/绝对化用语", "severity": "warning",
     "keywords": ["best seller", "no.1", "top rated badge", "100% guarantee",
                  "medical cure claim", "fda approved"]},
]

_COMPLIANCE_SEEDS = {
    "amazon": {
        "main_image": {
            "background": "pure white RGB(255,255,255)",
            "background_rgb": [255, 255, 255],
            "product_min_ratio": 0.85,
            "text_policy": "no_text_no_watermark_no_promo_labels",
            "props": "forbidden",
            "aspect_ratio": "1:1",
            "size_min_px": 1600,
            "severity": "block",
        },
        "scene": {"background": "lifestyle scene allowed", "model_allowed": True,
                  "text_policy": "site_language_only", "severity": "warning"},
        "detail": {"background": "any clean background", "text_policy": "site_language_only",
                   "severity": "warning"},
    },
    "temu": {
        "main_image": {
            "background": "pure white RGB(255,255,255)",
            "background_rgb": [255, 255, 255],
            "product_min_ratio": 0.80,
            "text_policy": "no_text_no_watermark",
            "aspect_ratio": "1:1",
            "size_min_px": 1350,
            "severity": "block",
        },
        "scene": {"background": "lifestyle scene allowed", "model_allowed": True,
                  "text_policy": "site_language_only", "severity": "warning"},
        "detail": {"background": "any clean background", "text_policy": "site_language_only",
                   "severity": "warning"},
    },
    "shopee": {
        "main_image": {
            "background": "white or light solid background preferred",
            "product_min_ratio": 0.70,
            "text_policy": "minimal text, no watermarks, no misleading claims",
            "aspect_ratio": "1:1",
            "size_min_px": 1024,
            "severity": "warning",
        },
        "scene": {"background": "lifestyle scene allowed", "model_allowed": True,
                  "text_policy": "site_language_only", "severity": "warning"},
        "detail": {"background": "any clean background", "text_policy": "site_language_only",
                   "severity": "warning"},
    },
    "tiktok_shop": {
        "main_image": {
            "background": "pure white RGB(255,255,255)",
            "background_rgb": [255, 255, 255],
            "product_min_ratio": 0.80,
            "text_policy": "no_text_no_watermark",
            "aspect_ratio": "1:1 or 3:4",
            "size_min_px": 1080,
            "severity": "block",
        },
        "scene": {"background": "short-video style scene, vertical 9:16 friendly",
                  "model_allowed": True, "text_policy": "site_language_only",
                  "severity": "warning"},
        "detail": {"background": "any clean background", "text_policy": "site_language_only",
                   "severity": "warning"},
    },
    "aliexpress": {
        "main_image": {
            "background": "pure white RGB(255,255,255)",
            "background_rgb": [255, 255, 255],
            "product_min_ratio": 0.85,
            "text_policy": "no_text_no_watermark",
            "aspect_ratio": "1:1",
            "size_min_px": 1000,
            "severity": "block",
        },
        "scene": {"background": "lifestyle scene allowed", "model_allowed": True,
                  "text_policy": "site_language_only", "severity": "warning"},
        "detail": {"background": "any clean background", "text_policy": "site_language_only",
                   "severity": "warning"},
    },
    "ozon": {
        "main_image": {
            "background": "white or light solid background",
            "product_min_ratio": 0.70,
            "text_policy": "no watermarks; Russian text allowed on secondary images only",
            "aspect_ratio": "3:4",
            "size_min_px": 900,
            "severity": "block",
        },
        "scene": {"background": "lifestyle scene allowed", "model_allowed": True,
                  "text_policy": "russian_text_preferred", "severity": "warning"},
        "detail": {"background": "any clean background", "text_policy": "russian_text_preferred",
                   "severity": "warning"},
    },
}


def _seed_compliance_rules(config, app):
    """启动时按平台粒度补齐 platform_compliance_rules 种子数据（存在即跳过）"""
    import pymysql

    conn = pymysql.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
        charset='utf8mb4',
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT DISTINCT platform FROM platform_compliance_rules'
            )
            existing = {row[0] for row in cursor.fetchall()}
            missing = [p for p in _COMPLIANCE_SEEDS if p not in existing]
            if not missing:
                app.logger.info('[Seed] platform_compliance_rules 各平台均已存在，跳过种子')
                return

            import json
            inserted = 0
            for platform in missing:
                image_rules = _COMPLIANCE_SEEDS[platform]
                for image_type, rules in image_rules.items():
                    cursor.execute(
                        '''INSERT INTO platform_compliance_rules
                           (platform, image_type, rules, global_forbidden, enabled)
                           VALUES (%s, %s, %s, %s, 1)
                           ON DUPLICATE KEY UPDATE enabled = enabled''',
                        (
                            platform,
                            image_type,
                            json.dumps(rules, ensure_ascii=False),
                            json.dumps({"items": _COMPLIANCE_SEED_GLOBAL_FORBIDDEN},
                                       ensure_ascii=False),
                        )
                    )
                    inserted += 1
            conn.commit()
            app.logger.info(f'[Seed] 已补齐平台合规规则种子: 平台={missing} 共 {inserted} 条')
    except Exception as e:
        app.logger.error(f'[Seed] 平台合规规则种子插入失败: {e}')
    finally:
        conn.close()


def create_app(env=None):
    """应用工厂函数"""
    app = Flask(__name__)

    # 自定义 JSON Provider：处理 Decimal、date、datetime 类型（Flask 3.x 兼容）
    class CustomJSONProvider(DefaultJSONProvider):
        def default(self, obj):
            if isinstance(obj, Decimal):
                return float(obj)
            if isinstance(obj, (datetime, date)):
                return obj.isoformat()
            return super().default(obj)

    app.json = CustomJSONProvider(app)

    # 启用 Gzip 压缩（减小 API 响应体积 50-80%）
    Compress(app)

    # 加载配置
    config = get_config(env)
    app.config.from_object(config)
    
    # 启用 CORS（允许前端跨域请求）
    # 支持通过环境变量 CORS_ALLOWED_ORIGINS 指定允许的来源（逗号分隔）
    # 开发模式默认允许全部来源
    _cors_origins = os.environ.get('CORS_ALLOWED_ORIGINS', '*')
    if _cors_origins == '*':
        CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)
    else:
        _origins_list = [o.strip() for o in _cors_origins.split(',') if o.strip()]
        CORS(app, resources={r"/api/*": {"origins": _origins_list}}, supports_credentials=True)
    
    # 设置安全响应头
    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        return response

    # 反向代理（nginx / 云隧道）场景：还原真实客户端 IP 与协议。
    # 不开启时 request.remote_addr 会是代理 IP，导致 flask-limiter 退化为全局限流。
    if os.environ.get('TRUST_PROXY_HEADERS', 'false').lower() in ('1', 'true', 'yes'):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # 速率限制：防滥用，基于 IP 限制每分钟请求数
    _rate_limit = os.environ.get('RATE_LIMIT_PER_MINUTE', '200')
    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=[f"{_rate_limit} per minute"],
    )
    
    # 自动执行数据库迁移（仅执行未执行过的迁移）
    _run_migrations(config, app)

    # 若 feature_pricing 表为空，自动种子默认定价数据
    _seed_feature_pricing(config, app)

    # 按平台补齐平台合规规则种子数据
    _seed_compliance_rules(config, app)

    # 注册路由蓝图
    app.register_blueprint(auth_bp)
    app.register_blueprint(purchase_bp)
    app.register_blueprint(favorite_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(announcement_bp)
    app.register_blueprint(team_bp)
    app.register_blueprint(generation_bp)
    app.register_blueprint(toolbox_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(images_bp)
    app.register_blueprint(feature_pricing_bp)
    app.register_blueprint(sse_bp)
    app.register_blueprint(editor_bp)
    app.register_blueprint(template_bp)
    app.register_blueprint(compliance_bp)
    app.register_blueprint(batch_bp)
    app.register_blueprint(user_ai_provider_bp)
    
    # 全局错误处理器
    @app.errorhandler(AuthError)
    def handle_auth_error(error):
        """处理 AuthError 业务异常"""
        return jsonify({
            'code': error.code,
            'message': error.message,
            'data': None
        }), error.http_status
    
    @app.errorhandler(404)
    def handle_not_found(error):
        """处理 404"""
        return jsonify({
            'code': 5001,
            'message': '接口不存在',
            'data': None
        }), 404
    
    @app.errorhandler(405)
    def handle_method_not_allowed(error):
        """处理 405"""
        return jsonify({
            'code': 5001,
            'message': '请求方法不允许',
            'data': None
        }), 405
    
    @app.errorhandler(500)
    def handle_internal_error(error):
        """处理 500"""
        return jsonify({
            'code': 5001,
            'message': '服务器内部错误',
            'data': None
        }), 500
    
    @app.errorhandler(Exception)
    def handle_uncaught_exception(error):
        """兜底捕获所有未处理异常，确保始终返回 JSON（debug 模式下也会优先生效）"""
        import traceback
        app.logger.error(f'Uncaught exception: {traceback.format_exc()}')
        from werkzeug.exceptions import HTTPException
        if isinstance(error, HTTPException):
            return jsonify({
                'code': 5001,
                'message': '服务器内部错误',
                'data': None
            }), error.code
        return jsonify({
            'code': 5001,
            'message': '服务器内部错误',
            'data': None
        }), 500
    
    # 健康检查接口
    @app.route('/api/v1/health', methods=['GET'])
    def health_check():
        return jsonify({'code': 0, 'message': 'ok', 'data': {'status': 'healthy'}})
    
    # 根路径
    @app.route('/', methods=['GET'])
    def index():
        return jsonify({
            'code': 0,
            'message': 'EcomAI Studio Auth API',
            'data': {
                'version': '1.0.0',
                'docs': '/api/v1/health'
            }
        })
    
    return app


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)