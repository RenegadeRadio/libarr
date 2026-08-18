import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'

import App from './App.vue'
import './style.css'
import AuthorsView from './views/AuthorsView.vue'
import LibraryView from './views/LibraryView.vue'
import SystemView from './views/SystemView.vue'
import WantedView from './views/WantedView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: LibraryView, meta: { title: 'Library' } },
    { path: '/authors', component: AuthorsView, meta: { title: 'Authors' } },
    { path: '/wanted', component: WantedView, meta: { title: 'Wanted' } },
    { path: '/system', component: SystemView, meta: { title: 'System' } },
  ],
})

createApp(App).use(router).mount('#app')
