<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const rows = ref([])
const camps = ref([])
const form = ref({ event_type: 'redeem', coupon_code: '', campaign_code: 'NEW10', amount: '', business_day: '', occurred_at: '' })
const msg = ref('')
const err = ref('')

async function load() {
  err.value = ''
  try {
    camps.value = await api.campaigns()
    rows.value = await api.events()
    if (!form.value.campaign_code && camps.value[0]) form.value.campaign_code = camps.value[0].code
  } catch (e) { err.value = e.message }
}
async function submit() {
  msg.value = ''; err.value = ''
  try {
    const body = { ...form.value }
    if (body.amount === '') delete body.amount
    else body.amount = Number(body.amount)
    if (!body.business_day) delete body.business_day
    if (!body.occurred_at) delete body.occurred_at
    const r = await api.addEvent(body)
    msg.value = `已写入事件 #${r.event_id}` + (r.fact_id ? ` / 事实 #${r.fact_id}` : '')
      + (r.retargeted
        ? ` · 原目标日 ${r.retarget_from} 已钉扎，改挂到 ${r.business_day}（occurred_at 保留 ${r.occurred_at}）`
        : ` · 归属业务日 ${r.business_day}`)
    form.value.coupon_code = ''
    await load()
  } catch (e) { err.value = e.message }
}
onMounted(load)
</script>
<template>
  <div class="panel">
    <div class="row">
      <label>类型
        <select v-model="form.event_type">
          <option value="issue">发放</option>
          <option value="redeem">核销</option>
          <option value="void">作废</option>
        </select>
      </label>
      <label>券码 <input v-model="form.coupon_code" placeholder="C-2xxx" /></label>
      <label>活动
        <select v-model="form.campaign_code">
          <option v-for="c in camps" :key="c.code" :value="c.code">{{ c.code }} · {{ c.title }}</option>
        </select>
      </label>
      <label>金额 <input v-model="form.amount" placeholder="可空=面额" /></label>
      <label>业务日 <input v-model="form.business_day" placeholder="可空=按发生时刻" /></label>
      <label>发生时刻 <input v-model="form.occurred_at" placeholder="可空=现在" /></label>
      <button type="button" @click="submit">写入事件</button>
      <button type="button" class="ghost" @click="load">刷新</button>
    </div>
    <p class="msg">核销目标日已钉扎时，服务端改挂到最早开放日并打 retarget_from；无开放日则失败不写。</p>
    <p class="msg" v-if="msg">{{ msg }}</p>
    <p class="msg err" v-if="err">{{ err }}</p>
  </div>
  <div class="panel">
    <table>
      <thead><tr><th>ID</th><th>类型</th><th>券码</th><th>活动</th><th>金额</th><th>业务日</th><th>改挂自</th><th>时刻</th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td>{{ r.id }}</td>
          <td><span class="tag" :class="{ warn: r.event_type==='redeem' }">{{ r.event_type }}</span></td>
          <td>{{ r.coupon_code }}</td>
          <td>{{ r.campaign_code }}</td>
          <td>{{ r.amount }}</td>
          <td>{{ r.business_day }}</td>
          <td><span class="tag warn" v-if="r.retarget_from">{{ r.retarget_from }}</span><span v-else>—</span></td>
          <td>{{ r.occurred_at }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
