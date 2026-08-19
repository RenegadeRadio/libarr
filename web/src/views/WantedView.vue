<script setup>
import { onMounted, ref } from 'vue'
import api from '../api.js'

const missing = ref([])
const cutoff = ref([])
const history = ref([])
const searching = ref(new Set())

onMounted(async () => {
  ;[missing.value, cutoff.value, history.value] = await Promise.all([
    api('/wanted/missing'),
    api('/wanted/cutoff'),
    api('/history?limit=20'),
  ])
})

async function searchNow(book) {
  searching.value.add(book.id)
  try {
    const result = await api(`/books/${book.id}/search`, { method: 'POST' })
    history.value = await api('/history?limit=20')
    alert(
      result.queued
        ? `Queued: ${result.winner}`
        : result.already_queued
          ? 'Already queued'
          : 'No release found',
    )
  } finally {
    searching.value.delete(book.id)
  }
}

function kindLabel(kind) {
  return { grab: '⬇ grabbed', import: '📥 imported', upgrade: '⬆ upgraded', fail: '❌ failed', discovery: '✨ discovered' }[kind] || kind
}
</script>

<template>
  <section class="card">
    <h1>Wanted</h1>
    <h2>Missing</h2>
    <p v-if="missing.length === 0" class="muted">Nothing missing — every monitored book has a file.</p>
    <table v-else class="wanted">
      <tr v-for="b in missing" :key="b.id">
        <td>{{ b.title }}</td>
        <td class="muted">{{ b.author_name }} · {{ b.year }}</td>
        <td>
          <button class="btn btn-sm" :disabled="searching.has(b.id)" @click="searchNow(b)">
            {{ searching.has(b.id) ? 'Searching…' : 'Search' }}
          </button>
        </td>
      </tr>
    </table>

    <h2>Cutoff unmet</h2>
    <p v-if="cutoff.length === 0" class="muted">All owned books meet the quality cutoff.</p>
    <table v-else class="wanted">
      <tr v-for="b in cutoff" :key="b.id">
        <td>{{ b.title }}</td>
        <td class="muted">{{ b.author_name }} · {{ b.year }} · {{ b.formats.join(', ') }}</td>
        <td>
          <button class="btn btn-sm" :disabled="searching.has(b.id)" @click="searchNow(b)">
            {{ searching.has(b.id) ? 'Searching…' : 'Upgrade' }}
          </button>
        </td>
      </tr>
    </table>

    <h2>History</h2>
    <ul class="muted history">
      <li v-for="e in history" :key="e.id">
        <span>{{ kindLabel(e.kind) }}</span> {{ e.title }}
        <span v-if="e.details" class="dim">— {{ e.details }}</span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.wanted {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 18px;
}
.wanted td {
  padding: 6px 10px 6px 0;
  border-bottom: 1px solid var(--border);
}
.btn-sm {
  margin: 0;
  padding: 4px 10px;
  font-size: 12px;
}
.history {
  list-style: none;
  padding: 0;
  line-height: 1.9;
}
.dim {
  opacity: 0.6;
}
</style>
