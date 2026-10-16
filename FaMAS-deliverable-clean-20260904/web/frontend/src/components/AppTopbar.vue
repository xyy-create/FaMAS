<script setup>
import { computed } from 'vue'

const props = defineProps({
  pages: {
    type: Array,
    required: true,
  },
  currentPageId: {
    type: String,
    required: true,
  },
  currentUser: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits(['logout', 'update:currentPageId'])

const roleLabel = computed(() => (props.currentUser.role === 'admin' ? '管理员' : '普通用户'))
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <span class="brand-name">书脉</span>
      <span class="kb-name">默认知识库</span>
    </div>

    <nav class="main-nav" aria-label="主导航">
      <button
        v-for="page in pages"
        :key="page.id"
        class="nav-item"
        :class="{ active: currentPageId === page.id }"
        type="button"
        @click="emit('update:currentPageId', page.id)"
      >
        {{ page.label }}
      </button>
    </nav>

    <div class="user-actions">
      <span class="admin-label">{{ currentUser.username }} · {{ roleLabel }}</span>
      <button class="logout-button" type="button" @click="emit('logout')">退出</button>
    </div>
  </header>
</template>
