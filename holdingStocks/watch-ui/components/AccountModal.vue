<script setup lang="ts">
import type { AccountProfile } from '~/types/snapshot'

const props = defineProps<{
  show: boolean
  account?: AccountProfile | null
  isEdit?: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved', acc: AccountProfile): void
  (e: 'deleted', id: string): void
}>()

const availableStrategies = [
  { id: 'strategy38', name: '策略38 · 地量起爆多维选股', defaultType: 'short_term' },
  { id: 'strategy1', name: '策略1 · 核心龙头与强趋势', defaultType: 'short_term' },
  { id: 'strategy3', name: '策略3 · 鲍鱼捞饭反转信号', defaultType: 'short_term' },
  { id: 'strategy17', name: '策略17 · 破位反包企稳买点', defaultType: 'short_term' },
  { id: 'strategy13a', name: '因子13A · 核心质地长线配置', defaultType: 'long_term' },
  { id: 'strategy8', name: '策略8 · 行业双动量波段轮动', defaultType: 'long_term' },
]

const form = reactive({
  name: '',
  type: 'short_term' as 'long_term' | 'short_term',
  initial_capital: 200000,
  description: '',
  mounted_strategies: ['strategy38'] as string[],
  risk_rules: {
    max_position_pct: 0.20,
    stop_loss_pct: -0.04,
    max_hold_days: 5,
    cash_gate_sensitive: true,
  },
})

const loading = ref(false)
const errorMsg = ref('')

watch(
  () => props.account,
  (acc) => {
    if (acc && props.isEdit) {
      form.name = acc.name || ''
      form.type = acc.type || 'short_term'
      form.initial_capital = acc.initial_capital || 100000
      form.description = acc.description || ''
      form.mounted_strategies = [...(acc.mounted_strategies || [])]
      form.risk_rules = {
        max_position_pct: acc.risk_rules?.max_position_pct ?? 0.20,
        stop_loss_pct: acc.risk_rules?.stop_loss_pct ?? -0.04,
        max_hold_days: acc.risk_rules?.max_hold_days ?? 5,
        cash_gate_sensitive: acc.risk_rules?.cash_gate_sensitive ?? true,
      }
    } else {
      // 默认重置为新建
      form.name = ''
      form.type = 'short_term'
      form.initial_capital = 200000
      form.description = ''
      form.mounted_strategies = ['strategy38']
      form.risk_rules = {
        max_position_pct: 0.20,
        stop_loss_pct: -0.04,
        max_hold_days: 5,
        cash_gate_sensitive: true,
      }
    }
    errorMsg.value = ''
  },
  { immediate: true },
)

function onTypeChange(type: 'long_term' | 'short_term') {
  form.type = type
  if (type === 'long_term') {
    form.risk_rules.max_position_pct = 0.30
    form.risk_rules.stop_loss_pct = -0.10
    form.risk_rules.max_hold_days = 90
    form.risk_rules.cash_gate_sensitive = false
    form.mounted_strategies = ['strategy13a', 'strategy8']
  } else {
    form.risk_rules.max_position_pct = 0.20
    form.risk_rules.stop_loss_pct = -0.04
    form.risk_rules.max_hold_days = 5
    form.risk_rules.cash_gate_sensitive = true
    form.mounted_strategies = ['strategy38', 'strategy1']
  }
}

function toggleStrategy(id: string) {
  const idx = form.mounted_strategies.indexOf(id)
  if (idx >= 0) {
    form.mounted_strategies.splice(idx, 1)
  } else {
    form.mounted_strategies.push(id)
  }
}

async function handleSave() {
  if (!form.name.trim()) {
    errorMsg.value = '请输入账户名称'
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    const isEdit = Boolean(props.isEdit && props.account?.id)
    const url = isEdit ? '/api/accounts/update' : '/api/accounts'
    const body: any = {
      name: form.name.trim(),
      type: form.type,
      initial_capital: Number(form.initial_capital),
      description: form.description.trim(),
      mounted_strategies: form.mounted_strategies,
      risk_rules: form.risk_rules,
    }
    if (isEdit) {
      body.account_id = props.account?.id
    }
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const data = await res.json()
    if (!res.ok || data.error) {
      throw new Error(data.error || '保存账户失败')
    }
    emit('saved', data)
    emit('close')
  } catch (err: any) {
    errorMsg.value = err?.message || '操作失败'
  } finally {
    loading.value = false
  }
}

async function handleDelete() {
  if (!props.account?.id) return
  if (props.account.is_default) {
    errorMsg.value = '默认主账户受保护，不可删除'
    return
  }
  if (!confirm(`确定要彻底删除账户【${props.account.name}】吗？删除后其专属账本将被清理。`)) {
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await fetch('/api/accounts/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: props.account.id }),
    })
    const data = await res.json()
    if (!res.ok || data.error) {
      throw new Error(data.error || '删除账户失败')
    }
    emit('deleted', props.account.id)
    emit('close')
  } catch (err: any) {
    errorMsg.value = err?.message || '删除失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div
    v-if="show"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
    @click.self="emit('close')"
  >
    <div class="card w-full max-w-lg border border-ui-hairline bg-ui-surface p-5 shadow-2xl space-y-4">
      <div class="flex items-center justify-between border-b border-ui-hairline pb-3">
        <div class="flex items-center gap-2">
          <span class="rounded bg-accent/20 px-2 py-0.5 text-xs font-bold text-accent">
            {{ isEdit ? '账户设置' : '创建新交易账户' }}
          </span>
          <h3 class="text-sm font-bold text-ui-text">
            {{ isEdit ? account?.name : '添加独立交易沙盒' }}
          </h3>
        </div>
        <button
          type="button"
          class="text-ui-text-3 hover:text-ui-text text-sm p-1"
          @click="emit('close')"
        >
          ✕
        </button>
      </div>

      <div v-if="errorMsg" class="rounded bg-rose-500/10 border border-rose-500/30 p-2.5 text-xs text-rose-400">
        ⚠️ {{ errorMsg }}
      </div>

      <div class="space-y-3.5 text-xs">
        <!-- 账户定位类型 -->
        <div>
          <label class="block font-medium text-ui-text-2 mb-1.5">1. 账户定位与风格</label>
          <div class="grid grid-cols-2 gap-2">
            <button
              type="button"
              class="flex flex-col items-center justify-center rounded-lg border p-2.5 transition text-left"
              :class="form.type === 'short_term' ? 'border-amber-500/60 bg-amber-500/10 text-amber-300 font-bold' : 'border-ui-hairline bg-ui-surface-2/40 text-ui-text-3 hover:border-ui-hairline/80'"
              @click="onTypeChange('short_term')"
            >
              <div class="flex items-center gap-1.5 text-xs">
                <span>⚡ 短线进攻型</span>
              </div>
              <span class="text-[11px] font-normal text-ui-text-3 mt-1 text-center">
                高换手 · 紧止损 · 捕捉地量起爆与龙头买点
              </span>
            </button>
            <button
              type="button"
              class="flex flex-col items-center justify-center rounded-lg border p-2.5 transition text-left"
              :class="form.type === 'long_term' ? 'border-blue-500/60 bg-blue-500/10 text-blue-300 font-bold' : 'border-ui-hairline bg-ui-surface-2/40 text-ui-text-3 hover:border-ui-hairline/80'"
              @click="onTypeChange('long_term')"
            >
              <div class="flex items-center gap-1.5 text-xs">
                <span>🌟 长线稳健型</span>
              </div>
              <span class="text-[11px] font-normal text-ui-text-3 mt-1 text-center">
                底仓长持 · 宽止损 · 基本面质地与趋势波段
              </span>
            </button>
          </div>
        </div>

        <!-- 基础信息 -->
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block font-medium text-ui-text-3 mb-1">2. 账户名称</label>
            <input
              v-model="form.name"
              type="text"
              placeholder="例如：短线起爆一号"
              class="w-full rounded-md border border-ui-hairline bg-ui-surface px-2.5 py-1.5 text-ui-text focus:border-accent focus:outline-none"
            />
          </div>
          <div>
            <label class="block font-medium text-ui-text-3 mb-1">3. 初始分配资金 (元)</label>
            <input
              v-model.number="form.initial_capital"
              type="number"
              step="10000"
              class="w-full rounded-md border border-ui-hairline bg-ui-surface px-2.5 py-1.5 text-ui-text focus:border-accent focus:outline-none"
            />
          </div>
        </div>

        <!-- 挂载策略选择 -->
        <div>
          <label class="block font-medium text-ui-text-3 mb-1.5">
            4. 挂载执行策略 (策略触发时将自动在此账户扣款/成交)
          </label>
          <div class="grid grid-cols-2 gap-2">
            <div
              v-for="st in availableStrategies"
              :key="st.id"
              class="flex items-center gap-2 rounded-md border border-ui-hairline/60 bg-ui-surface-2/30 p-2 cursor-pointer hover:bg-ui-surface-2/60 transition"
              @click="toggleStrategy(st.id)"
            >
              <input
                type="checkbox"
                class="accent-accent rounded h-3.5 w-3.5"
                :checked="form.mounted_strategies.includes(st.id)"
                @click.stop="toggleStrategy(st.id)"
              />
              <span class="text-xs" :class="form.mounted_strategies.includes(st.id) ? 'text-ui-text font-semibold' : 'text-ui-text-3'">
                {{ st.name }}
              </span>
            </div>
          </div>
        </div>

        <!-- 专属风控与交易规则 -->
        <div class="rounded-lg border border-ui-hairline bg-ui-surface-2/30 p-3 space-y-2">
          <div class="font-semibold text-ui-text flex items-center justify-between">
            <span>5. 账户专属风控规则</span>
            <span class="text-[11px] text-accent font-normal">长短线差异化执行</span>
          </div>

          <div class="grid grid-cols-2 gap-3 pt-1">
            <div>
              <div class="flex justify-between text-[11px] text-ui-text-3 mb-1">
                <span>严格止损线:</span>
                <span class="font-bold text-ui-success">{{ (form.risk_rules.stop_loss_pct * 100).toFixed(1) }}%</span>
              </div>
              <input
                v-model.number="form.risk_rules.stop_loss_pct"
                type="range"
                min="-0.20"
                max="-0.02"
                step="0.01"
                class="w-full accent-ui-success"
              />
            </div>
            <div>
              <div class="flex justify-between text-[11px] text-ui-text-3 mb-1">
                <span>单票最大仓位:</span>
                <span class="font-bold text-accent">{{ (form.risk_rules.max_position_pct * 100).toFixed(0) }}%</span>
              </div>
              <input
                v-model.number="form.risk_rules.max_position_pct"
                type="range"
                min="0.10"
                max="0.50"
                step="0.05"
                class="w-full accent-accent"
              />
            </div>
          </div>

          <div class="flex items-center justify-between pt-1 text-[11px]">
            <label class="inline-flex items-center gap-1.5 cursor-pointer text-ui-text-2">
              <input
                v-model="form.risk_rules.cash_gate_sensitive"
                type="checkbox"
                class="accent-accent rounded"
              />
              <span>大盘触发因子35一票否决时强制空仓避险</span>
            </label>
            <div class="text-ui-text-3">
              建议最长持有: <b>{{ form.risk_rules.max_hold_days }} 天</b>
            </div>
          </div>
        </div>

        <!-- 描述备注 -->
        <div>
          <label class="block font-medium text-ui-text-3 mb-1">6. 账户备注说明</label>
          <input
            v-model="form.description"
            type="text"
            placeholder="例如：专用于验证低吸打板和策略38放量起爆"
            class="w-full rounded-md border border-ui-hairline bg-ui-surface px-2.5 py-1.5 text-ui-text focus:border-accent focus:outline-none"
          />
        </div>
      </div>

      <div class="flex items-center justify-between border-t border-ui-hairline pt-3">
        <div>
          <button
            v-if="isEdit && !account?.is_default"
            type="button"
            class="rounded px-2.5 py-1.5 text-xs text-rose-400 hover:bg-rose-500/15 transition"
            :disabled="loading"
            @click="handleDelete"
          >
            删除此账户
          </button>
        </div>
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="rounded-lg border border-ui-hairline bg-ui-surface px-3 py-1.5 text-xs text-ui-text hover:bg-ui-surface-2 transition"
            :disabled="loading"
            @click="emit('close')"
          >
            取消
          </button>
          <button
            type="button"
            class="rounded-lg bg-accent px-4 py-1.5 text-xs font-bold text-white shadow hover:opacity-90 transition disabled:opacity-50"
            :disabled="loading"
            @click="handleSave"
          >
            {{ loading ? '处理中…' : isEdit ? '保存变更' : '立即创建' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
