<script setup>
import { onMounted, reactive, ref } from 'vue'

import { listApiSettings, saveApiSetting, testApiSetting } from '../lib/api'

const props = defineProps({
  token: {
    type: String,
    required: true,
  },
})

const providers = reactive([
  {
    id: 'dashscope',
    name: '通义千问 / Qwen',
    model_name: 'qwen-plus',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    api_key: '',
    masked_api_key: '',
    has_api_key: false,
    key_source: 'user',
    temperature: '0.2',
    max_tokens: '4096',
    statusMessage: '',
    testResult: null,
    isTesting: false,
  },
  {
    id: 'deepseek',
    name: 'DeepSeek',
    model_name: 'deepseek-chat',
    base_url: 'https://api.deepseek.com',
    api_key: '',
    masked_api_key: '',
    has_api_key: false,
    key_source: 'user',
    temperature: '0.2',
    max_tokens: '4096',
    statusMessage: '',
    testResult: null,
    isTesting: false,
  },
])

const isLoading = ref(false)
const errorMessage = ref('')

async function loadSettings() {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const settings = await listApiSettings(props.token)
    for (const saved of settings) {
      const provider = providers.find((item) => item.id === saved.provider)
      if (!provider) continue
      provider.model_name = saved.model_name
      provider.base_url = saved.base_url
      provider.masked_api_key = saved.masked_api_key
      provider.has_api_key = saved.has_api_key
      provider.key_source = saved.key_source
      provider.temperature = saved.temperature
      provider.max_tokens = saved.max_tokens
    }
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isLoading.value = false
  }
}

async function saveProvider(provider) {
    provider.statusMessage = '保存中...'
  errorMessage.value = ''
  try {
    const saved = await saveApiSetting(props.token, provider.id, {
      provider: provider.id,
      model_name: provider.model_name,
      base_url: provider.base_url,
      api_key: provider.api_key || null,
      temperature: provider.temperature,
      max_tokens: provider.max_tokens,
    })
    provider.api_key = ''
    provider.masked_api_key = saved.masked_api_key
    provider.has_api_key = saved.has_api_key
    provider.key_source = saved.key_source
    provider.statusMessage = '已保存'
    provider.testResult = null
  } catch (error) {
    provider.statusMessage = ''
    errorMessage.value = error.message
  }
}

async function testProvider(provider) {
  provider.isTesting = true
  provider.statusMessage = ''
  provider.testResult = null
  errorMessage.value = ''
  try {
    provider.testResult = await testApiSetting(props.token, provider.id)
  } catch (error) {
    provider.testResult = {
      ok: false,
      message: error.message,
      response_preview: '',
    }
  } finally {
    provider.isTesting = false
  }
}

onMounted(loadSettings)
</script>

<template>
  <main class="workspace">
    <section class="page-header">
      <div>
        <p class="eyebrow">模型接口</p>
        <h1>模型 API 设置</h1>
      </div>
      <button class="secondary-button" type="button" :disabled="isLoading" @click="loadSettings">
        刷新
      </button>
    </section>

    <p v-if="errorMessage" class="error-message page-message">{{ errorMessage }}</p>

    <section class="settings-grid">
      <article v-for="provider in providers" :key="provider.id" class="settings-card">
        <div class="settings-card-header">
          <div>
            <h2>{{ provider.name }}</h2>
            <p>密钥保存在后端，前端只显示脱敏结果。</p>
          </div>
          <span
            class="status-badge"
            :class="provider.has_api_key ? 'status-graph-ready' : 'status-pending'"
          >
            {{
              provider.has_api_key
                ? provider.key_source === 'system'
                  ? '系统默认'
                  : '已配置'
                : '未配置'
            }}
          </span>
        </div>

        <form class="settings-form" @submit.prevent="saveProvider(provider)">
          <label class="form-field">
            <span>接口密钥</span>
            <input
              v-model="provider.api_key"
              type="password"
              :placeholder="provider.masked_api_key || '输入接口密钥'"
              autocomplete="off"
            />
          </label>

          <label class="form-field">
            <span>模型名称</span>
            <input v-model="provider.model_name" type="text" />
          </label>

          <label class="form-field">
            <span>接口地址</span>
            <input v-model="provider.base_url" type="url" />
          </label>

          <div class="form-row">
            <label class="form-field">
              <span>温度</span>
              <input v-model="provider.temperature" type="number" min="0" max="2" step="0.1" />
            </label>

            <label class="form-field">
              <span>最大输出 Token</span>
              <input v-model="provider.max_tokens" type="number" min="1" step="1" />
            </label>
          </div>

          <div class="form-actions">
            <span class="form-status">{{ provider.statusMessage }}</span>
            <button class="primary-button" type="submit">保存 {{ provider.name }}</button>
            <button
              class="secondary-button"
              type="button"
              :disabled="provider.isTesting"
              @click="testProvider(provider)"
            >
              {{ provider.isTesting ? '测试中...' : '测试连接' }}
            </button>
          </div>

          <div
            v-if="provider.testResult"
            class="api-test-result"
            :class="provider.testResult.ok ? 'api-test-result-ok' : 'api-test-result-error'"
          >
            <strong>{{ provider.testResult.ok ? '连接正常' : '连接失败' }}</strong>
            <p>{{ provider.testResult.message }}</p>
            <p v-if="provider.testResult.status_code">
              状态码：{{ provider.testResult.status_code }}
            </p>
            <p v-if="provider.testResult.response_preview">
              响应：{{ provider.testResult.response_preview }}
            </p>
          </div>
        </form>
      </article>
    </section>

    <section class="content-panel info-panel">
      <div>
        <h2>保存方式</h2>
          <p>
          接口密钥会提交给后端保存，保存后不会在前端完整显示。
        </p>
      </div>
    </section>
  </main>
</template>
