<script setup lang="ts">
import QRCode from 'qrcode'

type LoginState = {
  status: 'idle' | 'starting' | 'waiting' | 'scanned' | 'reconnecting' | 'connected' | 'error'
  message: string
  loginUrl: string | null
  channelReady?: boolean | null
  sessionState?: 'unknown' | 'available' | 'missing' | 'invalid'
  lastTestAt?: number | null
  delivery?: { outbox_error?: string | null; pending_notification_count?: number; consecutive_failures?: number; expired_notification_count?: number; last_success_at?: number | null }
  testPush?: { status: 'idle' | 'sending' | 'sent' | 'error'; message: string }
}
const opened = ref(false)
const busy = ref(false)
const testing = ref(false)
const error = ref('')
const qrImage = ref('')
const state = ref<LoginState>({ status: 'idle', message: '', loginUrl: null })
const active = computed(() => ['starting', 'waiting', 'scanned', 'reconnecting'].includes(state.value.status))
let timer: ReturnType<typeof setInterval> | undefined
let generation = 0
const trigger = ref<HTMLButtonElement>()
const closeButton = ref<HTMLButtonElement>()

watch(() => state.value.loginUrl, async (url, _, cleanup) => {
  let current = true
  cleanup(() => { current = false })
  qrImage.value = ''
  if (!url) return
  try {
    const image = await QRCode.toDataURL(url, { width: 280, margin: 4, errorCorrectionLevel: 'M' })
    if (current) qrImage.value = image
  } catch {
    // The original login link remains usable if local QR rendering fails.
  }
})

async function sync(start = false) {
  if (busy.value) return
  const requestGeneration = generation
  busy.value = true
  error.value = ''
  try {
    const result = await $fetch<LoginState>('/api/wechat/login', {
      method: start ? 'POST' : 'GET', retry: 0, timeout: 5000,
    })
    if (opened.value && generation === requestGeneration) state.value = result
  } catch {
    if (opened.value && generation === requestGeneration) error.value = '连接服务暂不可用，请稍后重试。'
  } finally {
    if (generation === requestGeneration) busy.value = false
  }
}

async function open() {
  opened.value = true
  generation++
  busy.value = false
  await nextTick()
  closeButton.value?.focus()
  void sync()
  timer = setInterval(() => { void sync() }, 2000)
}

async function testPush() {
  if (testing.value || state.value.testPush?.status === 'sending') return
  testing.value = true
  const requestGeneration = generation
  try {
    const result = await $fetch<LoginState>('/api/wechat/test', { method: 'POST', retry: 0, timeout: 5000 })
    if (opened.value && generation === requestGeneration) state.value.testPush = result.testPush
  } catch {
    if (opened.value && generation === requestGeneration) {
      state.value.testPush = { status: 'error', message: '未能确认发送状态，请稍后查看微信或重新打开窗口。' }
    }
  } finally {
    testing.value = false
  }
}

function close() {
  opened.value = false
  generation++
  busy.value = false
  if (timer) clearInterval(timer)
  timer = undefined
  trigger.value?.focus()
}

function onKey(event: KeyboardEvent) {
  if (!opened.value) return
  if (event.key === 'Escape') close()
  if (event.key === 'Tab') {
    const dialog = closeButton.value?.closest('[role="dialog"]')
    const buttons = dialog?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href]')
    if (!buttons?.length) return
    const first = buttons[0]!
    const last = buttons[buttons.length - 1]!
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
  }
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('keydown', onKey)
})
</script>

<template>
  <button ref="trigger" type="button" class="btn btn-ghost gap-1.5" aria-haspopup="dialog" :aria-expanded="opened" @click="open">
    <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
      <path d="M21 11.5c0 4.1-4 7.5-9 7.5-1.3 0-2.6-.2-3.7-.7L4 20l1.2-3.7A6.8 6.8 0 0 1 3 11.5C3 7.4 7 4 12 4s9 3.4 9 7.5Z" />
      <circle cx="9" cy="10" r=".6" /><circle cx="15" cy="10" r=".6" />
    </svg>
    微信连接
  </button>
  <Teleport to="body">
    <div v-if="opened" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" @click.self="close">
      <section role="dialog" aria-modal="true" aria-labelledby="wechat-connect-title" class="card max-h-[90vh] w-full max-w-sm overflow-y-auto p-5 text-ui-text">
        <div class="flex items-center justify-between gap-4">
          <h2 id="wechat-connect-title" class="text-lg font-semibold">微信连接</h2>
          <button ref="closeButton" type="button" class="btn btn-ghost" aria-label="关闭微信连接" @click="close">关闭</button>
        </div>
        <dl class="mt-3 space-y-1 text-sm text-ui-text-2" aria-live="polite">
          <div class="flex justify-between"><dt>通道</dt><dd>{{ state.channelReady == null ? '检查中' : state.channelReady ? '运行中' : '未就绪' }}</dd></div>
          <div class="flex justify-between"><dt>消息会话</dt><dd>{{ state.sessionState === 'available' ? '已建立，发送时验证' : state.sessionState === 'invalid' ? '已失效，请给机器人发消息' : state.sessionState === 'missing' ? '待建立，请给机器人发消息' : '检查中' }}</dd></div>
          <div class="flex justify-between"><dt>最近测试</dt><dd>{{ state.testPush?.status === 'sent' ? '发送成功' : state.testPush?.status === 'error' ? '发送失败' : state.testPush?.status === 'sending' ? '发送中' : '尚未测试' }}</dd></div>
          <div class="flex justify-between"><dt>待发消息 / 连续失败</dt><dd>{{ state.delivery?.pending_notification_count || 0 }} / {{ state.delivery?.consecutive_failures || 0 }}</dd></div>
          <div v-if="state.delivery?.expired_notification_count" class="flex justify-between"><dt>已过期或达到重试上限</dt><dd>{{ state.delivery.expired_notification_count }}</dd></div>
        </dl>
        <p v-if="state.delivery?.outbox_error" class="mt-3 text-sm text-ui-danger" role="alert">{{ state.delivery.outbox_error }}</p>
        <p class="mt-3 text-sm text-ui-text-2" aria-live="polite">{{ state.message || '正在检查微信连接…' }}</p>
        <img v-if="qrImage && state.loginUrl" :src="qrImage" width="280" height="280" alt="使用微信扫一扫连接机器人" class="mx-auto mt-4 rounded-lg bg-white">
        <a v-if="state.loginUrl" :href="state.loginUrl" target="_blank" rel="noopener noreferrer" class="mt-3 block text-center text-sm font-semibold text-accent underline">打开扫码链接 ↗</a>
        <p v-if="error" role="alert" class="mt-3 text-sm text-ui-danger">{{ error }}</p>
        <button type="button" class="btn btn-primary mt-5 w-full" :disabled="busy || active" @click="sync(true)">
          {{ active ? (state.status === 'reconnecting' ? '正在启动微信通道…' : state.status === 'scanned' ? '等待手机确认…' : '等待微信扫码…') : state.channelReady || state.status === 'connected' ? '重新扫码连接' : '生成二维码 / 扫码链接' }}
        </button>
        <button type="button" class="btn btn-ghost mt-3 w-full border border-ui-hairline" :disabled="testing || state.testPush?.status === 'sending' || active" @click="testPush">
          {{ testing || state.testPush?.status === 'sending' ? '正在发送测试消息…' : '测试微信推送' }}
        </button>
        <p v-if="state.testPush?.message" role="status" aria-live="polite" class="mt-3 text-sm" :class="state.testPush.status === 'error' ? 'text-ui-danger' : state.testPush.status === 'sent' ? 'text-accent' : 'text-ui-text-2'">{{ state.testPush.message }}</p>
        <p class="mt-3 text-xs text-ui-text-3">扫码成功后，请给机器人发一条消息以接收预警。关闭窗口不影响已开始的扫码。</p>
      </section>
    </div>
  </Teleport>
</template>
