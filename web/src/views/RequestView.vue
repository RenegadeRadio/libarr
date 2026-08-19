<script setup>
import { ref } from 'vue'
import api from '../api.js'

const title = ref('')
const author = ref('')
const isbn = ref('')
const busy = ref(false)
const result = ref(null)
const error = ref('')

async function submit() {
  busy.value = true
  error.value = ''
  result.value = null
  try {
    result.value = await api('/requests', {
      method: 'POST',
      body: JSON.stringify({
        title: title.value,
        author: author.value || null,
        isbn: isbn.value || null,
      }),
    })
  } catch (e) {
    error.value = String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="card">
    <h1>Request a book</h1>
    <p class="muted">
      The Overseerr flow: request → Libarr adds it (monitored) → searches every
      indexer → queues the best release. Optionally resolve by ISBN for exact
      metadata.
    </p>
    <form class="search-form" @submit.prevent="submit">
      <input v-model="title" type="text" placeholder="Title (required)" required />
      <input v-model="author" type="text" placeholder="Author" class="lang" />
      <input v-model="isbn" type="text" placeholder="ISBN-13 (optional)" class="lang" />
      <button class="btn" type="submit" :disabled="busy || !title">
        {{ busy ? 'Requesting…' : 'Request' }}
      </button>
    </form>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="result && !result.manual" class="ok">
      ✅ {{ result.title }} added{{ result.queued ? ` — queued: ${result.winner}` : ' — no release found yet (wanted list will keep watching)' }}
    </p>
    <div v-if="result && result.manual" class="card manual">
      <p class="ok">✅ {{ result.title }} added — automated indexers found nothing, but a manual source exists.</p>
      <a class="btn" :href="result.download_url" target="_blank" rel="noopener">
        Download manually (Anna's Archive)
      </a>
      <p class="muted">Opens in your browser; the queue keeps it bookmarked until you're done.</p>
    </div>
  </section>
</template>

<style scoped>
.ok {
  color: var(--ok);
}
</style>
