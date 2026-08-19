<script setup>
import { ref } from 'vue'
import api from '../api.js'

const messages = ref([])
const input = ref('')
const busy = ref(false)
const requested = ref(new Set())

async function send() {
  const text = input.value.trim()
  if (!text || busy.value) return
  messages.value.push({ role: 'user', text })
  input.value = ''
  busy.value = true
  try {
    const res = await api('/chat', { method: 'POST', body: JSON.stringify({ message: text }) })
    messages.value.push({ role: 'bot', text: res.reply, suggestions: res.suggestions })
  } catch (e) {
    messages.value.push({ role: 'bot', text: `Something went wrong: ${e}` })
  } finally {
    busy.value = false
  }
}

async function requestBook(s) {
  const key = `${s.title}|${s.author || ''}`
  if (requested.value.has(key)) return
  try {
    const res = await api('/requests', {
      method: 'POST',
      body: JSON.stringify({ title: s.title, author: s.author || null }),
    })
    requested.value.add(key)
    s.requested = res.queued ? 'queued ✓' : 'added (watching wanted list)'
  } catch (e) {
    s.requested = `failed: ${e}`
  }
}
</script>

<template>
  <section class="card chat">
    <h1>Book Assistant</h1>
    <p class="muted">
      Ask in plain language — "books similar to Rubicon", "fantasy from the
      1980s", "find me books by Ursula K. Le Guin", "request Dune". Suggestions
      are live discovery results; request one and the pipeline takes over.
    </p>
    <div class="thread">
      <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
        <div class="bubble">{{ m.text }}</div>
        <div v-if="m.suggestions?.length" class="suggestions">
          <div v-for="(s, j) in m.suggestions" :key="j" class="suggestion">
            <div class="sug-title">
              <strong>{{ s.title }}</strong>
              <span class="muted"> — {{ s.author }}{{ s.year ? ` (${s.year})` : '' }}</span>
            </div>
            <button class="btn small" @click="requestBook(s)" :disabled="s.requested">
              {{ s.requested || 'Request' }}
            </button>
          </div>
        </div>
      </div>
    </div>
    <form class="search-form" @submit.prevent="send">
      <input v-model="input" type="text" placeholder="e.g. i am looking for books similar to rubicon…" />
      <button class="btn" type="submit" :disabled="busy || !input.trim()">
        {{ busy ? '…' : 'Ask' }}
      </button>
    </form>
  </section>
</template>

<style scoped>
.thread {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 14px 0;
}
.msg {
  max-width: 85%;
}
.msg.user {
  align-self: flex-end;
}
.msg.bot {
  align-self: flex-start;
}
.bubble {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 12px;
  white-space: pre-wrap;
}
.msg.user .bubble {
  background: var(--accent-dim, rgba(0, 0, 0, 0.25));
}
.suggestions {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.suggestion {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
}
.sug-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
