<script setup lang="ts">
import type { HoldingRow } from '~/types/snapshot'

defineProps<{ rows: HoldingRow[]; phase?: string }>()

const steps = [
  ['9:15', '竞价·可撤'],
  ['9:20', '不可撤'],
  ['9:25', '阈值/过门'],
  ['9:30', '信号触发'],
]

function baiduUrl(code?: string, name?: string) {
  const c = (code || '').replace(/\D/g, '')
  return `https://finance.baidu.com/stock/ab-${c}?name=${encodeURIComponent(name || '')}`
}

function fmt(v?: number | null, d = 2) {
  if (v == null) return '-'
  return v.toFixed(d)
}
</script>

<template>
  <div>
    <div class="card mb-4 p-3">
      <div class="flex flex-wrap gap-2 text-xs">
        <span v-for="[t, l] in steps" :key="t" class="rounded-full bg-accent/10 px-2 py-1 text-accent">{{ t }} {{ l }}</span>
      </div>
      <div class="mt-2 text-sm">当前：<strong>{{ phase || '-' }}</strong></div>
    </div>
    <div class="card overflow-x-auto">
      <table class="min-w-full text-sm">
        <thead class="bg-ui-fill-hover text-left text-ui-text-2">
          <tr>
            <th class="px-2 py-2">代码</th>
            <th class="px-2 py-2">名称</th>
            <th class="px-2 py-2">竞价/开盘</th>
            <th class="px-2 py-2">现价</th>
            <th class="px-2 py-2">前日</th>
            <th class="px-2 py-2">过门</th>
            <th class="px-2 py-2">阈值</th>
            <th class="px-2 py-2">买点</th>
            <th class="px-2 py-2">止损</th>
            <th class="px-2 py-2">因子侧</th>
            <th class="px-2 py-2">说明</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="String(r.代码)" class="border-t border-ui-hairline">
            <td class="px-2 py-2">
              <a :href="baiduUrl(r.代码, r.名称)" target="_blank" rel="noopener" class="sensitive text-accent hover:underline">{{ r.代码 }}</a>
            </td>
            <td class="px-2 py-2">
              <a :href="baiduUrl(r.代码, r.名称)" target="_blank" rel="noopener" class="sensitive hover:text-accent hover:underline">{{ r.名称 }}</a>
            </td>
            <td class="sensitive px-2 py-2">{{ r.阈值就绪 ? fmt(r.开盘, r['价位小数'] ?? 2) : (r.竞价参考 != null ? fmt(r.竞价参考, r['价位小数'] ?? 2) : '待9:25') }}</td>
            <td class="sensitive px-2 py-2">{{ fmt(r.现价, r['价位小数'] ?? 2) }}</td>
            <td class="px-2 py-2">{{ r.前日形态 || '-' }}</td>
            <td class="px-2 py-2 font-semibold" :class="r.过门OK ? 'text-up' : 'text-ui-text-2'">{{ r.过门 || '-' }}</td>
            <td class="px-2 py-2">{{ r['阈值%'] || '-' }}</td>
            <td class="sensitive px-2 py-2">{{ r.阈值就绪 ? fmt(r.买点, r['价位小数'] ?? 2) : '-' }}</td>
            <td class="sensitive px-2 py-2">{{ r.阈值就绪 ? fmt(r.止损, r['价位小数'] ?? 2) : '-' }}</td>
            <td class="px-2 py-2">{{ r.因子侧 || '-' }}</td>
            <td class="max-w-[220px] px-2 py-2 text-xs text-ui-text-2">{{ r.挂单说明 || r.预警 || '-' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
