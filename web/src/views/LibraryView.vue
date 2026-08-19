<script setup>
import { onMounted, ref } from 'vue'
import api from '../api.js'

const books = ref([])
const selected = ref(null)
const loading = ref(true)

onMounted(async () => {
  books.value = await api('/books?limit=200')
  loading.value = false
})

async function openBook(book) {
  selected.value = await api(`/books/${book.id}`)
}

function hasFile(book) {
  return book.editions.some((e) => e.files.length > 0)
}
</script>

<template>
  <div v-if="loading" class="muted">Loading library…</div>
  <div v-else-if="books.length === 0" class="card">
    <h1>Library</h1>
    <p class="muted">
      No books yet. Drop EPUBs into the library folder and run the scan (Phase 2
      adds the scan trigger to this UI).
    </p>
  </div>
  <div v-else class="layout">
    <div class="grid">
      <div v-for="b in books" :key="b.id" class="book-card" @click="openBook(b)">
        <img
          class="cover"
          :src="`/api/v1/covers/${b.id}`"
          :alt="`Cover of ${b.title}`"
          @error="(e) => (e.target.style.visibility = 'hidden')"
        />
        <div class="b-title">{{ b.title }}</div>
        <div class="muted b-meta">{{ b.author_name }}{{ b.year ? ` · ${b.year}` : '' }}</div>
      </div>
    </div>
    <aside v-if="selected" class="card detail">
      <h2>{{ selected.title }}</h2>
      <p class="muted">
        {{ selected.author_name }} · {{ selected.year }} · {{ selected.language }}
      </p>
      <p v-if="selected.description">{{ selected.description }}</p>
      <div v-if="selected.subjects.length" class="tags">
        <span v-for="s in selected.subjects" :key="s" class="tag">{{ s }}</span>
      </div>
      <p class="muted">Formats: {{ selected.formats.join(', ') || '—' }}</p>
      <a
        v-if="hasFile(selected)"
        class="btn"
        :href="`/api/v1/books/${selected.id}/file`"
        >Download</a
      >
    </aside>
  </div>
</template>
