<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const err = ref('')
const notice = ref('')
const snapshot = ref<any>(null)
const editDist = ref<Record<number, number>>({})
function fmt(e: any) {
  try { return JSON.parse(e.message).detail } catch { return e.message || '请求失败' }
}
async function load() {
  rows.value = await api('/halls')
  for (const r of rows.value) {
    if (!(r.id in editDist.value)) editDist.value[r.id] = r.min_manhattan
  }
}
async function seal(id: number) {
  err.value = ''; notice.value = ''
  try {
    await api(`/halls/${id}/seal`, { method: 'POST' })
    notice.value = '已封场：写入口闸落下，快照入仓，改距将只进待生效配置'
    await load()
  } catch (e: any) { err.value = fmt(e) }
}
async function unseal(id: number) {
  err.value = ''; notice.value = ''
  try {
    const r = await api(`/halls/${id}/unseal`, { method: 'POST' })
    notice.value = `已解封：待生效配置生效，当前最小间距 ${r.min_manhattan}，可以重新排座`
    await load()
  } catch (e: any) { err.value = fmt(e) }
}
async function saveDist(id: number) {
  err.value = ''; notice.value = ''
  try {
    const r = await api(`/halls/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ min_manhattan: Number(editDist.value[id]) }),
    })
    notice.value = r.pending
      ? `考室封场中：最小间距 ${r.pending_min_manhattan} 已写入待生效配置，解封后生效`
      : `最小间距已更新为 ${r.min_manhattan}`
    await load()
  } catch (e: any) { err.value = fmt(e) }
}
async function showSnapshot(id: number) {
  err.value = ''; snapshot.value = null
  try { snapshot.value = await api(`/halls/${id}/snapshot`) } catch (e: any) { err.value = fmt(e) }
}
onMounted(load)
</script>
<template>
  <h1>考室</h1>
  <p class="sub">考室网格与最小曼哈顿间距 · 封场后禁写，解封才可写</p>
  <p v-if="err" class="badge badge-bad">{{ err }}</p>
  <p v-if="notice" class="badge badge-ok">{{ notice }}</p>
  <div class="card">
    <table>
      <thead>
        <tr><th>编码</th><th>名称</th><th>行</th><th>列</th><th>生效间距</th><th>待生效</th><th>状态</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td>{{ r.code }}</td>
          <td>{{ r.name }}</td>
          <td>{{ r.rows }}</td>
          <td>{{ r.cols }}</td>
          <td>{{ r.min_manhattan }}</td>
          <td>
            <span v-if="r.pending_min_manhattan != null && r.pending_min_manhattan !== r.min_manhattan"
                  class="badge badge-warn">{{ r.pending_min_manhattan }}（解封生效）</span>
            <span v-else class="muted">—</span>
          </td>
          <td>
            <span v-if="r.sealed" class="badge badge-bad">已封场</span>
            <span v-else class="badge badge-ok">可排座</span>
          </td>
          <td>
            <input
              v-model.number="editDist[r.id]" type="number" min="1" max="50"
              style="width:3.2rem" :aria-label="'最小间距-' + r.code"
            >
            <button class="btn" style="padding:0.2rem 0.5rem" @click="saveDist(r.id)">改距</button>
            <button v-if="!r.sealed" class="btn" style="padding:0.2rem 0.5rem" @click="seal(r.id)">封场</button>
            <button v-else class="btn" style="padding:0.2rem 0.5rem" @click="unseal(r.id)">解封</button>
            <button class="btn" style="padding:0.2rem 0.5rem" @click="showSnapshot(r.id)">快照</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <div v-if="snapshot" class="card">
    <h3>封场快照 #{{ snapshot.snapshot_id }}（只读）</h3>
    <p class="muted">
      封场时间 {{ snapshot.sealed_at }} · 封场当时最小间距 {{ snapshot.min_manhattan }}
    </p>
    <p>
      已排座 {{ snapshot.stats?.seated }} · 未排上 {{ snapshot.stats?.unplaced }} ·
      违规 {{ snapshot.stats?.violations }} · 容量 {{ snapshot.stats?.capacity }}
    </p>
    <p class="muted">快照仓内容保持封场当时的字，解封与再排均不改写。</p>
  </div>
</template>
