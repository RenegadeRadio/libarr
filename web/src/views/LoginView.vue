<script setup>
import { onMounted, ref } from 'vue'
import api from '../api.js'

const needed = ref(null)
const username = ref('')
const password = ref('')
const error = ref('')

onMounted(async () => {
  try {
    needed.value = (await api('/auth/bootstrap')).needed
  } catch {
    needed.value = true
  }
})

async function submit() {
  error.value = ''
  try {
    if (needed.value) {
      await api('/auth/bootstrap', {
        method: 'POST',
        body: JSON.stringify({ username: username.value, password: password.value }),
      })
    }
    await api('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username: username.value, password: password.value }),
    })
    window.location.href = '/'
  } catch (e) {
    error.value = String(e)
  }
}
</script>

<template>
  <section class="card login-card">
    <h1>📚 Libarr</h1>
    <p class="muted">
      {{ needed ? 'First run — create the admin account.' : 'Sign in to your library.' }}
    </p>
    <form @submit.prevent="submit">
      <label>
        Username
        <input v-model="username" type="text" autocomplete="username" required />
      </label>
      <label>
        Password
        <input v-model="password" type="password" autocomplete="current-password" required />
      </label>
      <button class="btn" type="submit">{{ needed ? 'Create account' : 'Sign in' }}</button>
      <p v-if="error" class="error">{{ error }}</p>
    </form>
  </section>
</template>
