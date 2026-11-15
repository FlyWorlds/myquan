<script setup lang="ts">
import type { AccountProfile } from '~/types/snapshot'

const props = defineProps<{
  accounts?: AccountProfile[]
  activeAccountId?: string
}>()

const emit = defineEmits<{
  (e: 'change', accountId: string): void
  (e: 'refresh'): void
}>()

const {
  accounts: globalAccounts,
  activeAccountId: globalActiveId,
  fetchAccounts,
  switchAccount: doSwitchAccount,
  initActiveAccount,
} = useAccounts()

// 优先采用全局单例账户列表，避免被 WebSocket 快照覆盖
const displayAccounts = computed(() => {
  return globalAccounts.value.length ? globalAccounts.value : props.accounts || []
})

const currentActiveId = computed(() => {
  return globalActiveId.value || props.activeAccountId || 'acc_default'
})

onMounted(() => {
  initActiveAccount()
  void fetchAccounts()
})

const showModal = ref(false)
const modalAccount = ref<AccountProfile | null>(null)
const isEditModal = ref(false)

function openCreateModal() {
  modalAccount.value = null
  isEditModal.value = false
  showModal.value = true
}

function openEditModal(acc: AccountProfile) {
  modalAccount.value = acc
  isEditModal.value = true
  showModal.value = true
}

async function selectAccount(aid: string) {
  if (aid === currentActiveId.value) return
  await doSwitchAccount(aid)
  emit('change', aid)
}

async function onAccountSaved(acc: AccountProfile) {
  await fetchAccounts()
  emit('refresh')
  if (!isEditModal.value && acc?.id) {
    await selectAccount(acc.id)
  }
}

async function onAccountDeleted(deletedId: string) {
  await fetchAccounts()
  emit('refresh')
  if (currentActiveId.value === deletedId) {
    await selectAccount('acc_default')
  }
}

function fmtMoneyWan(val?: number): string {
  if (val == null) return '0.00'
  return (val / 10000).toFixed(2)
}
</script>

<template>
  <div class="account-switcher-wrap flex flex-wrap items-center justify-between gap-2 border-b border-ui-hairline/60 pb-2.5">
    <div class="flex flex-wrap items-center gap-2">
      <span class="text-xs font-semibold text-ui-text-3">交易账户：</span>
      <div
        v-for="acc in displayAccounts"
        :key="acc.id"
        class="group inline-flex items-center rounded-lg border transition-all cursor-pointer text-xs"
        :class="
          acc.id === currentActiveId
            ? acc.type === 'long_term'
              ? 'border-blue-500/70 bg-blue-500/15 text-blue-200 shadow-sm'
              : 'border-amber-500/70 bg-amber-500/15 text-amber-200 shadow-sm'
            : 'border-ui-hairline bg-ui-surface-2/40 text-ui-text-3 hover:border-ui-hairline/80 hover:text-ui-text'
        "
        @click="selectAccount(acc.id)"
      >
        <!-- 账户主体按钮 -->
        <div class="flex items-center gap-1.5 px-2.5 py-1.5 font-medium">
          <span v-if="acc.is_default">🌟</span>
          <span v-else-if="acc.type === 'long_term'">📈</span>
          <span v-else>⚡</span>
          <span class="font-bold">{{ acc.name }}</span>

          <span
            class="rounded px-1.5 py-0.2 text-[10px] font-semibold"
            :class="
              acc.type === 'long_term'
                ? 'bg-blue-500/25 text-blue-300'
                : 'bg-amber-500/25 text-amber-300'
            "
          >
            {{ acc.type === 'long_term' ? '长线' : '短线' }}
          </span>

          <span class="ml-1 font-mono text-[11px] tabular-nums font-bold">
            ¥{{ fmtMoneyWan(acc.account_total) }}万
          </span>

          <span class="text-[10px] opacity-75">
            ({{ acc.positions_count || 0 }}只)
          </span>
        </div>

        <!-- 账户设置图标按钮 -->
        <button
          type="button"
          class="px-1.5 py-1.5 text-ui-text-3 hover:text-accent border-l border-ui-hairline/40 transition opacity-80 group-hover:opacity-100"
          title="账户设置与策略风控挂载"
          @click.stop="openEditModal(acc)"
        >
          ⚙️
        </button>
      </div>

      <!-- 添加账户按钮 -->
      <button
        type="button"
        class="inline-flex items-center gap-1 rounded-lg border border-dashed border-ui-hairline bg-ui-surface px-2.5 py-1.5 text-xs text-accent hover:border-accent hover:bg-accent/10 transition"
        @click="openCreateModal"
      >
        <span>➕</span>
        <span>添加账户</span>
      </button>
    </div>

    <div class="hidden sm:flex items-center gap-2 text-[11px] text-ui-text-3">
      <span>后台隔离运行 · 微信推送自动标明所属账户</span>
    </div>

    <!-- 弹窗 -->
    <AccountModal
      :show="showModal"
      :account="modalAccount"
      :is-edit="isEditModal"
      @close="showModal = false"
      @saved="onAccountSaved"
      @deleted="onAccountDeleted"
    />
  </div>
</template>
