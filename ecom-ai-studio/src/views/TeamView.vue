<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import type { TeamMember, TeamInvitation } from '@/types'
import { Users, Plus, LogIn, Copy, Trash2, Crown, Shield, BarChart3, Key, Wallet, Coins, ArrowRight, AlertCircle, Loader2, Check, ChevronDown, ChevronUp, AlertTriangle, Send, History } from 'lucide-vue-next'
import {
  createTeam as apiCreateTeam,
  joinTeam as apiJoinTeam,
  getTeamInvitation,
  refreshInvitation,
  getTeamMembers,
  dissolveTeam as apiDissolveTeam,
  transferToTeam as apiTransferToTeam,
  getTeamTransferLogs,
} from '@/api/team'
import { fetchUserBalance } from '@/api/user'
import type { TransferLog } from '@/types'
import { getErrorMessage } from '@/lib/error'

const auth = useAuthStore()
const router = useRouter()

const showCreateModal = ref(false)
const showJoinModal = ref(false)

const newTeamName = ref('')
const newTeamCategory = ref('')
const joinCode = ref('')
const createError = ref('')
const joinError = ref('')
const refreshError = ref('')
const refreshSuccess = ref(false)

const categories = ['服装/鞋包', '3C电子', '家居园艺', '美妆个护', '运动户外', '其他']

const selectedTeamId = ref<string | null>(null)

const currentTeamData = computed(() =>
  auth.teams.find((t) => t.id === selectedTeamId.value),
)

const isOwner = computed(() => {
  if (!selectedTeamId.value || !currentTeamData.value) return false
  return currentTeamData.value.ownerId === auth.user?.id
})

// 邀请码
const currentInvitation = ref<TeamInvitation | null>(null)
const refreshingCode = ref(false)
const copied = ref(false)
const invitationLoading = ref(false)

// 成员列表
const teamMembers = ref<TeamMember[]>([])
const membersLoading = ref(false)

const creating = ref(false)
const joining = ref(false)

// 高级设置（解散团队）
const showAdvancedSettings = ref(false)

// 解散确认
const showConfirmDissolve = ref(false)
const dissolveConfirmName = ref('')
const dissolving = ref(false)
const dissolveError = ref('')
const dissolveSuccessMsg = ref('')

// 转账
const showTransferPanel = ref(false)
const transferAmount = ref<number | null>(null)
const transferring = ref(false)
const transferError = ref('')
const transferSuccess = ref(false)

// 转账记录
const showTransferLogs = ref(false)
const transferLogs = ref<TransferLog[]>([])
const transferLogsLoading = ref(false)

const roleLabels: Record<string, string> = {
  owner: '创建者',
  admin: '管理员',
  member: '成员',
}

// 选中团队变化时加载邀请码和成员
watch(selectedTeamId, async (newVal) => {
  currentInvitation.value = null
  teamMembers.value = []
  if (newVal && isOwner.value) {
    await loadInvitation(newVal)
  }
  if (newVal) {
    await loadMembers(newVal)
  }
})

async function loadInvitation(teamId: string) {
  invitationLoading.value = true
  try {
    const res = await getTeamInvitation(teamId)
    currentInvitation.value = res.data?.invitation || null
  } catch {
    currentInvitation.value = null
  } finally {
    invitationLoading.value = false
  }
}

async function loadMembers(teamId: string) {
  membersLoading.value = true
  try {
    const res = await getTeamMembers(teamId)
    teamMembers.value = res.data?.members || []
  } catch {
    teamMembers.value = []
  } finally {
    membersLoading.value = false
  }
}

async function createTeam() {
  if (!newTeamName.value || !newTeamCategory.value) return

  if (newTeamName.value.trim().length < 2) {
    createError.value = '团队名称至少需要 2 个字符'
    return
  }

  creating.value = true
  createError.value = ''

  try {
    const res = await apiCreateTeam({
      name: newTeamName.value.trim(),
      category: newTeamCategory.value,
    })

    if (res.data?.team) {
      auth.teams.push(res.data.team)
      selectedTeamId.value = res.data.team.id
    }

    showCreateModal.value = false
    newTeamName.value = ''
    newTeamCategory.value = ''
  } catch (err) {
    createError.value = getErrorMessage(err, '创建团队失败，请稍后重试')
  } finally {
    creating.value = false
  }
}

async function joinTeam() {
  if (!joinCode.value || joinCode.value.trim().length < 6) return

  joining.value = true
  joinError.value = ''

  try {
    const res = await apiJoinTeam(joinCode.value.trim())

    if (res.data?.team) {
      auth.teams.push(res.data.team)
      selectedTeamId.value = res.data.team.id
    }

    showJoinModal.value = false
    joinCode.value = ''
  } catch (err) {
    joinError.value = getErrorMessage(err, '加入团队失败，请稍后重试')
  } finally {
    joining.value = false
  }
}

async function generateNewCode() {
  if (!selectedTeamId.value) return
  refreshingCode.value = true
  refreshError.value = ''
  try {
    const res = await refreshInvitation(selectedTeamId.value)
    if (res.data?.invitation) {
      currentInvitation.value = res.data.invitation
      refreshSuccess.value = true
      setTimeout(() => (refreshSuccess.value = false), 2000)
    } else {
      refreshError.value = '邀请码生成失败，服务器返回异常，请稍后重试'
    }
  } catch (err) {
    refreshError.value = getErrorMessage(err, '邀请码刷新失败，请稍后重试')
  } finally {
    refreshingCode.value = false
  }
}

async function copyInviteCode() {
  if (!currentInvitation.value?.code) return
  try {
    await navigator.clipboard.writeText(currentInvitation.value.code)
    copied.value = true
    setTimeout(() => (copied.value = false), 2000)
  } catch {
    // 降级：选中文本手动复制
  }
}

function removeMember(_id: string) {
  // 待实现
}

function goToTeamTopup() {
  router.push({ path: '/purchase', query: { action: 'topup' } })
}

// ==================== 解散团队 ====================

async function refreshPersonalBalance() {
  if (!auth.user) return
  try {
    const res = await fetchUserBalance('personal')
    if (res.code === 0 && auth.user) {
      auth.user.personalPoints = res.data.balance
    }
  } catch {
    // 余额刷新是非关键操作，失败不阻断解散流程
  }
}

async function confirmDissolveTeam() {
  if (!selectedTeamId.value || !currentTeamData.value) return
  if (dissolveConfirmName.value !== currentTeamData.value.name) return

  dissolving.value = true
  dissolveError.value = ''
  dissolveSuccessMsg.value = ''

  try {
    const res = await apiDissolveTeam(selectedTeamId.value)
    const data = res.data!
    // 先关闭弹窗
    showConfirmDissolve.value = false
    dissolveConfirmName.value = ''
    // 等待 Vue 完成当前渲染周期后再变更团队状态，避免渲染崩溃
    await nextTick()
    auth.removeTeam(selectedTeamId.value)
    selectedTeamId.value = null
    showAdvancedSettings.value = false
    showTransferPanel.value = false
    showTransferLogs.value = false
    // 刷新个人钱包余额（解散后团队余额已自动转入）
    await refreshPersonalBalance()
    // 用内联消息替代 alert()
    dissolveSuccessMsg.value = data.message
    setTimeout(() => { dissolveSuccessMsg.value = '' }, 5000)
  } catch (err) {
    dissolveError.value = getErrorMessage(err, '解散团队失败，请稍后重试')
  } finally {
    dissolving.value = false
  }
}

// ==================== 转账 ====================

function setMaxTransfer() {
  transferAmount.value = auth.user?.personalPoints ?? 0
}

async function doTransfer() {
  if (!selectedTeamId.value || !transferAmount.value || transferAmount.value <= 0) return

  transferring.value = true
  transferError.value = ''
  transferSuccess.value = false

  try {
    const res = await apiTransferToTeam(selectedTeamId.value, transferAmount.value)
    const data = res.data!
    // 更新 store 余额
    if (auth.user) {
      auth.user.personalPoints = data.newPersonalBalance
    }
    const team = auth.teams.find((t) => t.id === selectedTeamId.value)
    if (team) {
      team.poolBalance = data.newTeamBalance
    }
    transferSuccess.value = true
    transferAmount.value = null
    setTimeout(() => { transferSuccess.value = false }, 3000)
  } catch (err) {
    transferError.value = getErrorMessage(err, '转账失败，请稍后重试')
  } finally {
    transferring.value = false
  }
}

// ==================== 转账记录 ====================

async function loadTransferLogs() {
  if (!selectedTeamId.value) return
  transferLogsLoading.value = true
  try {
    const res = await getTeamTransferLogs(selectedTeamId.value)
    transferLogs.value = (res as any).data?.logs || []
    showTransferLogs.value = true
  } catch {
    transferLogs.value = []
  } finally {
    transferLogsLoading.value = false
  }
}

function formatDate(isoStr: string): string {
  if (!isoStr) return '—'
  return isoStr.split('T')[0]
}

function isInvitationExpired(inv: TeamInvitation): boolean {
  if (!inv.expiresAt) return false
  return new Date(inv.expiresAt) < new Date()
}
</script>

<template>
  <div class="p-6 max-w-6xl mx-auto">
    <div class="flex items-center justify-between mb-6">
      <h2 class="text-xl font-semibold text-slate-900">
        <Users class="w-5 h-5 inline mr-2 text-brand-purple" />
        团队管理
      </h2>
      <div class="flex items-center gap-2">
        <button
          @click="showJoinModal = true"
          class="btn-secondary text-sm"
        >
          <LogIn class="w-4 h-4 inline mr-1" />
          加入团队
        </button>
        <button
          @click="showCreateModal = true"
          class="btn-primary text-sm"
        >
          <Plus class="w-4 h-4 inline mr-1" />
          创建团队
        </button>
      </div>
    </div>

    <div class="flex items-center gap-2 mb-6">
      <button
        @click="selectedTeamId = null"
        :class="[
          'px-4 py-2 rounded-xl text-sm font-medium transition-all duration-200',
          !selectedTeamId
            ? 'bg-brand-gradient-subtle text-brand-purple'
            : 'bg-slate-100 text-slate-500 hover:text-slate-700',
        ]"
      >
        👤 我的个人空间
      </button>
      <button
        v-for="team in auth.teams"
        :key="team.id"
        @click="selectedTeamId = team.id; auth.switchTeam(team.id)"
        :class="[
          'px-4 py-2 rounded-xl text-sm font-medium transition-all duration-200',
          selectedTeamId === team.id
            ? 'bg-brand-gradient-subtle text-brand-purple'
            : 'bg-slate-100 text-slate-500 hover:text-slate-700',
        ]"
      >
        {{ team.name }}
      </button>
    </div>

    <div v-if="selectedTeamId && currentTeamData" class="glass-card overflow-hidden animate-fade-in">
      <div class="p-5 border-b border-slate-100">
        <div class="flex items-start justify-between">
          <div>
            <h3 class="text-lg font-semibold text-slate-900">{{ currentTeamData.name }}</h3>
            <p class="text-sm text-slate-500 mt-0.5">
              {{
                categories.includes(currentTeamData.category || '')
                  ? currentTeamData.category
                  : '其他'
              }}
              · {{ teamMembers.length }} 名成员
            </p>
          </div>
          <!-- 邀请码区域 -->
          <div v-if="isOwner" class="flex items-center gap-6">
            <div class="text-center">
              <p class="text-xs text-slate-500 mb-1">邀请码</p>
              <div v-if="invitationLoading" class="flex items-center gap-2">
                <Loader2 class="w-4 h-4 animate-spin text-slate-400" />
              </div>
              <div v-else-if="currentInvitation" class="flex flex-col items-center gap-0.5">
                <div class="flex items-center gap-2">
                  <code
                    :class="[
                      'px-3 py-1.5 rounded-lg bg-slate-100 text-sm font-mono font-semibold tracking-widest',
                      isInvitationExpired(currentInvitation)
                        ? 'text-red-500 line-through'
                        : 'text-brand-purple',
                    ]"
                  >
                    {{ currentInvitation.code }}
                  </code>
                  <button
                    title="复制邀请码"
                    class="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
                    @click="copyInviteCode"
                  >
                    <Check v-if="copied" class="w-4 h-4 text-green-500" />
                    <Copy v-else class="w-4 h-4" />
                  </button>
                </div>
                <div class="flex items-center gap-2 text-[10px] mt-0.5">
                  <span
                    :class="[
                      isInvitationExpired(currentInvitation)
                        ? 'text-red-400'
                        : 'text-slate-400',
                    ]"
                  >
                    有效期至 {{ formatDate(currentInvitation.expiresAt) }}
                  </span>
                  <span class="text-slate-300">|</span>
                  <span
                    :class="[
                      currentInvitation.usageCount >= currentInvitation.maxUsage
                        ? 'text-red-400'
                        : 'text-slate-400',
                    ]"
                  >
                    已使用 {{ currentInvitation.usageCount }}/{{ currentInvitation.maxUsage }} 次
                  </span>
                </div>
              </div>
              <div v-else class="text-xs text-slate-400">
                暂无有效邀请码
              </div>
              <Transition name="fade">
                <span v-if="refreshSuccess" class="text-xs text-green-500 mt-1">
                  邀请码已刷新
                </span>
              </Transition>
            </div>
            <Transition name="fade">
              <div
                v-if="refreshError"
                class="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-sm text-red-600"
              >
                <AlertCircle class="w-4 h-4 flex-shrink-0" />
                {{ refreshError }}
              </div>
            </Transition>
            <button
              @click="generateNewCode"
              :disabled="refreshingCode"
              class="btn-secondary text-xs disabled:opacity-50"
            >
              <Loader2 v-if="refreshingCode" class="w-3.5 h-3.5 inline mr-1 animate-spin" />
              <Key v-else class="w-3.5 h-3.5 inline mr-1" />
              生成新码
            </button>
          </div>
        </div>

        <!-- 团队钱包信息卡片 -->
        <div class="mt-4 p-4 rounded-xl bg-gradient-to-br from-brand-gradient-subtle/40 to-purple-50/20 border border-brand-purple/15">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-3">
              <div class="w-10 h-10 rounded-xl bg-brand-purple/10 flex items-center justify-center">
                <Wallet class="w-5 h-5 text-brand-purple" />
              </div>
              <div>
                <p class="text-xs font-medium text-slate-600">团队共享钱包</p>
                <p class="text-[11px] text-slate-400">所有团队成员均可使用此余额进行 AI 生图</p>
              </div>
            </div>
            <div class="text-right">
              <p class="text-2xl font-bold text-brand-purple">{{ currentTeamData.poolBalance.toLocaleString() }}</p>
              <p class="text-[11px] text-slate-400">灵感币</p>
            </div>
          </div>
          <div v-if="isOwner" class="mt-3 pt-3 border-t border-brand-purple/10 flex items-center justify-between">
            <div class="flex items-start gap-1.5">
              <AlertCircle class="w-3.5 h-3.5 text-blue-500 mt-0.5 flex-shrink-0" />
              <p class="text-[11px] text-blue-600 leading-relaxed">
                作为 Owner，你可以为团队充值灵感币。成员使用团队钱包生图时将从此余额扣除。
              </p>
            </div>
            <button
              @click="goToTeamTopup"
              class="ml-4 px-3 py-1.5 rounded-lg text-xs font-semibold bg-brand-purple text-white hover:bg-brand-purple/90 transition-colors flex items-center gap-1 whitespace-nowrap cursor-pointer"
            >
              <Coins class="w-3.5 h-3.5" />
              充值团队钱包
              <ArrowRight class="w-3 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      <!-- 成员列表 -->
      <div class="p-5">
        <h4 class="text-sm font-semibold text-slate-700 mb-3">成员列表</h4>
        <div v-if="membersLoading" class="flex items-center justify-center py-8">
          <Loader2 class="w-5 h-5 animate-spin text-slate-400" />
        </div>
        <div v-else-if="teamMembers.length === 0" class="text-center py-8 text-sm text-slate-400">
          暂无成员数据
        </div>
        <div v-else class="space-y-2">
          <div
            v-for="member in teamMembers"
            :key="member.id"
            class="flex items-center justify-between py-2 px-3 rounded-lg hover:bg-slate-50 transition-colors"
          >
            <div class="flex items-center gap-3">
              <div
                :class="[
                  'w-9 h-9 rounded-full flex items-center justify-center text-white text-sm font-semibold',
                  member.role === 'owner'
                    ? 'bg-brand-gradient'
                    : member.role === 'admin'
                      ? 'bg-blue-400'
                      : 'bg-slate-300',
                ]"
              >
                {{ (member.email || '?').charAt(0).toUpperCase() }}
              </div>
              <div>
                <p class="text-sm font-medium text-slate-800">{{ member.email }}</p>
                <div class="flex items-center gap-2">
                  <span class="text-xs text-slate-500">
                    {{ roleLabels[member.role] || member.role }}
                    · 加入于 {{ formatDate(member.joinedAt) }}
                  </span>
                </div>
              </div>
            </div>
            <div class="flex items-center gap-2">
              <Crown v-if="member.role === 'owner'" class="w-4 h-4 text-amber-500" />
              <Shield v-else-if="member.role === 'admin'" class="w-4 h-4 text-blue-400" />
              <Shield v-else class="w-4 h-4 text-slate-300" />
              <button
                v-if="isOwner && member.role !== 'owner'"
                @click="removeMember(member.id)"
                class="px-2 py-1 rounded-lg text-xs text-red-400 hover:bg-red-50 hover:text-red-500 transition-colors"
              >
                <Trash2 class="w-3.5 h-3.5 inline mr-0.5" />
                移除
              </button>
            </div>
          </div>

          <!-- 转账至团队 -->
          <div class="mt-3 pt-3 border-t border-brand-purple/10">
            <div class="flex items-center justify-between mb-2">
              <button
                @click="showTransferPanel = !showTransferPanel"
                class="flex items-center gap-1.5 text-xs font-medium text-slate-600 hover:text-brand-purple transition-colors cursor-pointer"
              >
                <Send class="w-3.5 h-3.5" />
                转入资金到团队钱包
                <ChevronDown v-if="!showTransferPanel" class="w-3 h-3" />
                <ChevronUp v-else class="w-3 h-3" />
              </button>
              <button
                @click="loadTransferLogs"
                class="flex items-center gap-1 text-xs text-slate-400 hover:text-brand-purple transition-colors cursor-pointer"
              >
                <History class="w-3 h-3" />
                转账记录
              </button>
            </div>

            <!-- 转账面板 -->
            <Transition name="fade">
              <div v-if="showTransferPanel" class="space-y-3 p-3 rounded-lg bg-white/60 border border-slate-100">
                <div class="flex items-center justify-between text-xs">
                  <span class="text-slate-500">我的个人余额</span>
                  <span class="font-semibold text-brand-purple">
                    {{ (auth.user?.personalPoints ?? 0).toLocaleString() }} 灵感币
                  </span>
                </div>
                <div class="flex items-center gap-2">
                  <input
                    v-model.number="transferAmount"
                    type="number"
                    min="1"
                    placeholder="输入转账金额"
                    class="flex-1 px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:border-brand-purple/50"
                  />
                  <button
                    @click="setMaxTransfer"
                    class="px-2.5 py-2 rounded-lg text-xs font-medium bg-slate-100 text-slate-600 hover:bg-slate-200 transition-colors whitespace-nowrap cursor-pointer"
                  >
                    全部转入
                  </button>
                </div>
                <Transition name="fade">
                  <div
                    v-if="transferError"
                    class="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-xs text-red-600"
                  >
                    <AlertCircle class="w-3.5 h-3.5 flex-shrink-0" />
                    {{ transferError }}
                  </div>
                </Transition>
                <Transition name="fade">
                  <div
                    v-if="transferSuccess"
                    class="flex items-center gap-2 px-3 py-2 rounded-lg bg-green-50 border border-green-200 text-xs text-green-600"
                  >
                    <Check class="w-3.5 h-3.5 flex-shrink-0" />
                    转账成功！余额已更新
                  </div>
                </Transition>
                <button
                  @click="doTransfer"
                  :disabled="!transferAmount || transferAmount <= 0 || transferring"
                  class="w-full py-2 rounded-lg text-xs font-semibold bg-brand-purple text-white hover:bg-brand-purple/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
                >
                  <Loader2 v-if="transferring" class="w-3.5 h-3.5 inline mr-1 animate-spin" />
                  确认转账
                </button>
              </div>
            </Transition>
          </div>
        </div>

        <!-- 转账记录面板 -->
        <Transition name="fade">
          <div
            v-if="showTransferLogs"
            class="mt-3 p-4 rounded-xl bg-white border border-slate-200"
          >
            <div class="flex items-center justify-between mb-3">
              <h5 class="text-sm font-semibold text-slate-700">转账记录</h5>
              <button
                @click="showTransferLogs = false"
                class="text-xs text-slate-400 hover:text-slate-600 cursor-pointer"
              >
                关闭
              </button>
            </div>
            <div v-if="transferLogsLoading" class="flex items-center justify-center py-4">
              <Loader2 class="w-4 h-4 animate-spin text-slate-400" />
            </div>
            <div v-else-if="transferLogs.length === 0" class="text-center py-4 text-xs text-slate-400">
              暂无转账记录
            </div>
            <div v-else class="space-y-2">
              <div
                v-for="log in transferLogs"
                :key="log.id"
                class="flex items-center justify-between py-2 px-3 rounded-lg bg-slate-50 text-xs"
              >
                <div class="flex items-center gap-2">
                  <Send
                    :class="[
                      'w-3.5 h-3.5',
                      log.transferType === 'personal_to_team'
                        ? 'text-green-500'
                        : 'text-blue-500',
                    ]"
                  />
                  <span class="text-slate-600">
                    {{ log.transferType === 'personal_to_team' ? '转入团队' : '团队解散转入' }}
                  </span>
                  <span class="text-slate-400">
                    {{ (log as any).fromUserEmail || '—' }}
                  </span>
                </div>
                <div class="flex items-center gap-3">
                  <span
                    :class="[
                      'font-semibold',
                      log.transferType === 'personal_to_team'
                        ? 'text-green-600'
                        : 'text-blue-600',
                    ]"
                  >
                    {{ log.transferType === 'personal_to_team' ? '+' : '+' }}{{ log.amount.toLocaleString() }}
                  </span>
                  <span class="text-slate-400">{{ formatDate(log.createdAt) }}</span>
                  <span
                    :class="[
                      'px-1.5 py-0.5 rounded text-[10px]',
                      log.status === 'success'
                        ? 'bg-green-100 text-green-600'
                        : 'bg-red-100 text-red-600',
                    ]"
                  >
                    {{ log.status === 'success' ? '成功' : '失败' }}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </Transition>
      </div>

      <!-- 高级设置（解散团队）-->
      <div v-if="isOwner" class="border-t border-slate-100 p-5">
        <button
          @click="showAdvancedSettings = !showAdvancedSettings"
          class="flex items-center gap-2 text-sm font-semibold text-slate-500 hover:text-red-500 transition-colors cursor-pointer"
        >
          <ChevronDown v-if="!showAdvancedSettings" class="w-4 h-4" />
          <ChevronUp v-else class="w-4 h-4" />
          高级设置
        </button>
        <Transition name="fade">
          <div v-if="showAdvancedSettings" class="mt-3">
            <div class="p-4 rounded-xl bg-red-50 border border-red-200">
              <div class="flex items-start gap-3">
                <AlertTriangle class="w-5 h-5 text-red-500 mt-0.5 flex-shrink-0" />
                <div>
                  <h5 class="text-sm font-semibold text-red-700">危险操作：解散团队</h5>
                  <p class="text-xs text-red-600 mt-1 leading-relaxed">
                    解散后所有团队成员将被移除，团队数据不可恢复。
                    <template v-if="currentTeamData.poolBalance > 0">
                      团队钱包剩余 <strong>{{ currentTeamData.poolBalance.toLocaleString() }} 灵感币</strong>将在解散时自动转入您的个人钱包。
                    </template>
                    <template v-else>
                      团队钱包余额为零，解散后无法恢复。
                    </template>
                  </p>
                  <button
                    @click="showConfirmDissolve = true; dissolveError = ''; dissolveConfirmName = ''"
                    class="mt-3 px-4 py-2 rounded-lg text-xs font-semibold bg-red-500 text-white hover:bg-red-600 transition-colors cursor-pointer"
                  >
                    解散团队
                  </button>
                </div>
              </div>
            </div>
          </div>
        </Transition>
      </div>

      <div v-if="isOwner" class="border-t border-slate-100 p-5">
        <h4 class="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
          <BarChart3 class="w-4 h-4 text-brand-purple" />
          近7天团队算力消耗
        </h4>
        <div class="flex items-end gap-2 h-32">
          <div
            v-for="i in 7"
            :key="i"
            class="flex-1 flex flex-col items-center gap-1"
          >
            <div
              class="w-full rounded-t-md bg-brand-gradient opacity-80 transition-all hover:opacity-100"
              :style="{ height: `${Math.random() * 60 + 20}%` }"
            />
            <span class="text-[10px] text-slate-400">
              {{ ['一', '二', '三', '四', '五', '六', '日'][i - 1] }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 解散成功提示 -->
    <Transition name="fade">
      <div
        v-if="dissolveSuccessMsg"
        class="max-w-2xl mx-auto mt-4 p-4 rounded-xl bg-green-50 border border-green-200 flex items-start gap-3"
      >
        <Check class="w-5 h-5 text-green-500 mt-0.5 flex-shrink-0" />
        <div>
          <p class="text-sm font-semibold text-green-700">操作成功</p>
          <p class="text-xs text-green-600 mt-0.5">{{ dissolveSuccessMsg }}</p>
        </div>
      </div>
    </Transition>

    <!-- 无团队时 -->
    <div
      v-if="!selectedTeamId && auth.teams.length === 0"
      class="text-center py-16 text-slate-400"
    >
      <Users class="w-12 h-12 mx-auto mb-4 opacity-50" />
      <p class="font-medium text-slate-500 mb-2">暂无团队</p>
      <p class="text-sm mb-4">创建或加入一个团队，与成员共享资产和算力</p>
      <div class="flex items-center justify-center gap-2">
        <button @click="showCreateModal = true" class="btn-primary text-sm">
          <Plus class="w-4 h-4 inline mr-1" />
          创建团队
        </button>
        <button @click="showJoinModal = true" class="btn-secondary text-sm">
          <LogIn class="w-4 h-4 inline mr-1" />
          加入团队
        </button>
      </div>
    </div>

    <!-- 创建团队弹窗 -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showCreateModal"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          @click.self="showCreateModal = false; createError = ''"
        >
          <div class="bg-white rounded-2xl w-full max-w-md mx-4 p-6 shadow-2xl animate-scale-in">
            <h3 class="text-lg font-semibold text-slate-900 mb-4">创建团队</h3>
            <div class="space-y-4">
              <div>
                <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                  团队名称
                </label>
                <input
                  v-model="newTeamName"
                  type="text"
                  placeholder="2~20 个字符"
                  maxlength="20"
                  class="glass-input w-full px-4 py-2.5 text-sm"
                />
              </div>
              <div>
                <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                  主营类目
                </label>
                <select
                  v-model="newTeamCategory"
                  class="w-full rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-700"
                >
                  <option value="" disabled>请选择类目</option>
                  <option v-for="cat in categories" :key="cat" :value="cat">
                    {{ cat }}
                  </option>
                </select>
              </div>
              <Transition name="fade">
                <div
                  v-if="createError"
                  class="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-sm text-red-600"
                >
                  <AlertCircle class="w-4 h-4 flex-shrink-0" />
                  {{ createError }}
                </div>
              </Transition>
            </div>
            <div class="flex gap-3 mt-6">
              <button
                @click="showCreateModal = false; createError = ''"
                class="btn-secondary flex-1"
                :disabled="creating"
              >
                取消
              </button>
              <button
                @click="createTeam"
                :disabled="!newTeamName || !newTeamCategory || creating"
                class="btn-primary flex-1 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Loader2 v-if="creating" class="w-4 h-4 inline mr-1 animate-spin" />
                创建
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 加入团队弹窗 -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showJoinModal"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          @click.self="showJoinModal = false; joinError = ''"
        >
          <div class="bg-white rounded-2xl w-full max-w-md mx-4 p-6 shadow-2xl animate-scale-in">
            <h3 class="text-lg font-semibold text-slate-900 mb-4">加入团队</h3>
            <div>
              <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                邀请码
              </label>
              <input
                v-model="joinCode"
                type="text"
                placeholder="输入邀请码"
                class="glass-input w-full px-4 py-2.5 text-sm tracking-widest text-center"
              />
            </div>
            <Transition name="fade">
              <div
                v-if="joinError"
                class="mt-3 flex items-center gap-2 px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-sm text-red-600"
              >
                <AlertCircle class="w-4 h-4 flex-shrink-0" />
                {{ joinError }}
              </div>
            </Transition>
            <div class="flex gap-3 mt-6">
              <button
                @click="showJoinModal = false; joinError = ''"
                class="btn-secondary flex-1"
                :disabled="joining"
              >
                取消
              </button>
              <button
                @click="joinTeam"
                :disabled="joinCode.length < 6 || joining"
                class="btn-primary flex-1 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Loader2 v-if="joining" class="w-4 h-4 inline mr-1 animate-spin" />
                加入
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 解散团队确认弹窗 -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showConfirmDissolve"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          @click.self="showConfirmDissolve = false; dissolveError = ''; dissolveConfirmName = ''"
        >
          <div class="bg-white rounded-2xl w-full max-w-md mx-4 p-6 shadow-2xl animate-scale-in">
            <div class="flex items-center gap-2 mb-4">
              <AlertTriangle class="w-5 h-5 text-red-500" />
              <h3 class="text-lg font-semibold text-slate-900">确认解散团队？</h3>
            </div>
            <div class="space-y-3">
              <div class="p-3 rounded-lg bg-slate-50 text-sm text-slate-600 space-y-1.5">
                <p>
                  <strong>团队名称：</strong>{{ currentTeamData?.name }}
                </p>
                <p>
                  <strong>成员数量：</strong>{{ teamMembers.length }} 人
                </p>
                <p v-if="currentTeamData && currentTeamData.poolBalance > 0">
                  <strong>余额转移：</strong>{{ currentTeamData.poolBalance.toLocaleString() }} 灵感币将自动转入您的个人钱包
                </p>
                <p v-else>
                  <strong>余额转移：</strong>无（团队钱包余额为零）
                </p>
              </div>
              <p class="text-xs text-red-500">
                此操作不可撤销，请输入团队名称以确认：
              </p>
              <input
                v-model="dissolveConfirmName"
                type="text"
                :placeholder="`输入「${currentTeamData?.name}」确认`"
                class="w-full px-4 py-2.5 rounded-lg border border-slate-200 text-sm focus:outline-none focus:border-red-400"
              />
              <Transition name="fade">
                <div
                  v-if="dissolveError"
                  class="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-sm text-red-600"
                >
                  <AlertCircle class="w-4 h-4 flex-shrink-0" />
                  {{ dissolveError }}
                </div>
              </Transition>
            </div>
            <div class="flex gap-3 mt-6">
              <button
                @click="showConfirmDissolve = false; dissolveError = ''; dissolveConfirmName = ''"
                class="btn-secondary flex-1 cursor-pointer"
                :disabled="dissolving"
              >
                取消
              </button>
              <button
                @click="confirmDissolveTeam"
                :disabled="dissolveConfirmName !== currentTeamData?.name || dissolving"
                class="flex-1 px-4 py-2.5 rounded-xl text-sm font-semibold bg-red-500 text-white hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
              >
                <Loader2 v-if="dissolving" class="w-4 h-4 inline mr-1 animate-spin" />
                确认解散
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: all 0.2s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>