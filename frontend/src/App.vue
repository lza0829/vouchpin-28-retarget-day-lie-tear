<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const chips = [
  { to: '/', label: '总览', tip: '今日票根' },
  { to: '/events', label: '券事件', tip: '发放·核销·作废' },
  { to: '/redeem', label: '核销钉扎', tip: '事实→批次' },
  { to: '/batches', label: '钉扎批次', tip: '已钉集合' },
  { to: '/settings', label: '设置', tip: '业务日' },
]
function on(to) {
  if (to === '/') return route.path === '/'
  return route.path.startsWith(to)
}
const cur = computed(() => chips.find((c) => on(c.to)) || chips[0])
</script>

<template>
  <div class="shell">
    <header class="mast">
      <router-link class="brand" to="/" aria-label="Vouchpin 券钉簿">
        <span class="brand-mark" aria-hidden="true">✂</span>
        <span class="brand-text">
          <strong>Vouchpin</strong>
          <em>券钉簿</em>
        </span>
      </router-link>
      <p class="brand-tag">券事件入湖 · 核销事实钉扎 · 批次互证</p>
      <nav class="chips" aria-label="工位">
        <router-link
          v-for="c in chips"
          :key="c.to"
          :to="c.to"
          class="chip"
          :class="{ on: on(c.to) }"
        >
          <span>{{ c.label }}</span>
          <small>{{ c.tip }}</small>
        </router-link>
      </nav>
    </header>

    <section class="desk">
      <div class="desk-head">
        <h1>{{ cur.label }}</h1>
        <p>{{ cur.tip }}</p>
      </div>
      <main class="main">
        <router-view />
      </main>
    </section>
  </div>
</template>
