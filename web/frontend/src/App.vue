<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import AppTopbar from './components/AppTopbar.vue'
import DocumentsPage from './pages/DocumentsPage.vue'
import KnowledgeGraphPage from './pages/KnowledgeGraphPage.vue'
import LoginPage from './pages/LoginPage.vue'
import RetrievalPage from './pages/RetrievalPage.vue'
import SettingsPage from './pages/SettingsPage.vue'
import UsersPage from './pages/UsersPage.vue'
import { clearStoredToken, getCurrentUser, getStoredToken, logout, storeToken } from './lib/api'

const allPages = [
  { id: 'documents', label: '文档' },
  { id: 'knowledge-graph', label: '知识图谱' },
  { id: 'retrieval', label: '书脉问答' },
  { id: 'users', label: '用户', adminOnly: true },
  { id: 'settings', label: '设置' },
]

const pageComponents = {
  documents: DocumentsPage,
  'knowledge-graph': KnowledgeGraphPage,
  retrieval: RetrievalPage,
  users: UsersPage,
  settings: SettingsPage,
}

const currentPageId = ref('documents')
const currentPageComponent = computed(() => pageComponents[currentPageId.value] ?? DocumentsPage)
const token = ref(getStoredToken())
const currentUser = ref(null)
const isCheckingSession = ref(true)

const isAuthenticated = computed(() => Boolean(currentUser.value))
const pages = computed(() =>
  allPages.filter((page) => !page.adminOnly || currentUser.value?.role === 'admin'),
)

async function loadCurrentUser() {
  try {
    currentUser.value = await getCurrentUser(token.value)
  } catch {
    clearStoredToken()
    token.value = ''
    currentUser.value = null
  } finally {
    isCheckingSession.value = false
  }
}

async function handleLogin(accessToken) {
  token.value = accessToken
  storeToken(accessToken)
  isCheckingSession.value = true
  await loadCurrentUser()
}

async function handleLogout() {
  try {
    await logout(token.value)
  } catch {
    // Ignore logout failures; local session is cleared below.
  }
  clearStoredToken()
  token.value = ''
  currentUser.value = null
  currentPageId.value = 'documents'
}

onMounted(loadCurrentUser)

watch(pages, () => {
  if (!pages.value.some((page) => page.id === currentPageId.value)) {
    currentPageId.value = 'documents'
  }
})
</script>

<template>
  <div class="app-shell">
    <main v-if="isCheckingSession" class="empty-state">
      <h2>正在确认登录状态</h2>
      <p>请稍候。</p>
    </main>

    <LoginPage v-else-if="!isAuthenticated" @login="handleLogin" />

    <template v-else>
      <AppTopbar
        :pages="pages"
        :current-page-id="currentPageId"
        :current-user="currentUser"
        @logout="handleLogout"
        @update:current-page-id="currentPageId = $event"
      />

      <KeepAlive>
        <component :is="currentPageComponent" :token="token" />
      </KeepAlive>
    </template>
  </div>
</template>
