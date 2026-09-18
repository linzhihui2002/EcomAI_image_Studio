import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { User, Team, PointsRecord, WalletType } from '@/types'
import { fetchUserProfile, fetchUserBalance, fetchPointsRecords } from '@/api/user'
import { ApiError } from '@/api/client'
import { getErrorMessage, ERROR_DEFAULTS } from '@/lib/error'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const teams = ref<Team[]>([])
  const pointsRecords = ref<PointsRecord[]>([])
  const currentTeamId = ref<string | null>(null)
  const selectedWallet = ref<WalletType>('personal')
  const authLoading = ref(true)

  const isLoggedIn = computed(() => !!user.value)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const currentTeam = computed(() =>
    teams.value.find((t) => t.id === currentTeamId.value) || null,
  )

  const teamPoolBalance = computed<number>(() => {
    if (!currentTeamId.value) return 0
    const team = teams.value.find((t) => t.id === currentTeamId.value)
    return team?.poolBalance ?? 0
  })

  const selectedWalletBalance = computed<number>(() => {
    if (selectedWallet.value === 'team') {
      return teamPoolBalance.value
    }
    return user.value?.personalPoints ?? 0
  })

  async function login(email: string, passwordOrCode: string, isCodeLogin = false) {
    const url = isCodeLogin ? '/api/v1/auth/login/code' : '/api/v1/auth/login'
    const body = isCodeLogin 
      ? { email, code: passwordOrCode }
      : { email, password: passwordOrCode }

    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!response.headers.get('content-type')?.includes('application/json')) {
      // 开发环境打印后端实际返回内容（帮助定位问题）
      if (import.meta.env.DEV) {
        const text = await response.clone().text()
        console.error('[Auth:login] 后端返回非 JSON 响应', {
          status: response.status,
          contentType: response.headers.get('content-type'),
          body: text.substring(0, 500),
        })
      }
      throw new Error('登录服务暂时不可用，请稍后重试')
    }
    const data = await response.json()

    if (data.code !== 0) {
      // 登录接口上下文：后端 1001/1002 在此场景仅表示"凭证错误"（非 token 过期）
      // 因为用户尚未持有 token，不存在"过期"语义，需避免误显示"登录已过期"
      const loginErrorMap: Record<number, string> = {
        1001: '账号或密码错误，请重新输入',
        1002: '账号或密码错误，请重新输入',
        1004: '密码错误，请重新输入',
        1008: '账号不存在，请先注册',
      }
      const mappedMsg = loginErrorMap[data.code]
      throw new Error(mappedMsg || getErrorMessage(
        { code: data.code, message: data.message },
        ERROR_DEFAULTS.LOGIN_FAILED,
      ))
    }

    setToken(data.data.token)
    user.value = data.data.user
    teams.value = data.data.teams || []
    pointsRecords.value = data.data.pointsRecords || []
    selectedWallet.value = 'personal'
    authLoading.value = false
    
    // Refresh balance from API
    try {
      const balRes = await fetchUserBalance('personal')
      if (balRes.code === 0 && user.value) {
        user.value.personalPoints = balRes.data.balance
      }
    } catch { /* non-critical */ }
  }

  async function register(email: string, password: string, code: string) {
    const response = await fetch('/api/v1/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, code }),
    })
    if (!response.headers.get('content-type')?.includes('application/json')) {
      // 开发环境打印后端实际返回内容（帮助定位问题）
      if (import.meta.env.DEV) {
        const text = await response.clone().text()
        console.error('[Auth:register] 后端返回非 JSON 响应', {
          status: response.status,
          contentType: response.headers.get('content-type'),
          body: text.substring(0, 500),
        })
      }
      throw new Error('注册服务暂时不可用，请稍后重试')
    }
    const data = await response.json()

    if (data.code !== 0) {
      // 注册接口上下文：将后端错误码映射为用户友好的中文提示
      const registerErrorMap: Record<number, string> = {
        1007: '该邮箱已被注册，请直接登录',
        2006: '该邮箱已被注册，请直接登录',
        3002: '输入信息有误，请检查后提交',
        3009: '验证码无效或已过期，请重新获取',
        1005: '验证码错误或已过期，请重新获取',
        1006: '验证码发送过于频繁，请稍后再试',
      }
      const mappedMsg = registerErrorMap[data.code]
      throw new Error(mappedMsg || getErrorMessage(
        { code: data.code, message: data.message },
        ERROR_DEFAULTS.REGISTER_FAILED,
      ))
    }

    setToken(data.data.token)
    user.value = data.data.user
    teams.value = []
    pointsRecords.value = [{
      id: `pr-bonus-${Date.now()}`,
      amount: 100,
      type: 'bonus',
      sourceWallet: 'personal',
      description: '新用户注册赠送',
      createdAt: new Date().toISOString(),
    }]
    selectedWallet.value = 'personal'
  }

  function clearAuth() {
    localStorage.removeItem('ecomai_token')
    localStorage.removeItem('ecomai_logged_in')
    user.value = null
    teams.value = []
    pointsRecords.value = []
    currentTeamId.value = null
  }

  function logout() {
    clearAuth()
    selectedWallet.value = 'personal'
    authLoading.value = false
  }

  async function initAuth() {
    const token = getToken()
    if (!token) {
      authLoading.value = false
      return
    }
    try {
      // Fetch user profile
      const profileRes = await fetchUserProfile()
      if (profileRes.code === 0 && profileRes.data) {
        user.value = profileRes.data
        // 加载用户团队列表
        if (profileRes.data.teams) {
          teams.value = profileRes.data.teams
        }
      } else {
        clearAuth()
        return
      }

      // Refresh balance from API（确保与登录流程一致）
      try {
        const balRes = await fetchUserBalance('personal')
        if (balRes.code === 0 && user.value) {
          user.value.personalPoints = balRes.data.balance
        }
      } catch {
        // Balance refresh is non-critical, use value from profile
      }

      // Fetch points records
      try {
        const recordsRes = await fetchPointsRecords({ page: 1, pageSize: 50 })
        if (recordsRes.code === 0) {
          pointsRecords.value = recordsRes.data
        }
      } catch {
        // Points records are non-critical, continue without them
        pointsRecords.value = []
      }

    } catch (err: any) {
      // 认证相关错误（token无效/过期）或网络超时 → 清除本地状态让用户重新登录
      if (err instanceof ApiError && (err.code === 1001 || err.code === 1002 || err.code === -1)) {
        clearAuth()
      } else {
        // 其他错误暂不清除 token，保留重试机会
        user.value = null
        teams.value = []
        pointsRecords.value = []
        currentTeamId.value = null
      }
    } finally {
      authLoading.value = false
    }
  }

  function setUser(userData: User) {
    user.value = userData
  }

  function setToken(token: string) {
    localStorage.setItem('ecomai_token', token)
  }

  function getToken(): string | null {
    return localStorage.getItem('ecomai_token')
  }

  function switchTeam(teamId: string | null) {
    currentTeamId.value = teamId
    if (teamId && selectedWallet.value === 'team') {
      const team = teams.value.find((t) => t.id === teamId)
      if (!team || team.poolBalance <= 0) {
        selectedWallet.value = 'personal'
      }
    }
  }

  function switchWallet(wallet: WalletType) {
    if (wallet === 'team' && (!currentTeamId.value || teamPoolBalance.value <= 0)) {
      return
    }
    selectedWallet.value = wallet
  }

  function deductPoints(amount: number): boolean {
    // The actual deduction happens on the backend during generation
    // This is just a local optimistic update
    if (selectedWallet.value === 'personal') {
      if (!user.value || user.value.personalPoints < amount) return false
      user.value.personalPoints -= amount
      return true
    } else {
      const team = teams.value.find((t) => t.id === currentTeamId.value)
      if (!team || team.poolBalance < amount) return false
      team.poolBalance -= amount
      return true
    }
  }

  function topupPersonal(amount: number) {
    if (user.value) user.value.personalPoints += amount
  }

  function topupTeam(teamId: string, amount: number) {
    const team = teams.value.find((t) => t.id === teamId)
    if (team) team.poolBalance += amount
  }

  function addPointsRecord(record: PointsRecord) {
    pointsRecords.value.unshift(record)
  }

  function removeTeam(teamId: string) {
    teams.value = teams.value.filter((t) => t.id !== teamId)
    if (currentTeamId.value === teamId) {
      currentTeamId.value = null
      selectedWallet.value = 'personal'
    }
  }

  return {
    user,
    teams,
    pointsRecords,
    currentTeamId,
    selectedWallet,
    authLoading,
    isLoggedIn,
    isAdmin,
    currentTeam,
    teamPoolBalance,
    selectedWalletBalance,
    login,
    register,
    logout,
    initAuth,
    setUser,
    setToken,
    getToken,
    switchTeam,
    switchWallet,
    deductPoints,
    topupPersonal,
    topupTeam,
    addPointsRecord,
    removeTeam,
  }
})
