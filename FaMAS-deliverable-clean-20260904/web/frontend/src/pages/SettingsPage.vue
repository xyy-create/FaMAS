<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'

import {
  changeAccountPassword,
  getSystemSettings,
  listApiSettings,
  listAvailableModels,
  saveApiSetting,
  testApiSetting,
} from '../lib/api'

const props = defineProps({
  token: {
    type: String,
    required: true,
  },
})

const systemSettings = ref(null)
const isLoading = ref(false)
const isSavingPassword = ref(false)
const errorMessage = ref('')
const successMessage = ref('')
const passwordMessage = ref('')
const activeSectionId = ref('account')
const passwordForm = ref({
  current_password: '',
  new_password: '',
})
const passwordPolicy = '密码至少 8 位，并且需要同时包含字母和数字。'

const providers = reactive([
  createProviderState(
    'dashscope',
    '通义千问 / Qwen',
    'qwen-plus',
    'https://dashscope.aliyuncs.com/compatible-mode/v1',
  ),
  createProviderState('deepseek', 'DeepSeek', 'deepseek-chat', 'https://api.deepseek.com'),
])

const isAdmin = computed(() => systemSettings.value?.admin?.role === 'admin')
const accountStatusClass = computed(() =>
  systemSettings.value?.admin?.is_active ? 'status-graph-ready' : 'status-failed',
)
const accountStatusLabel = computed(() =>
  systemSettings.value?.admin?.is_active ? '启用' : '停用',
)
const registrationMode = computed(() => systemSettings.value?.modes?.registration ?? 'immediate')
const registrationLabel = computed(() =>
  registrationMode.value === 'approval' ? '管理员审核' : '立即可用',
)
const currentKnowledgeBaseName = computed(() =>
  valueOrFallback(systemSettings.value?.knowledge_base?.name, '默认知识库'),
)
const publicAccess = computed(() => systemSettings.value?.public_access ?? null)
const publicAccessClass = computed(() =>
  publicAccess.value?.ready_for_temporary_public_access ? 'status-graph-ready' : 'status-degraded',
)
const publicAccessLabel = computed(() =>
  publicAccess.value?.ready_for_temporary_public_access ? '已就绪' : '需配置',
)
const sidebarSections = computed(() => {
  const storage = systemSettings.value?.storage ?? {}
  const hasPublicAccess = Boolean(publicAccess.value)
  return [
    { id: 'account', label: '账号信息', hint: '当前账号与权限' },
    { id: 'password', label: '修改密码', hint: '更新登录密码' },
    { id: 'runtime', label: '运行环境', hint: '前后端与数据库' },
    {
      id: 'storage',
      label: '存储与任务',
      hint: Object.keys(storage).length > 0 ? '路径与上传限制' : '任务与上传限制',
    },
    { id: 'access', label: '访问模式', hint: '注册与处理开关' },
    { id: 'knowledge-base', label: '知识库', hint: '默认知识库信息' },
    ...(hasPublicAccess ? [{ id: 'public-access', label: '临时公网访问', hint: '隧道与检查项' }] : []),
    { id: 'entry', label: '访问入口', hint: '本地地址' },
    { id: 'models', label: '模型设置', hint: 'Qwen / DeepSeek' },
  ]
})
const activeSection = computed(
  () => sidebarSections.value.find((item) => item.id === activeSectionId.value) ?? sidebarSections.value[0] ?? null,
)

watch(
  sidebarSections,
  (sections) => {
    if (!sections.some((section) => section.id === activeSectionId.value)) {
      activeSectionId.value = sections[0]?.id ?? 'account'
    }
  },
  { immediate: true },
)

function createProviderState(id, name, defaultModelName, defaultBaseUrl) {
  return reactive({
    id,
    name,
    model_name: defaultModelName,
    base_url: defaultBaseUrl,
    api_key: '',
    masked_api_key: '',
    has_api_key: false,
    key_source: 'user',
    temperature: '0.2',
    max_tokens: '4096',
    statusMessage: '',
    testResult: null,
    isTesting: false,
    isLoadingModels: false,
    availableModels: [],
    modelMessage: '',
  })
}

function selectSection(sectionId) {
  activeSectionId.value = sectionId
}

function valueOrFallback(value, fallback = '暂无') {
  if (value === null || value === undefined || value === '') {
    return fallback
  }
  if (typeof value === 'boolean') {
    return value ? '是' : '否'
  }
  return value
}

function roleLabel(role) {
  const labels = {
    admin: '管理员',
    user: '普通用户',
  }
  return labels[role] ?? valueOrFallback(role)
}

function approvalStatusLabel(status) {
  const labels = {
    approved: '已通过',
    pending: '待审核',
    rejected: '已拒绝',
  }
  return labels[String(status || '').toLowerCase()] ?? valueOrFallback(status)
}

function runtimeModeLabel(mode) {
  const labels = {
    development: '开发模式',
    public: '临时公网模式',
    production: '生产模式',
  }
  return labels[String(mode || '').toLowerCase()] ?? valueOrFallback(mode)
}

function knowledgeBaseModeLabel(mode) {
  const labels = {
    reserved: '预留',
  }
  return labels[String(mode || '').toLowerCase()] ?? valueOrFallback(mode)
}

function pipelineStopLabel(value) {
  const labels = {
    parse_pdf: 'PDF 解析后',
    build_graph: '图谱构建后',
    full_pipeline: '完整流水线',
  }
  return labels[String(value || '').toLowerCase()] ?? valueOrFallback(value)
}

function frontendDistLabel(value) {
  const labels = {
    built: '已构建',
    'not built': '未构建',
  }
  return labels[String(value || '').toLowerCase()] ?? valueOrFallback(value)
}

function providerStatusClass(provider) {
  return provider.has_api_key ? 'status-graph-ready' : 'status-pending'
}

function providerStatusLabel(provider) {
  if (!provider.has_api_key) return '未配置'
  return provider.key_source === 'system' ? '系统默认' : '已保存'
}

function providerKeySourceLabel(source) {
  const labels = {
    system: '系统密钥',
    user: '个人密钥',
  }
  return labels[source] ?? valueOrFallback(source)
}

function formatSize(bytes) {
  if (bytes === null || bytes === undefined) return '暂无'
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = Number(bytes)
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

async function loadSettings() {
  isLoading.value = true
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const [systemResult, apiResult] = await Promise.allSettled([
      getSystemSettings(props.token),
      listApiSettings(props.token),
    ])

    if (systemResult.status === 'fulfilled') {
      systemSettings.value = systemResult.value
    } else {
      errorMessage.value = systemResult.reason?.message ?? '系统设置加载失败。'
    }

    if (apiResult.status === 'fulfilled') {
      syncProviders(apiResult.value)
    } else {
      errorMessage.value = errorMessage.value
        ? `${errorMessage.value} / ${apiResult.reason?.message ?? '模型设置加载失败。'}`
        : apiResult.reason?.message ?? '模型设置加载失败。'
    }
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isLoading.value = false
  }
}

function syncProviders(savedSettings) {
  for (const saved of savedSettings ?? []) {
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
}

async function updatePassword() {
  isSavingPassword.value = true
  errorMessage.value = ''
  successMessage.value = ''
  passwordMessage.value = ''
  const passwordError = validatePassword(passwordForm.value.new_password)
  if (passwordError) {
    errorMessage.value = passwordError
    isSavingPassword.value = false
    return
  }
  try {
    await changeAccountPassword(props.token, passwordForm.value)
    passwordForm.value = {
      current_password: '',
      new_password: '',
    }
    passwordMessage.value = '密码已更新。'
    successMessage.value = '密码已更新。'
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isSavingPassword.value = false
  }
}

function validatePassword(passwordValue) {
  if (passwordValue.length < 8) {
    return '密码至少需要 8 位。'
  }
  if (!/[A-Za-z]/.test(passwordValue) || !/\d/.test(passwordValue)) {
    return passwordPolicy
  }
  return ''
}

async function saveProvider(provider) {
  provider.statusMessage = '保存中...'
  errorMessage.value = ''
  successMessage.value = ''
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
    successMessage.value = `${provider.name} 已保存。`
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

async function loadAvailableModels(provider) {
  provider.isLoadingModels = true
  provider.modelMessage = ''
  try {
    const result = await listAvailableModels(props.token, provider.id)
    provider.availableModels = Array.isArray(result?.models) ? result.models : []
    provider.modelMessage =
      result?.message ??
      (provider.availableModels.length > 0
        ? `已加载 ${provider.availableModels.length} 个模型。`
        : '暂无可用模型。')
    if (!provider.model_name && provider.availableModels.length > 0) {
      provider.model_name = provider.availableModels[0].id
    }
  } catch (error) {
    provider.modelMessage = error.message
  } finally {
    provider.isLoadingModels = false
  }
}

function chooseModel(provider, modelId) {
  provider.model_name = modelId
  provider.modelMessage = `已选择 ${modelId}`
}

onMounted(loadSettings)
</script>

<template>
  <main class="workspace settings-workspace">
    <section class="page-header settings-page-header">
      <div>
        <p class="eyebrow">设置</p>
        <h1>设置工作台</h1>
      </div>
      <button class="secondary-button" type="button" :disabled="isLoading" @click="loadSettings">
        {{ isLoading ? '刷新中...' : '刷新' }}
      </button>
    </section>

    <p v-if="errorMessage" class="error-message page-message">{{ errorMessage }}</p>
    <p v-if="successMessage" class="success-message page-message">{{ successMessage }}</p>

    <section class="settings-layout">
      <aside class="settings-sidebar">
        <div class="settings-sidebar-head">
          <p class="eyebrow">导航</p>
          <h2>设置目录</h2>
          <p>左侧选择要查看的内容，右侧只显示当前项的详情。</p>
        </div>

        <nav class="settings-nav" aria-label="设置导航">
          <button
            v-for="section in sidebarSections"
            :key="section.id"
            class="settings-nav-item"
            :class="{ active: activeSectionId === section.id }"
            type="button"
            @click="selectSection(section.id)"
          >
            <strong>{{ section.label }}</strong>
            <span>{{ section.hint }}</span>
          </button>
        </nav>

        <div class="settings-sidebar-foot">
          <div class="detail-item compact">
            <span>当前账号</span>
            <strong>{{ valueOrFallback(systemSettings?.admin?.username, '加载中') }}</strong>
          </div>
          <div class="detail-item compact">
            <span>默认知识库</span>
            <strong>{{ currentKnowledgeBaseName }}</strong>
          </div>
          <div class="detail-item compact">
            <span>当前状态</span>
            <strong>{{ activeSection?.label ?? '设置' }}</strong>
          </div>
        </div>
      </aside>

      <section class="settings-main">
        <article v-if="activeSectionId === 'account'" class="settings-card settings-panel">
          <div class="settings-card-header">
            <div>
              <h2>账号信息</h2>
              <p>当前登录账号、角色、审核状态与注册方式。</p>
            </div>
            <span class="status-badge" :class="accountStatusClass">{{ accountStatusLabel }}</span>
          </div>

          <div class="detail-list">
            <div class="detail-item">
              <span>账号</span>
              <strong>{{ valueOrFallback(systemSettings?.admin?.username, 'admin') }}</strong>
            </div>
            <div class="detail-item">
              <span>角色</span>
              <strong>{{ roleLabel(systemSettings?.admin?.role) }}</strong>
            </div>
            <div class="detail-item">
              <span>审核状态</span>
              <strong>{{ approvalStatusLabel(systemSettings?.admin?.approval_status) }}</strong>
            </div>
            <div class="detail-item">
              <span>注册方式</span>
              <strong>{{ registrationLabel }}</strong>
            </div>
            <div v-if="systemSettings?.usage" class="detail-item">
              <span>文档数量</span>
              <strong>{{ valueOrFallback(systemSettings?.usage?.document_count, 0) }}</strong>
            </div>
          </div>
        </article>

        <article v-else-if="activeSectionId === 'password'" class="settings-card settings-panel">
          <div class="settings-card-header">
            <div>
              <h2>修改密码</h2>
              <p>更新当前登录账号的密码。</p>
            </div>
          </div>

          <form class="settings-form" @submit.prevent="updatePassword">
            <label class="form-field">
              <span>当前密码</span>
              <input
                v-model="passwordForm.current_password"
                type="password"
                placeholder="输入当前密码"
                autocomplete="current-password"
                required
              />
            </label>
            <label class="form-field">
              <span>新密码</span>
              <input
                v-model="passwordForm.new_password"
                type="password"
                :placeholder="passwordPolicy"
                autocomplete="new-password"
                minlength="8"
                required
              />
            </label>
            <p class="inline-message">{{ passwordPolicy }}</p>
            <button class="primary-button" type="submit" :disabled="isSavingPassword">
              {{ isSavingPassword ? '更新中...' : '更新密码' }}
            </button>
            <p v-if="passwordMessage" class="inline-message">{{ passwordMessage }}</p>
          </form>
        </article>

        <article v-else-if="activeSectionId === 'runtime'" class="settings-card settings-panel">
          <div class="settings-card-header">
            <div>
              <h2>运行环境</h2>
              <p>当前本机服务的运行信息。</p>
            </div>
          </div>

          <div class="detail-list">
            <div class="detail-item">
              <span>前端</span>
              <strong>{{ valueOrFallback(systemSettings?.runtime?.frontend, 'Vue + Vite') }}</strong>
            </div>
            <div class="detail-item">
              <span>后端</span>
              <strong>{{ valueOrFallback(systemSettings?.runtime?.backend, 'Python + FastAPI') }}</strong>
            </div>
            <div class="detail-item" v-if="systemSettings?.runtime?.python">
              <span>Python 版本</span>
              <strong>{{ valueOrFallback(systemSettings?.runtime?.python) }}</strong>
            </div>
            <div class="detail-item" v-if="systemSettings?.runtime?.platform">
              <span>平台</span>
              <strong>{{ valueOrFallback(systemSettings?.runtime?.platform) }}</strong>
            </div>
            <div class="detail-item">
              <span>数据库</span>
              <strong>{{ valueOrFallback(systemSettings?.runtime?.database, 'SQLite') }}</strong>
            </div>
            <div class="detail-item">
              <span>运行模式</span>
              <strong>{{ runtimeModeLabel(systemSettings?.runtime?.runtime_mode) }}</strong>
            </div>
            <div class="detail-item">
              <span>前端构建</span>
              <strong>{{ frontendDistLabel(systemSettings?.runtime?.frontend_dist) }}</strong>
            </div>
            <div class="detail-item">
              <span>模拟流水线</span>
              <strong>{{ valueOrFallback(systemSettings?.runtime?.mock_pipeline) }}</strong>
            </div>
          </div>
        </article>

        <article v-else-if="activeSectionId === 'storage'" class="settings-card settings-panel">
          <div class="settings-card-header">
            <div>
              <h2>存储与任务</h2>
              <p>上传限制、存储路径与任务并发状态。</p>
            </div>
          </div>

          <div class="detail-list">
            <div class="detail-item">
              <span>并发任务上限</span>
              <strong>{{ valueOrFallback(systemSettings?.jobs?.active_job_limit, 0) }}</strong>
            </div>
            <div class="detail-item">
              <span>等待中任务</span>
              <strong>{{ valueOrFallback(systemSettings?.jobs?.pending_job_count, 0) }}</strong>
            </div>
            <div class="detail-item">
              <span>运行中任务</span>
              <strong>{{ valueOrFallback(systemSettings?.jobs?.running_job_count, 0) }}</strong>
            </div>
            <div class="detail-item">
              <span>可用任务槽位</span>
              <strong>{{ valueOrFallback(systemSettings?.jobs?.queue_slots_available, 0) }}</strong>
            </div>
            <div class="detail-item">
              <span>活动任务</span>
              <strong>{{ valueOrFallback(systemSettings?.jobs?.has_active_job) }}</strong>
            </div>
            <div class="detail-item">
              <span>分片大小</span>
              <strong>{{ formatSize(systemSettings?.storage?.chunk_size_bytes) }}</strong>
            </div>
            <div class="detail-item">
              <span>最大上传</span>
              <strong>{{ formatSize(systemSettings?.storage?.max_upload_bytes) }}</strong>
            </div>
          </div>

          <div v-if="Object.keys(systemSettings?.storage ?? {}).length > 0" class="detail-list settings-path-list">
            <div class="detail-item" v-if="systemSettings?.storage?.project_dir">
              <span>项目目录</span>
              <strong>{{ valueOrFallback(systemSettings?.storage?.project_dir) }}</strong>
            </div>
            <div class="detail-item" v-if="systemSettings?.storage?.web_dir">
              <span>Web 目录</span>
              <strong>{{ valueOrFallback(systemSettings?.storage?.web_dir) }}</strong>
            </div>
            <div class="detail-item" v-if="systemSettings?.storage?.storage_dir">
              <span>存储目录</span>
              <strong>{{ valueOrFallback(systemSettings?.storage?.storage_dir) }}</strong>
            </div>
            <div class="detail-item" v-if="systemSettings?.storage?.user_storage_dir">
              <span>用户目录</span>
              <strong>{{ valueOrFallback(systemSettings?.storage?.user_storage_dir) }}</strong>
            </div>
            <div class="detail-item" v-if="systemSettings?.storage?.upload_dir">
              <span>旧上传目录</span>
              <strong>{{ valueOrFallback(systemSettings?.storage?.upload_dir) }}</strong>
            </div>
            <div class="detail-item" v-if="systemSettings?.storage?.job_log_dir">
              <span>日志目录</span>
              <strong>{{ valueOrFallback(systemSettings?.storage?.job_log_dir) }}</strong>
            </div>
          </div>
        </article>

        <article v-else-if="activeSectionId === 'access'" class="settings-card settings-panel">
          <div class="settings-card-header">
            <div>
              <h2>访问模式</h2>
              <p>注册、图谱构建与流水线调度开关。</p>
            </div>
          </div>

          <div class="detail-list">
            <div class="detail-item">
              <span>注册模式</span>
              <strong>{{ registrationLabel }}</strong>
            </div>
            <div class="detail-item">
              <span>需要审核</span>
              <strong>{{ valueOrFallback(systemSettings?.modes?.registration_requires_approval) }}</strong>
            </div>
            <div v-if="systemSettings?.modes?.example_kg_fallback !== undefined" class="detail-item">
              <span>示例图谱回退</span>
              <strong>{{ valueOrFallback(systemSettings?.modes?.example_kg_fallback) }}</strong>
            </div>
            <div v-if="systemSettings?.modes?.pipeline_stop_at" class="detail-item">
              <span>流水线停止点</span>
              <strong>{{ pipelineStopLabel(systemSettings?.modes?.pipeline_stop_at) }}</strong>
            </div>
            <div v-if="systemSettings?.modes?.pipeline_worker_enabled !== undefined" class="detail-item">
              <span>任务队列</span>
              <strong>{{ valueOrFallback(systemSettings?.modes?.pipeline_worker_enabled) }}</strong>
            </div>
            <div v-if="systemSettings?.modes?.pipeline_worker_concurrency !== undefined" class="detail-item">
              <span>队列并发数</span>
              <strong>{{ valueOrFallback(systemSettings?.modes?.pipeline_worker_concurrency, 0) }}</strong>
            </div>
            <div v-if="systemSettings?.modes?.mineru_model_source" class="detail-item">
              <span>MinerU 来源</span>
              <strong>{{ valueOrFallback(systemSettings?.modes?.mineru_model_source) }}</strong>
            </div>
            <div v-if="systemSettings?.modes?.mineru_device_mode" class="detail-item">
              <span>MinerU 设备</span>
              <strong>{{ valueOrFallback(systemSettings?.modes?.mineru_device_mode) }}</strong>
            </div>
          </div>
        </article>

        <article v-else-if="activeSectionId === 'knowledge-base'" class="settings-card settings-panel">
          <div class="settings-card-header">
            <div>
              <h2>知识库</h2>
              <p>当前默认知识库的显示信息。</p>
            </div>
          </div>

          <div class="detail-list">
            <div class="detail-item">
              <span>知识库名称</span>
              <strong>{{ currentKnowledgeBaseName }}</strong>
            </div>
            <div v-if="systemSettings?.knowledge_base?.id !== undefined" class="detail-item">
              <span>知识库 ID</span>
              <strong>{{ valueOrFallback(systemSettings?.knowledge_base?.id, '暂无') }}</strong>
            </div>
            <div v-if="systemSettings?.knowledge_base?.multi_kb_management" class="detail-item">
              <span>多知识库管理</span>
              <strong>{{ knowledgeBaseModeLabel(systemSettings?.knowledge_base?.multi_kb_management) }}</strong>
            </div>
          </div>
        </article>

        <article v-else-if="activeSectionId === 'public-access'" class="settings-card settings-panel">
          <div class="settings-card-header">
            <div>
              <h2>临时公网访问</h2>
              <p>用于本机通过隧道临时公开访问时的准备状态。</p>
            </div>
            <span class="status-badge" :class="publicAccessClass">{{ publicAccessLabel }}</span>
          </div>

          <div class="detail-list">
            <div class="detail-item">
              <span>公网地址</span>
              <strong>{{ valueOrFallback(publicAccess?.public_url) }}</strong>
            </div>
            <div class="detail-item">
              <span>推荐目标</span>
              <strong>{{ valueOrFallback(publicAccess?.recommended_local_target) }}</strong>
            </div>
            <div class="detail-item">
              <span>单端口前端</span>
              <strong>{{ valueOrFallback(publicAccess?.checks?.single_port_frontend_ready) }}</strong>
            </div>
            <div class="detail-item">
              <span>注册审核</span>
              <strong>{{ valueOrFallback(publicAccess?.checks?.registration_approval_enabled) }}</strong>
            </div>
            <div class="detail-item">
              <span>系统密钥</span>
              <strong>{{ valueOrFallback(publicAccess?.checks?.secret_key_hardened) }}</strong>
            </div>
            <div class="detail-item">
              <span>公网地址配置</span>
              <strong>{{ valueOrFallback(publicAccess?.checks?.public_url_configured) }}</strong>
            </div>
          </div>
        </article>

        <article v-else-if="activeSectionId === 'entry'" class="settings-card settings-panel">
          <div class="settings-card-header">
            <div>
              <h2>访问入口</h2>
              <p>开发访问和单端口访问的常用地址。</p>
            </div>
          </div>

          <div class="detail-list">
            <div class="detail-item">
              <span>开发前端</span>
              <strong>http://127.0.0.1:5173</strong>
            </div>
            <div class="detail-item">
              <span>单端口访问</span>
              <strong>http://127.0.0.1:8000</strong>
            </div>
            <div class="detail-item">
              <span>接口文档</span>
              <strong>http://127.0.0.1:8000/docs</strong>
            </div>
          </div>
        </article>

        <article v-else-if="activeSectionId === 'models'" class="settings-card settings-panel">
          <div class="settings-card-header">
            <div>
              <h2>模型设置</h2>
              <p>Qwen / DeepSeek 的模型名称、接口地址、密钥与参数。</p>
            </div>
            <span class="status-badge status-graph-ready">可编辑</span>
          </div>

          <div class="settings-provider-grid">
            <article v-for="provider in providers" :key="provider.id" class="settings-provider-card">
              <div class="settings-provider-head">
                <div>
                  <h3>{{ provider.name }}</h3>
                  <p>
                    当前状态：
                    <strong>{{ providerStatusLabel(provider) }}</strong>
                    · {{ providerKeySourceLabel(provider.key_source) }}
                  </p>
                </div>
                <span class="status-badge" :class="providerStatusClass(provider)">
                  {{ providerStatusLabel(provider) }}
                </span>
              </div>

              <form class="settings-form provider-form" @submit.prevent="saveProvider(provider)">
                <label class="form-field">
                  <span>接口密钥</span>
                  <input
                    v-model="provider.api_key"
                    type="password"
                    :placeholder="provider.masked_api_key || '输入后会覆盖保存值'"
                    autocomplete="off"
                  />
                </label>

                <div class="form-row">
                  <label class="form-field">
                    <span>模型名称</span>
                    <input v-model="provider.model_name" type="text" placeholder="例如 qwen-plus" />
                  </label>

                  <label class="form-field">
                    <span>接口地址</span>
                    <input v-model="provider.base_url" type="url" />
                  </label>
                </div>

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

                <div class="settings-provider-actions">
                  <button
                    class="secondary-button"
                    type="button"
                    :disabled="provider.isLoadingModels"
                    @click="loadAvailableModels(provider)"
                  >
                    {{ provider.isLoadingModels ? '加载模型中...' : '获取可选模型' }}
                  </button>
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

                <p v-if="provider.statusMessage" class="inline-message">{{ provider.statusMessage }}</p>
                <p v-if="provider.modelMessage" class="inline-message">{{ provider.modelMessage }}</p>

                <div v-if="provider.availableModels.length > 0" class="model-chip-list">
                  <button
                    v-for="model in provider.availableModels"
                    :key="model.id"
                    type="button"
                    class="model-chip"
                    :class="{ active: provider.model_name === model.id }"
                    @click="chooseModel(provider, model.id)"
                  >
                    {{ model.name }}
                  </button>
                </div>

                <div
                  v-if="provider.testResult"
                  class="api-test-result"
                  :class="provider.testResult.ok ? 'api-test-result-ok' : 'api-test-result-error'"
                >
                  <strong>{{ provider.testResult.ok ? '连接正常' : '连接失败' }}</strong>
                  <p>{{ provider.testResult.message }}</p>
                  <p v-if="provider.testResult.status_code">状态码：{{ provider.testResult.status_code }}</p>
                  <p v-if="provider.testResult.response_preview">
                    响应：{{ provider.testResult.response_preview }}
                  </p>
                </div>
              </form>
            </article>
          </div>
        </article>
      </section>
    </section>

    <section class="content-panel info-panel settings-note-panel">
      <div>
        <h2>说明</h2>
        <p>这个页面把系统设置和模型设置放在同一处，左侧切换，右侧查看和修改当前项。</p>
      </div>
    </section>
  </main>
</template>
