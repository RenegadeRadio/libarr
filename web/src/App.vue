<script setup>
import { RouterLink, RouterView, useRoute } from 'vue-router'

const route = useRoute()

const nav = [
  { to: '/', label: 'Library' },
  { to: '/search', label: 'Search' },
  { to: '/discover', label: 'Discover' },
  { to: '/request', label: 'Request' },
  { to: '/authors', label: 'Authors' },
  { to: '/wanted', label: 'Wanted' },
  { to: '/system', label: 'System' },
]
</script>

<template>
  <div class="shell">
    <header v-if="route.path !== '/login'" class="topbar">
      <div class="brand">
        <span class="logo">📚</span>
        <span class="brand-name">Libarr</span>
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
