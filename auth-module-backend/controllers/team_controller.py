"""
团队控制器
处理 HTTP 请求参数校验、调用业务服务、格式化响应
所有接口均需登录（由路由层 token_required 保证）
"""
import traceback
from flask import request, jsonify, g
from services.team_service import (
    create_team as do_create_team,
    join_team as do_join_team,
    get_user_teams as do_get_user_teams,
    get_active_invitation as do_get_active_invitation,
    refresh_invitation as do_refresh_invitation,
    verify_invitation as do_verify_invitation,
    get_team_members as do_get_team_members,
    dissolve_team as do_dissolve_team,
)
from services.transfer_service import transfer_personal_to_team as do_transfer_to_team
from models.transfer_log import TransferLogModel
from services.auth_service import AuthError


def success_response(data=None, message='success', code=0):
    """统一成功响应"""
    return jsonify({'code': code, 'message': message, 'data': data})


def error_response(code, message, http_status=400, data=None):
    """统一错误响应"""
    return jsonify({'code': code, 'message': message, 'data': data}), http_status


# ==================== 团队管理 ====================


def create_team():
    """POST /api/v1/teams - 创建团队"""
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    name = (data.get('name') or '').strip()
    category = (data.get('category') or '').strip()

    if not name:
        return error_response(3002, '团队名称不能为空', 400)
    if not category:
        return error_response(3002, '请选择主营类目', 400)

    try:
        team = do_create_team(g.current_user['user_id'], name, category)
        return success_response({'team': team}, '团队创建成功'), 201
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[TeamController] create_team error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


def join_team():
    """POST /api/v1/teams/join - 通过邀请码加入团队"""
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    invite_code = (data.get('inviteCode') or '').strip()

    if not invite_code:
        return error_response(3002, '邀请码不能为空', 400)

    try:
        team = do_join_team(g.current_user['user_id'], invite_code)
        return success_response({'team': team}, '加入团队成功')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[TeamController] join_team error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


def get_my_teams():
    """GET /api/v1/teams/mine - 获取当前用户的团队列表"""
    try:
        teams = do_get_user_teams(g.current_user['user_id'])
        return success_response({'teams': teams}, 'ok')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[TeamController] get_my_teams error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


# ==================== 邀请码管理 ====================


def get_invitation(team_id):
    """GET /api/v1/teams/<team_id>/invitation - 获取团队邀请码详情"""
    try:
        invitation = do_get_active_invitation(team_id, g.current_user['user_id'])
        if invitation is None:
            return success_response({'invitation': None}, '当前无有效邀请码')
        return success_response({'invitation': invitation}, 'ok')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[TeamController] get_invitation error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


def refresh_invitation(team_id):
    """POST /api/v1/teams/<team_id>/invitation/refresh - 刷新邀请码"""
    try:
        invitation = do_refresh_invitation(team_id, g.current_user['user_id'])
        return success_response({'invitation': invitation}, '邀请码已刷新')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[TeamController] refresh_invitation error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


def verify_invitation():
    """POST /api/v1/teams/invitation/verify - 验证邀请码是否有效"""
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    code = (data.get('code') or '').strip()

    if not code:
        return error_response(3002, '邀请码不能为空', 400)

    try:
        verification = do_verify_invitation(code)
        return success_response({'verification': verification}, 'ok')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[TeamController] verify_invitation error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


# ==================== 团队成员管理 ====================


def get_team_members(team_id):
    """GET /api/v1/teams/<team_id>/members - 获取团队成员列表"""
    try:
        members = do_get_team_members(team_id, g.current_user['user_id'])
        return success_response({'members': members}, 'ok')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[TeamController] get_team_members error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


# ==================== 解散团队 ====================


def dissolve_team(team_id):
    """DELETE /api/v1/teams/<team_id> - 解散团队（仅 Owner）"""
    try:
        ip_address = request.remote_addr
        result = do_dissolve_team(team_id, g.current_user['user_id'], ip_address)
        return success_response(result, 'ok')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[TeamController] dissolve_team error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


# ==================== 转账功能 ====================


def transfer_to_team(team_id):
    """POST /api/v1/teams/<team_id>/transfer - 个人向团队转账"""
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    try:
        amount = int(data.get('amount', 0))
    except (ValueError, TypeError):
        return error_response(3015, '转账金额必须为有效数字', 400)

    if amount <= 0:
        return error_response(3015, '转账金额必须大于 0', 400)

    try:
        ip_address = request.remote_addr
        result = do_transfer_to_team(
            g.current_user['user_id'], team_id, amount, ip_address
        )
        return success_response(result, '转账成功')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[TeamController] transfer_to_team error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


def get_team_transfer_logs(team_id):
    """GET /api/v1/teams/<team_id>/transfer-logs - 获取团队转账日志"""
    try:
        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('pageSize', 20, type=int)

        # 校验是否为团队成员
        from models.team import TeamModel
        team_model = TeamModel()
        member = team_model.find_member(team_id, g.current_user['user_id'])
        if not member:
            return error_response(3007, '团队不存在或您不是该团队成员', 404)

        transfer_log_model = TransferLogModel()
        result = transfer_log_model.find_by_team(team_id, page, page_size)
        return success_response(
            {'logs': result['data'], 'pagination': result['pagination']},
            'ok'
        )
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[TeamController] get_team_transfer_logs error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)