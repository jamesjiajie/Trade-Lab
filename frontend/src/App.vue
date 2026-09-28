<script setup lang="ts">
import { init, use, type EChartsType } from 'echarts/core'
import { CandlestickChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

type Action = 'BUY' | 'SELL' | 'HOLD'
type Bar = { date: string; open: number; high: number; low: number; close: number; volume: number }
type Trade = { date: string; action: Action; shares: number; price: number }
type Account = { cash: number; shares: number; equity: number; trades: Trade[] }
type Curve = { date: string; manual: number; rule: number; benchmark: number }
type Session = {
  id: string; symbol: string; kind: 'stock' | 'etf'; source: string; date: string; step: number; total_steps: number
  finished: boolean; signal: Action; fee_rate: number; slippage: number; bars: Bar[]; curves: Curve[]
  accounts: { manual: Account; rule: Account; benchmark: Account }
  decisions: { date: string; action: Action; reason: string }[]
}
type SessionSummary = Pick<Session, 'id' | 'symbol' | 'kind' | 'source'> & { created_at: string }

const session = ref<Session | null>(null)
const sessions = ref<SessionSummary[]>([])
const symbol = ref('510300')
const kind = ref<'stock' | 'etf'>('etf')
const source = ref<'akshare' | 'csv'>('akshare')
const csvFile = ref<File | null>(null)
const feePercent = ref(0.1)
const slippagePercent = ref(0.1)
const action = ref<Action>('HOLD')
const reason = ref('')
const busy = ref(false)
const error = ref('')
const priceElement = ref<HTMLElement | null>(null)
const equityElement = ref<HTMLElement | null>(null)
use([CandlestickChart, LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])
let priceChart: EChartsType | null = null
let equityChart: EChartsType | null = null

const money = (value: number) => new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', maximumFractionDigits: 0 }).format(value)
const difference = computed(() => session.value ? session.value.accounts.manual.equity - session.value.accounts.rule.equity : 0)

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...options?.headers } })
  const body = await response.json()
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `请求失败 (${response.status})`)
  return body as T
}

async function refreshSessions() {
  sessions.value = await api<SessionSummary[]>('/sessions')
}

async function run(task: () => Promise<void>) {
  busy.value = true
  error.value = ''
  try { await task() } catch (caught) { error.value = caught instanceof Error ? caught.message : '操作失败' }
  finally { busy.value = false }
}

async function createSession() {
  await run(async () => {
    const csv_text = source.value === 'csv' ? await csvFile.value?.text() : undefined
    session.value = await api<Session>('/sessions', {
      method: 'POST', body: JSON.stringify({ symbol: symbol.value, kind: kind.value, source: source.value, csv_text, fee_rate: feePercent.value / 100, slippage: slippagePercent.value / 100 }),
    })
    await refreshSessions()
  })
}

async function openSession(id: string) {
  await run(async () => { session.value = await api<Session>(`/sessions/${id}`) })
}

async function advance() {
  if (!session.value) return
  await run(async () => {
    session.value = await api<Session>(`/sessions/${session.value!.id}/step`, {
      method: 'POST', body: JSON.stringify({ action: action.value, reason: reason.value }),
    })
    action.value = 'HOLD'
    reason.value = ''
  })
}

function drawCharts() {
  if (!session.value || !priceElement.value || !equityElement.value) return
  priceChart ||= init(priceElement.value)
  equityChart ||= init(equityElement.value)
  const bars = session.value.bars
  const curves = session.value.curves
  priceChart.setOption({
    animation: false,
    grid: { left: 58, right: 20, top: 18, bottom: 36 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: bars.map(bar => bar.date), axisLabel: { hideOverlap: true } },
    yAxis: { scale: true, axisLine: { show: false }, splitLine: { lineStyle: { color: '#e8edf2' } } },
    series: [{ type: 'candlestick', data: bars.map(bar => [bar.open, bar.close, bar.low, bar.high]), itemStyle: { color: '#d2534d', color0: '#218e78', borderColor: '#d2534d', borderColor0: '#218e78' } }],
  })
  equityChart.setOption({
    animation: false,
    grid: { left: 66, right: 20, top: 36, bottom: 36 },
    tooltip: { trigger: 'axis' },
    legend: { top: 2, right: 10, data: ['人工账户', '规则账户', '买入持有'] },
    xAxis: { type: 'category', data: curves.map(point => point.date), axisLabel: { hideOverlap: true } },
    yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: '#e8edf2' } } },
    series: [
      { name: '人工账户', type: 'line', showSymbol: false, data: curves.map(point => point.manual), lineStyle: { width: 2.5, color: '#2758c7' }, itemStyle: { color: '#2758c7' } },
      { name: '规则账户', type: 'line', showSymbol: false, data: curves.map(point => point.rule), lineStyle: { width: 2.5, color: '#e1933c' }, itemStyle: { color: '#e1933c' } },
      { name: '买入持有', type: 'line', showSymbol: false, data: curves.map(point => point.benchmark), lineStyle: { width: 2, type: 'dashed', color: '#718096' }, itemStyle: { color: '#718096' } },
    ],
  })
}

function resizeCharts() { priceChart?.resize(); equityChart?.resize() }
watch(session, async value => {
  if (!value) { priceChart?.dispose(); equityChart?.dispose(); priceChart = null; equityChart = null }
  await nextTick()
  drawCharts()
})
onMounted(() => { refreshSessions().catch(() => { error.value = '无法连接后端服务' }); window.addEventListener('resize', resizeCharts) })
onUnmounted(() => { window.removeEventListener('resize', resizeCharts); priceChart?.dispose(); equityChart?.dispose() })
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand"><div class="brand-mark">T<span>L</span></div><div><strong>Trade Lab</strong><small>交易模型实验室</small></div></div>
      <button class="nav primary-nav" @click="session = null">＋ 新建实验</button>
      <div class="sidebar-title">历史实验 <span>{{ sessions.length }}</span></div>
      <button v-for="item in sessions" :key="item.id" class="nav session-nav" :class="{ selected: session?.id === item.id }" @click="openSession(item.id)">
        <span class="ticker">{{ item.symbol }}</span><span>{{ item.kind === 'etf' ? 'ETF' : '股票' }}</span><small>{{ item.created_at.slice(0, 10) }}</small>
      </button>
      <div class="sidebar-footer">本地研究 · 数据保存在你的电脑</div>
    </aside>

    <main class="main">
      <header class="topbar"><span class="eyebrow">TRADE LAB / RESEARCH WORKSPACE</span><span class="status">● 本地模拟</span></header>
      <div v-if="error" class="error" role="alert">{{ error }}</div>

      <div v-if="!session" class="welcome">
        <div class="welcome-copy"><span class="eyebrow accent">从一个标的开始</span><h1>让每一次交易<br>都成为一次实验。</h1><p>导入真实日线，逐日做出判断。软件同时运行固定规则，帮你比较人工决策、规则执行与买入持有的结果。</p></div>
        <form class="setup-card" @submit.prevent="createSession">
          <div class="card-heading"><span class="step-dot">01</span><div><h2>创建历史回放</h2><p>收盘决策，下一交易日开盘模拟执行</p></div></div>
          <label>证券类型<select v-model="kind"><option value="etf">境内股票 ETF</option><option value="stock">沪深主板股票</option></select></label>
          <label>六位证券代码<input v-model="symbol" inputmode="numeric" maxlength="6" placeholder="例如 510300" required /></label>
          <label>数据来源<select v-model="source"><option value="akshare">AKShare 在线获取</option><option value="csv">本地 CSV 文件</option></select></label>
          <label v-if="source === 'csv'">选择 CSV 文件<input type="file" accept=".csv,text/csv" @change="csvFile = ($event.target as HTMLInputElement).files?.[0] ?? null" /><small>列名：date, open, high, low, close, volume；也支持对应中文列名</small></label>
          <div class="cost-inputs"><label>每笔费用（%）<input v-model.number="feePercent" type="number" min="0" max="1" step="0.01" required /></label><label>滑点（%）<input v-model.number="slippagePercent" type="number" min="0" max="1" step="0.01" required /></label></div>
          <div class="assumption">原始行情暂未处理分红送股。实验最多取最近 260 个交易日。</div>
          <button class="button solid" type="submit" :disabled="busy">{{ busy ? '正在准备数据…' : '开始实验 →' }}</button>
        </form>
      </div>

      <div v-else class="workspace">
        <div class="page-heading"><div><span class="eyebrow accent">历史回放 · {{ session.source === 'csv' ? 'CSV 快照' : 'AKShare 快照' }}</span><h1>{{ session.symbol }} <span>{{ session.kind === 'etf' ? '境内股票 ETF' : '沪深主板股票' }}</span></h1><p>当前可见：{{ session.date }} 收盘 · 回放进度 {{ session.step }} / {{ session.total_steps }} 次决策</p></div><span class="pill">{{ session.finished ? '回放完成' : '实验进行中' }}</span></div>
        <div class="metrics"><div class="metric"><span>人工账户</span><strong>{{ money(session.accounts.manual.equity) }}</strong><small>{{ session.accounts.manual.shares }} 份 / 股</small></div><div class="metric"><span>规则账户</span><strong>{{ money(session.accounts.rule.equity) }}</strong><small>20 日均线趋势</small></div><div class="metric"><span>买入持有</span><strong>{{ money(session.accounts.benchmark.equity) }}</strong><small>同标的基准</small></div><div class="metric comparison"><span>人工 − 规则</span><strong :class="difference < 0 ? 'negative' : 'positive'">{{ money(difference) }}</strong><small>相同资金与成交假设</small></div></div>
        <div class="content-grid"><section class="panel chart-panel"><div class="panel-head"><div><span class="eyebrow">MARKET</span><h2>可见行情</h2></div><small>未来 K 线未展示</small></div><div ref="priceElement" class="chart price-chart"></div></section>
          <section class="panel decision-panel"><div class="panel-head"><div><span class="eyebrow">DECISION</span><h2>今日决策</h2></div></div><div class="signal"><span>规则账户当前信号</span><strong :class="session.signal === 'BUY' ? 'positive' : 'negative'">{{ session.signal === 'BUY' ? '买入 / 持有' : '卖出 / 空仓' }}</strong><small>20 日均线；下一交易日开盘执行</small></div><form @submit.prevent="advance"><div class="choice-list"><label v-for="option in (['BUY', 'SELL', 'HOLD'] as Action[])" :key="option" :class="{ active: action === option }"><input v-model="action" type="radio" :value="option" />{{ option === 'BUY' ? '买入' : option === 'SELL' ? '卖出' : '不操作' }}</label></div><label class="reason-label">决策理由<textarea v-model="reason" rows="3" maxlength="500" placeholder="为什么这样决定？买入和卖出时必填。"></textarea></label><button class="button solid" type="submit" :disabled="busy || session.finished || (action !== 'HOLD' && !reason.trim())">{{ session.finished ? '回放已结束' : busy ? '计算中…' : '保存决策并进入下一日 →' }}</button></form><p class="note">成交受现金、持仓、100 份 / 股整数手和成交量约束。买卖账户使用同一套规则。</p></section></div>
        <div class="content-grid bottom-grid"><section class="panel chart-panel"><div class="panel-head"><div><span class="eyebrow">PERFORMANCE</span><h2>账户净值对照</h2></div><small>包含所设费用与滑点</small></div><div ref="equityElement" class="chart equity-chart"></div></section><section class="panel history-panel"><div class="panel-head"><div><span class="eyebrow">JOURNAL</span><h2>人工决策记录</h2></div><small>{{ session.decisions.length }} 次</small></div><div v-if="session.decisions.length" class="history-list"><div v-for="item in [...session.decisions].reverse().slice(0, 8)" :key="item.date" class="history-item"><div><strong>{{ item.date }}</strong><span>{{ item.action === 'BUY' ? '买入' : item.action === 'SELL' ? '卖出' : '不操作' }}</span></div><p>{{ item.reason || '未填写理由' }}</p></div></div><p v-else class="empty">还没有决策。写下第一笔交易的理由，开始积累证据。</p></section></div>
        <p class="disclaimer">当前版本使用未经复权的日线快照，尚未计入分红送股、真实涨跌停排队及停牌后的复杂成交情形；结果仅用于研究流程验证，不能视作可靠历史收益。</p>
      </div>
    </main>
  </div>
</template>
