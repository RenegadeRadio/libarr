<script setup>
import { onMounted, ref } from 'vue'
import api from '../api.js'

const health = ref(null)
const error = ref(null)

onMounted(async () => {
  try {
    health.value = await api('/health')
  } catch (e) {
    error.value = String(e)
  }
})
</script>

<template>
  <section class="card">
    <h1>System</h1>
    <p v-if="error" class="muted">Backend unreachable: {{ error }}</p>
    <ul v-else-if="health" class="muted" style="line-height: 1.8">
      <li>Backend: <span class="status-ok">{{ health.status }}</span></li>
      <li>Version: {{ health.version }}</li>
    </ul>
    <p v-else class="muted">Checking backend…</p>
  </section>
</template>
