<script setup>
import { onMounted, ref } from 'vue'
import api from '../api.js'

const q = ref('')
const genre = ref('')
const yearMin = ref('')
const yearMax = ref('')
const language = ref('')
const results = ref([])
const facets = ref([])
const total = ref(0)
const searched = ref(false)
const error = ref('')

onMounted(() => run())

async function run() {
  error.value = ''
  const params = new URLSearchParams()
  if (q.value) params.set('q', q.value)
  if (genre.value) params.set('genre', genre.value)
  if (yearMin.value) params.set('year_min', yearMin.value)
  if (yearMax.value) params.set('year_max', yearMax.value)
  if (language.value) params.set('language', language.value)
  try {
    const body = await api(`/search?${params.toString()}`)
    results.value = body.results
    facets.value = body.facets
    total.value = body.total
    searched.value = true
  } catch (e) {
    error.value = String(e)
  }
}

function pickGenre(slug) {
  genre.value = slug
  run()
}
</script>

<template>
  <section class="card">
    <h1>Search</h1>
    <form class="search-form" @submit.prevent="run">
      <input v-model="q" type="text" placeholder="Keywords (title, author, description…)" />
      <input v-model="yearMin" type="number" placeholder="Year from" class="year" />
      <input v-model="yearMax" type="number" placeholder="Year to" class="year" />
      <input v-model="language" type="text" placeholder="Language (eng)" class="lang" />
      <button class="btn" type="submit">Search</button>
    </form>
    <p v-if="error" class="error">{{ error }}</p>

    <div v-if="searched && total === 0" class="muted">No books match those filters.</div>

    <template v-else-if="searched">
      <p class="muted">{{ total }} book(s) — refine by genre:</p>
      <div class="tags">
        <button
          v-for="f in facets"
          :key="f.slug"
          class="tag tag-btn"
          :class="{ active: genre === f.slug }"
          @click="pickGenre(f.slug)"
        >
          {{ f.name }} ({{ f.count }})
        </button>
      </div>
      <div class="grid results">
        <div v-for="b in results" :key="b.id" class="book-card">
          <img
            class="cover"
            :src="`/api/v1/covers/${b.id}`"
            :alt="`Cover of ${b.title}`"
            @error="(e) => (e.target.style.visibility = 'hidden')"
          />
          <div class="b-title">{{ b.title }}</div>
          <div class="muted b-meta">
            {{ b.author_name }}{{ b.year ? ` · ${b.year}` : '' }}
          </div>
          <a class="download" :href="`/api/v1/books/${b.id}/file`">⬇</a>
        </div>
      </div>
    </template>
  </section>
</template>
