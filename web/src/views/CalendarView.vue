<script setup>
import { onMounted, ref } from 'vue'
import api from '../api.js'

const events = ref([])
const loading = ref(true)

onMounted(async () => {
  events.value = await api('/calendar')
  loading.value = false
})

const byYear = () =>
  events.value.reduce((groups, e) => {
    ;(groups[e.year] ||= []).push(e)
    return groups
  }, {})
</script>

<template>
  <section class="card">
    <h1>Calendar</h1>
    <p class="muted">
      New and upcoming releases for monitored authors (Open Library gives year
      granularity, so events are dated at their release year).
    </p>
    <p v-if="loading" class="muted">Loading…</p>
    <p v-else-if="events.length === 0" class="muted">
      Nothing upcoming — monitor some authors and their newest works will show here.
    </p>
    <template v-else>
      <div v-for="(items, year) in byYear()" :key="year" class="year-block">
        <h2>{{ year }}</h2>
        <ul class="events">
          <li v-for="(e, i) in items" :key="i">
            <strong>{{ e.title }}</strong>
            <span class="muted"> — {{ e.author }}</span>
          </li>
        </ul>
      </div>
    </template>
  </section>
</template>

<style scoped>
.events {
  list-style: none;
  padding: 0;
  line-height: 1.9;
}
.year-block {
  margin-bottom: 14px;
}
.year-block h2 {
  color: var(--accent);
  font-size: 15px;
  margin: 0 0 4px;
}
</style>
