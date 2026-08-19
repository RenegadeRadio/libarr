import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'

import App from './App.vue'
import './style.css'
import AuthorsView from './views/AuthorsView.vue'
import CalendarView from './views/CalendarView.vue'
import DiscoveryView from './views/DiscoveryView.vue'
import LibraryView from './views/LibraryView.vue'
import LoginView from './views/LoginView.vue'
import RequestView from './views/RequestView.vue'
import SearchView from './views/SearchView.vue'
import SystemView from './views/SystemView.vue'
import WantedView from './views/WantedView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: LibraryView, meta: { title: 'Library' } },
    { path: '/search', component: SearchView, meta: { title: 'Search' } },
    { path: '/discover', component: DiscoveryView, meta: { title: 'Discover' } },
    { path: '/request', component: RequestView, meta: { title: 'Request' } },
    { path: '/calendar', component: CalendarView, meta: { title: 'Calendar' } },
    { path: '/authors', component: AuthorsView, meta: { title: 'Authors' } },
    { path: '/wanted', component: WantedView, meta: { title: 'Wanted' } },
    { path: '/system', component: SystemView, meta: { title: 'System' } },
    { path: '/login', component: LoginView, meta: { title: 'Login' } },
  ],
})

// Route guard: every page except /login requires a valid session.
router.beforeEach(async (to) => {
  if (to.path === '/login') return true
  try {
    const resp = await fetch('/api/v1/auth/me')
    if (resp.ok) return true
  } catch {
    /* network error → fall through to login */
  }
  return '/login'
})

createApp(App).use(router).mount('#app')
