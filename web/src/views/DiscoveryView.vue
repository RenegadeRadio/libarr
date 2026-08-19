<script setup>
import { onMounted, ref } from 'vue'
import api from '../api.js'

const genre = ref('science fiction')
const yearMin = ref('')
const language = ref('')
const works = ref([])
const lists = ref([])
const searched = ref(false)
const error = ref('')

onMounted(async () => {
  lists.value = await api('/discovery-lists')
})

async function run() {
  error.value = ''
  const params = new URLSearchParams()
  if (genre.value) params.set('genre', genre.value)
  if (yearMin.value) params.set('year_min', yearMin.value)
  if (language.value) params.set('language', language.value)
  try {
    works.value = await api(`/discovery?${params.toString()}`)
    searched.value = true
  } catch (e) {
    error.value = String(e)
  }
}

async function addAll() {
  if (works.value.length === 0) return
  const result = await api('/discovery/import', {
    method: 'POST',
    body: JSON.stringify({ works: works.value, monitored: true }),
  })
  alert(`Added ${result.added} work(s) to the library`)
  works.value = []
}

async function saveList() {
  await api('/discovery-lists', {
    method: 'POST',
    body: JSON.stringify({
      name: `Genre: ${genre.value}`,
      query: { genre: genre.value, year_min: yearMin.value || null, language: language.value || null },
      schedule_days: 7,
      max_per_run: 10,
      auto_monitor: true,
    }),
  })
  lists.value = await api('/discovery-lists')
  alert('Saved as a weekly discovery list')
}

async function evaluate() {
  const result = await api('/system/discovery-lists', { method: 'POST' })
  alert(`Lists evaluated: ${JSON.stringify(result.lists)}`)
  lists.value = await api('/discovery-lists')
}
</script>

<template>
  <section class="card">
    <h1>Discover</h1>
    <p class="muted">
      Find books by genre or keywords and add them to your library — the
      *Arr import-list pattern over Open Library + Google Books.
    </p>
    <form class="search-form" @submit.prevent="run">
      <input v-model="genre" type="text" placeholder="Genre (e.g. science fiction)" />
      <input v-model="yearMin" type="number" placeholder="Year from" class="year" />
      <input v-model="language" type="text" placeholder="Language (eng)" class="lang" />
      <button class="btn" type="submit">Preview</button>
    </form>
    <p v-if="error" class="error">{{ error }}</p>

    <template v-if="searched">
      <p class="muted">{{ works.length }} work(s) found — not yet in your library.</p>
      <ul class="works">
        <li v-for="(w, i) in works" :key="i">
          <strong>{{ w.title }}</strong>
          <span class="muted"> — {{ w.author || 'Unknown author' }}{{ w.year ? ` · ${w.year}` : '' }}</span>
        </li>
      </ul>
      <button class="btn" :disabled="works.length === 0" @click="addAll">
        Add {{ works.length }} to library (monitored)
      </button>
      <button class="btn ghost" @click="saveList">Save as weekly list</button>
    </template>

    <h2>Saved lists</h2>
    <ul class="muted">
      <li v-for="l in lists" :key="l.id">
        {{ l.name }} — every {{ l.schedule_days }}d, up to {{ l.max_per_run }}
        <span v-if="l.last_run_at" class="dim">(last run {{ l.last_run_at.slice(0, 10) }})</span>
      </li>
    </ul>
    <button v-if="lists.length" class="btn ghost" @click="evaluate">Run lists now</button>
  </section>
</template>

<style scoped>
.works {
  list-style: none;
  padding: 0;
  line-height: 1.9;
}
.ghost {
  background: transparent;
  color: var(--accent);
  border: 1px solid var(--accent);
  margin-left: 8px;
}
.dim {
  opacity: 0.6;
}
</style>
