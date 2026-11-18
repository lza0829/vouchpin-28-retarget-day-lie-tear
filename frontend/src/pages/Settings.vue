<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'
const day = ref('')
const msg = ref('')
const err = ref('')
async function load() {
  try {
    const r = await api.getDay()
    day.value = r.business_day
  } catch (e) { err.value = e.message }
}
async function save() {
  msg.value = ''; err.value = ''
  try {
    const r = await api.setDay(day.value)
    msg.value = `业务日已设为 ${r.business_day}`
  } catch (e) { err.value = e.message }
}
onMounted(load)
</script>
<template>
  <div class="panel">
    <div class="row">
      <label>业务日 <input v-model="day" placeholder="YYYY-MM-DD" /></label>
      <button type="button" @click="save">保存</button>
    </div>
    <p class="msg" v-if="msg">{{ msg }}</p>
    <p class="msg err" v-if="err">{{ err }}</p>
  </div>
</template>
