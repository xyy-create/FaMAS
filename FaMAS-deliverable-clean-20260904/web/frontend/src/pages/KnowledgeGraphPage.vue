<script setup>
import { computed, onMounted, ref, watch } from 'vue'

import {
  getKnowledgeGraphSummary,
  listDocuments,
  listKnowledgeBases,
} from '../lib/api'
import {
  displayKnowledgeBaseName,
  displayMetadataText,
} from '../lib/display'

const props = defineProps({
  token: {
    type: String,
    required: true,
  },
})

const knowledgeBases = ref([])
const documents = ref([])
const selectedKnowledgeBaseId = ref(null)
const selectedDocumentId = ref('all')
const graphSummary = ref(null)
const isLoading = ref(false)
const errorMessage = ref('')
const refreshVersion = ref(0)

const activeKnowledgeBase = computed(() =>
  knowledgeBases.value.find((item) => item.id === selectedKnowledgeBaseId.value),
)

const activeKnowledgeBaseName = computed(() => displayKnowledgeBaseName(activeKnowledgeBase.value?.name))

const hasRenderableGraph = computed(
  () => graphSummary.value?.source === 'processed' && (graphSummary.value?.processed_run_ids?.length ?? 0) > 0,
)

const graphSourceLabel = computed(() => {
  if (!graphSummary.value) return '加载中'
  return hasRenderableGraph.value ? '已处理图谱' : '暂无图谱'
})

const graphSourceBadgeClass = computed(() =>
  !graphSummary.value || isLoading.value
    ? 'status-pending'
    : hasRenderableGraph.value
      ? 'status-graph-ready'
      : 'status-degraded',
)

const metadataSummary = computed(() => {
  const metadata = graphSummary.value?.metadata
  if (!metadata) return ''
  return displayMetadataText(metadata.subject, metadata.grade, metadata.publisher, metadata.textbook)
})

const sourceSummaryText = computed(() =>
  [
    activeKnowledgeBaseName.value,
    graphSourceLabel.value,
    `${formatCount(graphSummary.value?.counts?.nodes)} 个节点`,
    `${formatCount(graphSummary.value?.counts?.edges)} 条边`,
    `${formatCount(graphSummary.value?.counts?.triples)} 条三元组`,
    metadataSummary.value,
  ].filter(Boolean).join(' · '),
)

const shouldCollapseSourceSummary = computed(() => sourceSummaryText.value.length > 70)
const sourceSummaryCollapsed = ref(true)
const isSourceSummaryExpanded = computed(
  () => !shouldCollapseSourceSummary.value || !sourceSummaryCollapsed.value,
)

const iframeSrc = computed(() => {
  if (!selectedKnowledgeBaseId.value || !hasRenderableGraph.value) return ''
  const params = new URLSearchParams({
    api: '1',
    knowledge_base_id: String(selectedKnowledgeBaseId.value),
    v: String(refreshVersion.value),
  })
  if (selectedDocumentId.value !== 'all') {
    params.set('document_id', String(selectedDocumentId.value))
  }
  return `/chemistry/index.html?${params.toString()}`
})

async function loadKnowledgeBases() {
  knowledgeBases.value = await listKnowledgeBases(props.token)
  if (!selectedKnowledgeBaseId.value && knowledgeBases.value.length > 0) {
    selectedKnowledgeBaseId.value = knowledgeBases.value[0].id
  }
}

async function loadDocuments() {
  if (!selectedKnowledgeBaseId.value) return
  documents.value = await listDocuments(props.token, selectedKnowledgeBaseId.value)
  if (
    selectedDocumentId.value !== 'all' &&
    !documents.value.some((document) => String(document.id) === String(selectedDocumentId.value))
  ) {
    selectedDocumentId.value = 'all'
  }
}

async function loadGraphSummary() {
  if (!selectedKnowledgeBaseId.value) return
  const documentId = selectedDocumentId.value === 'all' ? null : selectedDocumentId.value
  graphSummary.value = await getKnowledgeGraphSummary(
    props.token,
    selectedKnowledgeBaseId.value,
    documentId,
  )
}

async function refreshData() {
  isLoading.value = true
  errorMessage.value = ''
  try {
    await loadKnowledgeBases()
    await loadDocuments()
    await loadGraphSummary()
    refreshVersion.value += 1
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isLoading.value = false
  }
}

function formatCount(value) {
  return Number(value ?? 0).toLocaleString()
}

function toggleSourceSummary() {
  if (!shouldCollapseSourceSummary.value) return
  sourceSummaryCollapsed.value = !sourceSummaryCollapsed.value
}

watch(selectedKnowledgeBaseId, async () => {
  selectedDocumentId.value = 'all'
  await refreshData()
})

watch(selectedDocumentId, async () => {
  await refreshData()
})

onMounted(refreshData)
</script>

<template>
  <main class="workspace kg-embed-workspace">
    <section class="page-header kg-embed-header">
      <div>
        <p class="eyebrow">知识图谱</p>
        <h1>知识图谱</h1>
      </div>
      <button class="primary-button" type="button" :disabled="isLoading" @click="refreshData">
        {{ isLoading ? '刷新中...' : '刷新图谱' }}
      </button>
    </section>

    <p v-if="errorMessage" class="error-message page-message">{{ errorMessage }}</p>

    <section class="kg-control-panel">
      <label class="form-field">
        <span>知识库</span>
        <select v-model="selectedKnowledgeBaseId">
          <option v-for="kb in knowledgeBases" :key="kb.id" :value="kb.id">
            {{ displayKnowledgeBaseName(kb.name) }}
          </option>
        </select>
      </label>

      <label class="form-field">
        <span>图谱范围</span>
        <select v-model="selectedDocumentId">
          <option value="all">全部文档</option>
          <option v-for="document in documents" :key="document.id" :value="String(document.id)">
            {{ document.filename }}
          </option>
        </select>
      </label>

      <div
        class="kg-source-summary"
        :class="{ 'is-collapsed': shouldCollapseSourceSummary && sourceSummaryCollapsed }"
      >
        <div class="kg-source-summary-head">
          <span class="status-badge" :class="graphSourceBadgeClass">{{ graphSourceLabel }}</span>
          <button
            v-if="shouldCollapseSourceSummary"
            class="summary-toggle"
            type="button"
            @click="toggleSourceSummary"
          >
            {{ sourceSummaryCollapsed ? '展开' : '收起' }}
          </button>
        </div>
        <div v-show="isSourceSummaryExpanded" class="kg-source-summary-body">
          <strong>{{ activeKnowledgeBaseName }}</strong>
          <span>{{ formatCount(graphSummary?.counts?.nodes) }} 个节点</span>
          <span>{{ formatCount(graphSummary?.counts?.edges) }} 条边</span>
          <span>{{ formatCount(graphSummary?.counts?.triples) }} 条三元组</span>
          <span v-if="metadataSummary">{{ metadataSummary }}</span>
        </div>
      </div>
    </section>

    <section class="kg-embed-panel">
      <iframe
        v-if="hasRenderableGraph"
        :key="iframeSrc"
        class="kg-embed-frame"
        :src="iframeSrc"
        title="知识图谱"
      ></iframe>
      <div v-else class="empty-state kg-embed-empty">
        <div>
          <h2>{{ graphSummary ? '当前知识库暂无可用图谱' : '正在加载图谱信息' }}</h2>
          <p>
            {{
              graphSummary
                ? '该知识库还没有生成可展示的知识图谱，请先在文档页构建图谱。'
                : '请稍候，正在获取知识库图谱状态。'
            }}
          </p>
        </div>
      </div>
    </section>
  </main>
</template>
