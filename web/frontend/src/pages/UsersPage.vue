<script setup>
import { onMounted, ref } from 'vue'

import { getUserOverview, listUsers, resetUserPassword, updateUserStatus } from '../lib/api'
import { displayMetadataText } from '../lib/display'

const props = defineProps({
  token: {
    type: String,
    required: true,
  },
})

const users = ref([])
const isLoading = ref(false)
const updatingUserId = ref(null)
const selectedOverview = ref(null)
const isLoadingOverview = ref(false)
const errorMessage = ref('')
const successMessage = ref('')
const passwordPolicy = '新密码至少 8 位，并且需要同时包含字母和数字。'

async function loadUsers() {
  isLoading.value = true
  errorMessage.value = ''
  try {
    users.value = await listUsers(props.token)
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isLoading.value = false
  }
}

async function setUserStatus(user, isActive) {
  updatingUserId.value = user.id
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const updated = await updateUserStatus(props.token, user.id, isActive)
    users.value = users.value.map((item) => (item.id === updated.id ? updated : item))
    if (selectedOverview.value?.user?.id === updated.id) {
      selectedOverview.value.user = updated
    }
    successMessage.value = `${updated.username} 已${updated.is_active ? '启用' : '停用'}`
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    updatingUserId.value = null
  }
}

async function resetPassword(user) {
  const newPassword = window.prompt(`为 ${user.username} 输入新密码`)
  if (newPassword === null) return
  const passwordError = validatePassword(newPassword)
  if (passwordError) {
    errorMessage.value = passwordError
    successMessage.value = ''
    return
  }

  updatingUserId.value = user.id
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const updated = await resetUserPassword(props.token, user.id, newPassword)
    users.value = users.value.map((item) => (item.id === updated.id ? updated : item))
    successMessage.value = `${updated.username} 密码已重置`
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    updatingUserId.value = null
  }
}

function validatePassword(passwordValue) {
  if (passwordValue.length < 8) {
    return '新密码至少需要 8 位。'
  }
  if (!/[A-Za-z]/.test(passwordValue) || !/\d/.test(passwordValue)) {
    return passwordPolicy
  }
  return ''
}

async function inspectUser(user) {
  selectedOverview.value = null
  isLoadingOverview.value = true
  errorMessage.value = ''
  try {
    selectedOverview.value = await getUserOverview(props.token, user.id)
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isLoadingOverview.value = false
  }
}

function formatDate(value) {
  if (!value) return '-'
  const text = String(value)
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(text)
  const date = new Date(hasTimezone ? text : `${text}Z`)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function statusClass(user) {
  if (user.approval_status === 'pending') return 'status-pending'
  return user.is_active ? 'status-graph-ready' : 'status-failed'
}

function documentStatusClass(status) {
  return `status-${String(status || '').toLowerCase().replaceAll('_', '-')}`
}

function documentStatusLabel(status) {
  const labels = {
    pending: '待处理',
    running: '处理中',
    parsed: '已解析',
    graph_ready: '图谱就绪',
    success: '成功',
    degraded: '降级完成',
    failed: '失败',
  }
  return labels[String(status || '').toLowerCase()] ?? status
}

function statusLabel(user) {
  if (user.approval_status === 'pending') return '待审核'
  return user.is_active ? '启用' : '停用'
}

function latestJobLabel(user) {
  if (!user.latest_job_stage || !user.latest_job_status) return '-'
  return `${stageLabel(user.latest_job_stage)} / ${jobStatusLabel(user.latest_job_status)}`
}

function stageLabel(stage) {
  const labels = {
    parse_pdf: '解析 PDF',
    build_graph: '构建图谱',
    full_pipeline: '完整处理',
    upload: '上传',
  }
  return labels[stage] ?? stage
}

function jobStatusLabel(status) {
  const labels = {
    pending: '等待中',
    running: '运行中',
    success: '成功',
    degraded: '降级完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return labels[String(status || '').toLowerCase()] ?? status
}

function providerLabel(provider) {
  const labels = {
    dashscope: '通义千问 / Qwen',
    deepseek: 'DeepSeek',
  }
  return labels[provider] ?? provider
}

function providerSourceLabel(source) {
  const labels = {
    system: '系统默认密钥',
    user: '个人密钥',
  }
  return labels[source] ?? source
}

function documentMetadataLabel(document) {
  return displayMetadataText(document.subject, document.grade, document.publisher)
}

function overviewJobLabel(document) {
  if (!document.latest_job_stage || !document.latest_job_status) return '-'
  return `${stageLabel(document.latest_job_stage)} / ${jobStatusLabel(document.latest_job_status)}`
}

function kgItemKindLabel(kind) {
  const labels = {
    node: '节点',
    edge: '关系',
    image: '图片',
  }
  return labels[String(kind || '').toLowerCase()] ?? kind
}

function overrideActionLabel(item) {
  if (item.is_hidden) return '隐藏'
  if (item.is_new) return '新增'
  return '修正'
}

function annotationTagsText(tags) {
  return Array.isArray(tags) && tags.length ? tags.join('、') : '-'
}

function canChangeStatus(user) {
  return user.role !== 'admin'
}

onMounted(loadUsers)
</script>

<template>
  <main class="workspace">
    <section class="page-header">
      <div>
        <p class="eyebrow">用户</p>
        <h1>用户管理</h1>
      </div>
      <button class="secondary-button" type="button" :disabled="isLoading" @click="loadUsers">
        {{ isLoading ? '刷新中...' : '刷新' }}
      </button>
    </section>

    <p v-if="errorMessage" class="error-message page-message">{{ errorMessage }}</p>
    <p v-if="successMessage" class="success-message page-message">{{ successMessage }}</p>

    <section class="content-panel table-panel">
      <div class="panel-header">
        <div>
          <h2>账号列表</h2>
          <p>{{ users.length }} 个已注册用户</p>
        </div>
      </div>

      <div class="table-wrap">
        <table class="data-table user-table">
          <thead>
            <tr>
              <th>账号</th>
              <th>角色</th>
              <th>状态</th>
              <th>文档</th>
              <th>任务</th>
              <th>最新任务</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.id">
              <td class="file-name">{{ user.username }}</td>
              <td>{{ user.role === 'admin' ? '管理员' : '普通用户' }}</td>
              <td>
                <span class="status-badge" :class="statusClass(user)">
                  {{ statusLabel(user) }}
                </span>
              </td>
              <td>{{ user.document_count }}</td>
              <td>
                <span
                  class="status-badge"
                  :class="user.active_job_count ? 'status-pending' : 'status-graph-ready'"
                >
                  {{ user.active_job_count ? `${user.active_job_count} 个运行中` : '空闲' }}
                </span>
              </td>
              <td>{{ latestJobLabel(user) }}</td>
              <td>{{ formatDate(user.created_at) }}</td>
              <td>
                <div class="row-actions">
                  <button
                    class="text-button"
                    type="button"
                    :disabled="isLoadingOverview"
                    @click="inspectUser(user)"
                  >
                    查看
                  </button>
                  <button
                    v-if="canChangeStatus(user) && user.approval_status === 'pending'"
                    class="text-button"
                    type="button"
                    :disabled="updatingUserId === user.id"
                    @click="setUserStatus(user, true)"
                  >
                    {{ updatingUserId === user.id ? '更新中...' : '通过' }}
                  </button>
                  <button
                    v-if="canChangeStatus(user)"
                    class="text-button"
                    type="button"
                    :disabled="updatingUserId === user.id"
                    @click="resetPassword(user)"
                  >
                    重置密码
                  </button>
                  <button
                    v-if="canChangeStatus(user) && user.is_active && user.approval_status !== 'pending'"
                    class="text-button danger"
                    type="button"
                    :disabled="updatingUserId === user.id"
                    @click="setUserStatus(user, false)"
                  >
                    {{ updatingUserId === user.id ? '更新中...' : '停用' }}
                  </button>
                  <button
                    v-if="canChangeStatus(user) && !user.is_active && user.approval_status !== 'pending'"
                    class="text-button"
                    type="button"
                    :disabled="updatingUserId === user.id"
                    @click="setUserStatus(user, true)"
                  >
                    {{ updatingUserId === user.id ? '更新中...' : '启用' }}
                  </button>
                  <span v-if="!canChangeStatus(user)" class="muted-inline">受保护</span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>

        <div v-if="!isLoading && users.length === 0" class="empty-table-state">
          暂无用户。
        </div>
      </div>
    </section>

    <section v-if="selectedOverview || isLoadingOverview" class="content-panel table-panel">
      <div class="panel-header">
        <div>
          <h2>
            {{
              selectedOverview
                ? `${selectedOverview.user.username} 概览`
                : '正在加载用户概览'
            }}
          </h2>
          <p>用户文档、处理任务和 API key 状态。</p>
        </div>
        <button
          v-if="selectedOverview"
          class="secondary-button"
          type="button"
          @click="inspectUser(selectedOverview.user)"
        >
          刷新概览
        </button>
      </div>

      <div v-if="isLoadingOverview" class="empty-table-state">正在加载概览...</div>

      <template v-if="selectedOverview && !isLoadingOverview">
        <div class="settings-grid user-overview-grid">
          <article class="settings-card">
            <div class="settings-card-header">
              <div>
                <h2>API Key 状态</h2>
                <p>显示用户使用个人密钥还是系统默认密钥。</p>
              </div>
            </div>
            <div class="detail-list">
              <div
                v-for="provider in selectedOverview.api_settings"
                :key="provider.provider"
                class="detail-item"
              >
                <span>{{ providerLabel(provider.provider) }}</span>
                <strong>
                  {{ providerSourceLabel(provider.effective_source) }}
                  <small v-if="provider.model_name"> / {{ provider.model_name }}</small>
                </strong>
              </div>
            </div>
          </article>

          <article class="settings-card">
            <div class="settings-card-header">
              <div>
                <h2>用户摘要</h2>
                <p>当前账号与任务状态。</p>
              </div>
            </div>
            <div class="detail-list">
              <div class="detail-item">
                <span>状态</span>
                <strong>{{ statusLabel(selectedOverview.user) }}</strong>
              </div>
              <div class="detail-item">
                <span>文档</span>
                <strong>{{ selectedOverview.user.document_count }}</strong>
              </div>
              <div class="detail-item">
                <span>运行中任务</span>
                <strong>{{ selectedOverview.user.active_job_count }}</strong>
              </div>
              <div class="detail-item">
                <span>最新任务</span>
                <strong>{{ latestJobLabel(selectedOverview.user) }}</strong>
              </div>
            </div>
          </article>
        </div>

        <div class="table-wrap">
          <table class="data-table user-documents-table">
            <thead>
              <tr>
                <th>文档</th>
                <th>信息</th>
                <th>状态</th>
                <th>最新任务</th>
                <th>上传时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="document in selectedOverview.documents" :key="document.id">
                <td class="file-name">{{ document.filename }}</td>
                <td>{{ documentMetadataLabel(document) }}</td>
                <td>
                  <span class="status-badge" :class="documentStatusClass(document.status)">
                    {{ documentStatusLabel(document.status) }}
                  </span>
                </td>
                <td>
                  <div class="job-cell">
                    <span>{{ overviewJobLabel(document) }}</span>
                    <small v-if="document.latest_job_error">{{ document.latest_job_error }}</small>
                  </div>
                </td>
                <td>{{ formatDate(document.uploaded_at) }}</td>
              </tr>
            </tbody>
          </table>

          <div v-if="selectedOverview.documents.length === 0" class="empty-table-state">
            该用户暂无文档。
          </div>
        </div>

        <div class="admin-audit-grid">
          <section class="audit-panel">
            <div class="panel-header compact">
              <div>
                <h2>人工修正层</h2>
                <p>明确显示所属用户、文档和修正对象。</p>
              </div>
            </div>
            <div class="table-wrap">
              <table class="data-table audit-table">
                <thead>
                  <tr>
                    <th>所属用户</th>
                    <th>文档</th>
                    <th>对象</th>
                    <th>操作</th>
                    <th>摘要</th>
                    <th>更新时间</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="item in selectedOverview.graph_overrides ?? []" :key="item.id">
                    <td>{{ item.owner_username }}</td>
                    <td class="file-name">{{ item.document_filename }}</td>
                    <td>{{ kgItemKindLabel(item.item_kind) }} · {{ item.item_id }}</td>
                    <td>{{ overrideActionLabel(item) }}</td>
                    <td>{{ item.summary || '-' }}</td>
                    <td>{{ formatDate(item.updated_at) }}</td>
                  </tr>
                </tbody>
              </table>
              <div
                v-if="(selectedOverview.graph_overrides ?? []).length === 0"
                class="empty-table-state"
              >
                该用户暂无人工修正记录。
              </div>
            </div>
          </section>

          <section class="audit-panel">
            <div class="panel-header compact">
              <div>
                <h2>人工标注层</h2>
                <p>显示节点、关系和图片的教学标签与备注。</p>
              </div>
            </div>
            <div class="table-wrap">
              <table class="data-table audit-table">
                <thead>
                  <tr>
                    <th>所属用户</th>
                    <th>文档</th>
                    <th>对象</th>
                    <th>标签</th>
                    <th>备注</th>
                    <th>更新时间</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="item in selectedOverview.graph_annotations ?? []" :key="item.id">
                    <td>{{ item.owner_username }}</td>
                    <td class="file-name">{{ item.document_filename }}</td>
                    <td>{{ kgItemKindLabel(item.target_kind) }} · {{ item.target_id }}</td>
                    <td>{{ annotationTagsText(item.tags) }}</td>
                    <td>{{ item.note || '-' }}</td>
                    <td>{{ formatDate(item.updated_at) }}</td>
                  </tr>
                </tbody>
              </table>
              <div
                v-if="(selectedOverview.graph_annotations ?? []).length === 0"
                class="empty-table-state"
              >
                该用户暂无人工标注记录。
              </div>
            </div>
          </section>
        </div>
      </template>
    </section>
  </main>
</template>
