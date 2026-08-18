<script setup>
import { RouterLink, RouterView } from 'vue-router'

const nav = [
  { to: '/', label: 'Library' },
  { to: '/authors', label: 'Authors' },
  { to: '/wanted', label: 'Wanted' },
  { to: '/system', label: 'System' },
]
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <span class="logo">📚</span>
        <span class="brand-name">Libarr</span>
        <span class="tag">v0.1.0 — Phase 0 scaffold</span>
      </div>
      <nav class="nav">
        <RouterLink v-for="item in nav" :key="item.to" :to="item.to" class="nav-link">
          {{ item.label }}
        </RouterLink>
      </nav>
    </header>
    <main class="content">
      <RouterView />
    </main>
  </div>
</template>
