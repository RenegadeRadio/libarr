<script setup>
import { onMounted, ref } from 'vue'
import api from '../api.js'

const health = ref(null)
const me = ref(null)
const error = ref(null)

onMounted(async () => {
  try {
    health.value = await api('/health')
  } catch (e) {
    error.value = String(e)
  }
  try {
    me.value = await api('/auth/me')
  } catch {
    me.value = null
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
      <li v-if="me">
        Signed in as <strong>{{ me.username }}</strong> ({{ me.role }})
      </li>
    </ul>
    <p v-else class="muted">Checking backend…</p>
  </section>
</template>
