<script setup>
import { ref } from 'vue'

import { login, register } from '../lib/api'

const emit = defineEmits(['login'])

const username = ref('')
const password = ref('')
const mode = ref('login')
const isSubmitting = ref(false)
const errorMessage = ref('')
const successMessage = ref('')
const passwordPolicy = '密码至少 8 位，并且需要同时包含字母和数字。'

function validatePassword(passwordValue) {
  if (passwordValue.length < 8) {
    return '密码至少需要 8 位。'
  }
  if (!/[A-Za-z]/.test(passwordValue) || !/\d/.test(passwordValue)) {
    return '密码需要同时包含字母和数字。'
  }
  return ''
}

async function submitLogin() {
  errorMessage.value = ''
  successMessage.value = ''
  isSubmitting.value = true
  try {
    if (mode.value === 'register') {
      const passwordError = validatePassword(password.value)
      if (passwordError) {
        errorMessage.value = passwordError
        return
      }
    }
    const request = mode.value === 'register' ? register : login
    const result = await request(username.value, password.value)
    if (mode.value === 'register' && !result.access_token) {
      successMessage.value = result.message || '账号已创建。'
      mode.value = 'login'
      password.value = ''
      return
    }
    emit('login', result.access_token)
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isSubmitting.value = false
  }
}

function switchMode(nextMode) {
  mode.value = nextMode
  errorMessage.value = ''
  successMessage.value = ''
}
</script>

<template>
  <main class="login-shell">
    <section class="login-panel">
      <div class="login-header">
        <p class="eyebrow">{{ mode === 'register' ? '创建账号' : '登录' }}</p>
        <h1>书脉</h1>
      </div>

      <form class="settings-form" @submit.prevent="submitLogin">
        <label class="form-field">
          <span>账号</span>
          <input v-model="username" type="text" autocomplete="username" />
        </label>

        <label class="form-field">
          <span>密码</span>
          <input
            v-model="password"
            type="password"
            :autocomplete="mode === 'register' ? 'new-password' : 'current-password'"
          />
        </label>

        <p v-if="mode === 'register'" class="inline-message">{{ passwordPolicy }}</p>

        <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>
        <p v-if="successMessage" class="success-message">{{ successMessage }}</p>

        <button class="primary-button" type="submit" :disabled="isSubmitting">
          {{
            isSubmitting
              ? mode === 'register'
                ? '正在创建...'
                : '正在登录...'
              : mode === 'register'
                ? '创建账号'
                : '登录'
          }}
        </button>

        <button
          class="secondary-button"
          type="button"
          @click="switchMode(mode === 'register' ? 'login' : 'register')"
        >
          {{ mode === 'register' ? '使用已有账号' : '创建新账号' }}
        </button>
      </form>
    </section>
  </main>
</template>
