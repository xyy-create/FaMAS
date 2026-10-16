<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import {
  activateDocumentSchema,
  createDocumentSchema,
  createDocumentSchemaTemplate,
  createKnowledgeBase,
  deleteKnowledgeBase,
  deleteDocument,
  deleteDocumentsBatch,
  getDocumentJobLogs,
  listDocumentJobs,
  listDocumentSchemas,
  listDocuments,
  listKnowledgeBases,
  rewriteDocumentSchemaWithLlm,
  startDocumentProcessing,
  updateDocumentSchema,
  updateKnowledgeBase,
  updateDocumentMetadata,
  uploadPdf,
} from '../lib/api'
import {
  displayKnowledgeBaseName,
  displayMetadataText,
  displayValue,
  normalizeDisplayInput,
} from '../lib/display'
import DocumentDetailPanel from '../components/DocumentDetailPanel.vue'

const props = defineProps({
  token: {
    type: String,
    required: true,
  },
})

const knowledgeBases = ref([])
const documents = ref([])
const selectedKnowledgeBaseId = ref(null)
const newKnowledgeBaseName = ref('')
const editingKnowledgeBaseName = ref('')
const selectedFile = ref(null)
const isLoading = ref(false)
const isUploading = ref(false)
const isBatchDeleting = ref(false)
const isSavingKnowledgeBase = ref(false)
const knowledgeBaseAction = ref('')
const uploadProgress = ref(null)
const processingAction = ref('')
const errorMessage = ref('')
const successMessage = ref('')
const selectedDocument = ref(null)
const selectedDocumentIds = ref(new Set())
const selectedJobs = ref([])
const selectedJobLogs = ref(null)
const schemaVersions = ref([])
const selectedSchemaId = ref(null)
const schemaEditTitle = ref('')
const schemaEditPrompt = ref('')
const schemaEditJson = ref('')
const schemaRewriteInstruction = ref('')
const schemaBuildVersionId = ref('active')
const compareSchemaId = ref(null)
const isLoadingDetails = ref(false)
const isLoadingSchemas = ref(false)
const isSavingMetadata = ref(false)
const schemaAction = ref('')
const metadataEdit = ref({
  subject: '',
  grade: '',
  publisher: '',
  textbook: '',
  textbook_version: '',
})
let refreshTimer = null

const activeKnowledgeBase = computed(() =>
  knowledgeBases.value.find((item) => item.id === selectedKnowledgeBaseId.value),
)
const activeKnowledgeBaseName = computed(() => displayKnowledgeBaseName(activeKnowledgeBase.value?.name))
const canManageActiveKnowledgeBase = computed(() =>
  Boolean(activeKnowledgeBase.value && !activeKnowledgeBase.value.is_system),
)
const hasActiveJob = computed(() =>
  documents.value.some((document) => ['pending', 'running'].includes(document.latest_job?.status)),
)
const selectedDocumentIdList = computed(() => Array.from(selectedDocumentIds.value))
const selectedDocumentCount = computed(() => selectedDocumentIds.value.size)
const allDocumentsSelected = computed(
  () =>
    documents.value.length > 0 &&
    documents.value.every((document) => selectedDocumentIds.value.has(document.id)),
)
const selectedSchemaVersion = computed(() =>
  schemaVersions.value.find((version) => version.id === selectedSchemaId.value) ?? null,
)
const activeSchemaVersion = computed(() =>
  schemaVersions.value.find((version) => version.is_active) ?? null,
)
const compareSchemaVersion = computed(() =>
  schemaVersions.value.find((version) => version.id === compareSchemaId.value) ?? null,
)
const availableCompareSchemas = computed(() =>
  schemaVersions.value.filter((version) => version.id !== selectedSchemaId.value),
)
const schemaFormPreview = computed(() => {
  try {
    const schema = JSON.parse(schemaEditJson.value || '{}')
    if (!schema || Array.isArray(schema) || typeof schema !== 'object') {
      throw new Error('Schema 必须是 JSON 对象。')
    }
    return {
      invalid: false,
      nodeTypes: Array.isArray(schema.node_types) ? schema.node_types : [],
      relationTypes: Array.isArray(schema.relation_types) ? schema.relation_types : [],
      extractionRules: Array.isArray(schema.extraction_rules) ? schema.extraction_rules : [],
      qualityConstraints: Array.isArray(schema.quality_constraints) ? schema.quality_constraints : [],
    }
  } catch (error) {
    return {
      invalid: true,
      error: error.message || 'Schema JSON 格式不正确。',
      nodeTypes: [],
      relationTypes: [],
      extractionRules: [],
      qualityConstraints: [],
    }
  }
})
const schemaComparison = computed(() => {
  if (!selectedSchemaVersion.value || !compareSchemaVersion.value) {
    return null
  }
  const current = selectedSchemaVersion.value.schema ?? {}
  const target = compareSchemaVersion.value.schema ?? {}
  return {
    nodes: compareSchemaObjectList(current.node_types, target.node_types, 'type'),
    relations: compareSchemaObjectList(current.relation_types, target.relation_types, 'type'),
    extractionRules: compareSchemaTextList(current.extraction_rules, target.extraction_rules),
    qualityConstraints: compareSchemaTextList(current.quality_constraints, target.quality_constraints),
  }
})

async function loadKnowledgeBases() {
  knowledgeBases.value = await listKnowledgeBases(props.token)
  if (!selectedKnowledgeBaseId.value && knowledgeBases.value.length > 0) {
    selectedKnowledgeBaseId.value = knowledgeBases.value[0].id
  }
  if (selectedKnowledgeBaseId.value && !knowledgeBases.value.some((item) => item.id === selectedKnowledgeBaseId.value)) {
    selectedKnowledgeBaseId.value = knowledgeBases.value[0]?.id ?? null
  }
  editingKnowledgeBaseName.value = activeKnowledgeBase.value?.name ?? ''
}

async function loadDocuments() {
  if (!selectedKnowledgeBaseId.value) {
    documents.value = []
    selectedDocumentIds.value = new Set()
    return
  }
  documents.value = await listDocuments(props.token, selectedKnowledgeBaseId.value)
  const visibleIds = new Set(documents.value.map((document) => document.id))
  selectedDocumentIds.value = new Set(
    Array.from(selectedDocumentIds.value).filter((documentId) => visibleIds.has(documentId)),
  )
  if (selectedDocument.value) {
    const updatedDocument = documents.value.find((document) => document.id === selectedDocument.value.id)
    if (updatedDocument) {
      selectedDocument.value = updatedDocument
    } else {
      selectedDocument.value = null
      selectedJobs.value = []
      selectedJobLogs.value = null
      clearSchemaWorkspace()
    }
  }
}

async function handleKnowledgeBaseChange() {
  selectedDocument.value = null
  selectedDocumentIds.value = new Set()
  selectedJobs.value = []
  selectedJobLogs.value = null
  clearSchemaWorkspace()
  editingKnowledgeBaseName.value = activeKnowledgeBase.value?.name ?? ''
  await loadDocuments()
}

async function refreshData() {
  isLoading.value = true
  errorMessage.value = ''
  try {
    await loadKnowledgeBases()
    await loadDocuments()
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isLoading.value = false
  }
}

function startAutoRefresh() {
  refreshTimer = window.setInterval(async () => {
    if (hasActiveJob.value && !isLoading.value && !isUploading.value) {
      await loadDocuments()
    }
  }, 5000)
}

function handleFileChange(event) {
  const [file] = event.target.files
  selectedFile.value = file ?? null
  successMessage.value = ''
  errorMessage.value = ''
}

async function submitUpload() {
  if (!selectedFile.value || !selectedKnowledgeBaseId.value) return
  isUploading.value = true
  uploadProgress.value = {
    phase: 'starting',
    uploaded_chunks: 0,
    total_chunks: 0,
    uploaded_bytes: 0,
    total_bytes: selectedFile.value.size,
    percent: 0,
  }
  errorMessage.value = ''
  successMessage.value = ''
  try {
    await uploadPdf(
      props.token,
      selectedKnowledgeBaseId.value,
      selectedFile.value,
      {},
      (progress) => {
        uploadProgress.value = progress
      },
    )
    successMessage.value = 'PDF 已上传'
    selectedFile.value = null
    await loadDocuments()
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isUploading.value = false
    uploadProgress.value = null
  }
}

async function createKnowledgeBaseFromForm() {
  const name = newKnowledgeBaseName.value.trim()
  if (!name) return
  isSavingKnowledgeBase.value = true
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const created = await createKnowledgeBase(props.token, name)
    newKnowledgeBaseName.value = ''
    await loadKnowledgeBases()
    selectedKnowledgeBaseId.value = created.id
    editingKnowledgeBaseName.value = created.name
    await handleKnowledgeBaseChange()
    successMessage.value = '知识库已创建'
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isSavingKnowledgeBase.value = false
  }
}

async function renameActiveKnowledgeBase() {
  if (!activeKnowledgeBase.value) return
  const name = editingKnowledgeBaseName.value.trim()
  if (!name || name === activeKnowledgeBase.value.name) return
  knowledgeBaseAction.value = 'rename'
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const updated = await updateKnowledgeBase(props.token, activeKnowledgeBase.value.id, name)
    await loadKnowledgeBases()
    selectedKnowledgeBaseId.value = updated.id
    editingKnowledgeBaseName.value = updated.name
    successMessage.value = '知识库名称已更新'
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    knowledgeBaseAction.value = ''
  }
}

async function removeActiveKnowledgeBase() {
  if (!activeKnowledgeBase.value) return
  const confirmed = window.confirm(`确认删除知识库 ${activeKnowledgeBase.value.name}？其中的文档会一起从当前列表中移除。`)
  if (!confirmed) return
  knowledgeBaseAction.value = 'delete'
  errorMessage.value = ''
  successMessage.value = ''
  try {
    await deleteKnowledgeBase(props.token, activeKnowledgeBase.value.id)
    selectedKnowledgeBaseId.value = null
    selectedDocument.value = null
    selectedDocumentIds.value = new Set()
    selectedJobs.value = []
    selectedJobLogs.value = null
    clearSchemaWorkspace()
    await loadKnowledgeBases()
    await loadDocuments()
    successMessage.value = '知识库已删除'
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    knowledgeBaseAction.value = ''
  }
}

async function startProcessing(document, stage, options = {}) {
  processingAction.value = `${stage}:${document.id}`
  errorMessage.value = ''
  successMessage.value = ''
  try {
    await startDocumentProcessing(props.token, document.id, stage, options)
    successMessage.value = `${stageLabel(stage)} 任务已创建`
    await loadDocuments()
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    processingAction.value = ''
  }
}

async function viewDocument(document) {
  selectedDocument.value = document
  metadataEdit.value = metadataFromDocument(document)
  selectedJobLogs.value = null
  clearSchemaWorkspace()
  isLoadingDetails.value = true
  errorMessage.value = ''
  try {
    selectedJobs.value = await listDocumentJobs(props.token, document.id)
    await loadSchemaVersions(document.id)
    if (selectedJobs.value.length > 0) {
      await viewJobLogs(selectedJobs.value[0])
    }
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isLoadingDetails.value = false
  }
}

async function closeDocumentDetail() {
  selectedDocument.value = null
  selectedJobs.value = []
  selectedJobLogs.value = null
  clearSchemaWorkspace()
}

async function refreshSelectedDocumentDetail() {
  if (!selectedDocument.value) return
  await viewDocument(selectedDocument.value)
}

async function loadSchemaVersions(documentId = selectedDocument.value?.id) {
  if (!documentId) return
  isLoadingSchemas.value = true
  try {
    schemaVersions.value = await listDocumentSchemas(props.token, documentId)
    const preferred = activeSchemaVersion.value ?? schemaVersions.value[0] ?? null
    selectSchemaVersion(preferred)
  } finally {
    isLoadingSchemas.value = false
  }
}

function selectSchemaVersion(version) {
  selectedSchemaId.value = version?.id ?? null
  schemaEditTitle.value = version?.title ?? ''
  schemaEditPrompt.value = version?.prompt_text ?? ''
  schemaEditJson.value = version ? JSON.stringify(version.schema ?? {}, null, 2) : ''
  if (version?.id) {
    schemaBuildVersionId.value = String(version.id)
    if (compareSchemaId.value === version.id) {
      compareSchemaId.value = schemaVersions.value.find((item) => item.id !== version.id)?.id ?? null
    }
  }
}

function updateSchemaJson(mutator) {
  const schema = parseSchemaEditorJson()
  mutator(schema)
  schemaEditJson.value = JSON.stringify(schema, null, 2)
}

function ensureSchemaObjectArray(schema, key) {
  if (!Array.isArray(schema[key])) {
    schema[key] = []
  }
  schema[key] = schema[key].map((item) => (item && typeof item === 'object' && !Array.isArray(item) ? item : {}))
  return schema[key]
}

function ensureSchemaTextArray(schema, key) {
  if (!Array.isArray(schema[key])) {
    schema[key] = []
  }
  schema[key] = schema[key].map((item) => String(item ?? ''))
  return schema[key]
}

function updateSchemaObjectItem(key, index, field, value) {
  try {
    updateSchemaJson((schema) => {
      const items = ensureSchemaObjectArray(schema, key)
      if (!items[index]) return
      items[index] = {
        ...items[index],
        [field]: value,
      }
    })
  } catch (error) {
    errorMessage.value = error.message
  }
}

function addSchemaObjectItem(key, defaults) {
  try {
    updateSchemaJson((schema) => {
      ensureSchemaObjectArray(schema, key).push(defaults)
    })
  } catch (error) {
    errorMessage.value = error.message
  }
}

function removeSchemaArrayItem(key, index) {
  try {
    updateSchemaJson((schema) => {
      if (!Array.isArray(schema[key])) return
      schema[key].splice(index, 1)
    })
  } catch (error) {
    errorMessage.value = error.message
  }
}

function updateSchemaTextItem(key, index, value) {
  try {
    updateSchemaJson((schema) => {
      const items = ensureSchemaTextArray(schema, key)
      if (index < 0 || index >= items.length) return
      items[index] = value
    })
  } catch (error) {
    errorMessage.value = error.message
  }
}

function addSchemaTextItem(key, value = '') {
  try {
    updateSchemaJson((schema) => {
      ensureSchemaTextArray(schema, key).push(value)
    })
  } catch (error) {
    errorMessage.value = error.message
  }
}

function compareSchemaObjectList(currentItems, targetItems, keyField) {
  const currentMap = schemaObjectMap(currentItems, keyField)
  const targetMap = schemaObjectMap(targetItems, keyField)
  return Array.from(new Set([...currentMap.keys(), ...targetMap.keys()]))
    .sort((left, right) => left.localeCompare(right))
    .map((key) => {
      const current = currentMap.get(key)
      const target = targetMap.get(key)
      if (!current) {
        return { key, label: schemaCompareLabel(target, key), status: 'added', statusLabel: '仅对比版本有' }
      }
      if (!target) {
        return { key, label: schemaCompareLabel(current, key), status: 'removed', statusLabel: '仅当前版本有' }
      }
      if (stableJson(current) !== stableJson(target)) {
        return {
          key,
          label: schemaCompareLabel(current, key),
          status: 'changed',
          statusLabel: '内容不同',
          currentText: current.description || '',
          targetText: target.description || '',
        }
      }
      return { key, label: schemaCompareLabel(current, key), status: 'same', statusLabel: '一致' }
    })
}

function compareSchemaTextList(currentItems, targetItems) {
  const currentSet = new Set((Array.isArray(currentItems) ? currentItems : []).map((item) => String(item ?? '')))
  const targetSet = new Set((Array.isArray(targetItems) ? targetItems : []).map((item) => String(item ?? '')))
  return Array.from(new Set([...currentSet, ...targetSet]))
    .filter((item) => item.trim())
    .sort((left, right) => left.localeCompare(right))
    .map((text) => {
      if (!currentSet.has(text)) return { key: text, label: text, status: 'added', statusLabel: '仅对比版本有' }
      if (!targetSet.has(text)) return { key: text, label: text, status: 'removed', statusLabel: '仅当前版本有' }
      return { key: text, label: text, status: 'same', statusLabel: '一致' }
    })
}

function schemaObjectMap(items, keyField) {
  const map = new Map()
  if (!Array.isArray(items)) return map
  for (const item of items) {
    if (!item || Array.isArray(item) || typeof item !== 'object') continue
    const key = String(item[keyField] || item.display_name || item.name || '').trim()
    if (key) {
      map.set(key, item)
    }
  }
  return map
}

function schemaCompareLabel(item, fallback) {
  if (!item || Array.isArray(item) || typeof item !== 'object') return fallback
  return item.display_name ? `${item.display_name}（${fallback}）` : fallback
}

function stableJson(value) {
  if (!value || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return JSON.stringify(value.map((item) => stableJsonObject(item)))
  return JSON.stringify(stableJsonObject(value))
}

function stableJsonObject(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return value
  return Object.keys(value)
    .sort()
    .reduce((result, key) => {
      result[key] = stableJsonObject(value[key])
      return result
    }, {})
}

async function generateSystemSchemaTemplate() {
  if (!selectedDocument.value) return
  schemaAction.value = 'template'
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const created = await createDocumentSchemaTemplate(props.token, selectedDocument.value.id, {
      title: '系统推荐 schema',
      prompt_text: schemaEditPrompt.value,
      activate: schemaVersions.value.length === 0,
    })
    await loadSchemaVersions(selectedDocument.value.id)
    selectSchemaVersion(created)
    successMessage.value = '系统推荐 schema 已生成'
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    schemaAction.value = ''
  }
}

async function copySelectedSchema() {
  if (!selectedDocument.value || !selectedSchemaVersion.value) return
  schemaAction.value = 'copy'
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const created = await createDocumentSchema(props.token, selectedDocument.value.id, {
      title: `${selectedSchemaVersion.value.title} 副本`,
      prompt_text: schemaEditPrompt.value,
      schema: parseSchemaEditorJson(),
      activate: false,
    })
    await loadSchemaVersions(selectedDocument.value.id)
    selectSchemaVersion(created)
    successMessage.value = 'schema 副本已创建'
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    schemaAction.value = ''
  }
}

async function saveSelectedSchema() {
  if (!selectedDocument.value || !selectedSchemaVersion.value) return
  schemaAction.value = 'save'
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const updated = await updateDocumentSchema(
      props.token,
      selectedDocument.value.id,
      selectedSchemaVersion.value.id,
      {
        title: schemaEditTitle.value,
        prompt_text: schemaEditPrompt.value,
        schema: parseSchemaEditorJson(),
      },
    )
    await loadSchemaVersions(selectedDocument.value.id)
    selectSchemaVersion(updated)
    successMessage.value = 'schema 已保存'
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    schemaAction.value = ''
  }
}

async function activateSelectedSchema() {
  if (!selectedDocument.value || !selectedSchemaVersion.value) return
  schemaAction.value = 'activate'
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const activated = await activateDocumentSchema(
      props.token,
      selectedDocument.value.id,
      selectedSchemaVersion.value.id,
    )
    await loadSchemaVersions(selectedDocument.value.id)
    selectSchemaVersion(activated)
    successMessage.value = 'schema 已设为启用版本'
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    schemaAction.value = ''
  }
}

async function rewriteSchemaWithLlm(preset = '') {
  if (!selectedDocument.value || !selectedSchemaVersion.value) return
  schemaAction.value = preset ? `llm:${preset}` : 'llm'
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const created = await rewriteDocumentSchemaWithLlm(
      props.token,
      selectedDocument.value.id,
      selectedSchemaVersion.value.id,
      {
        preset,
        instruction: schemaRewriteInstruction.value || schemaEditPrompt.value,
        provider: 'dashscope',
        activate: false,
      },
    )
    await loadSchemaVersions(selectedDocument.value.id)
    selectSchemaVersion(created)
    successMessage.value = '模型辅助修改已生成新 schema 版本'
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    schemaAction.value = ''
  }
}

async function startBuildGraphWithSelectedSchema() {
  if (!selectedDocument.value) return
  const schemaVersionId = schemaBuildVersionId.value === 'active' ? null : Number(schemaBuildVersionId.value)
  await startProcessing(
    selectedDocument.value,
    'build_graph',
    schemaVersionId ? { schema_version_id: schemaVersionId } : {},
  )
}

function parseSchemaEditorJson() {
  try {
    const parsed = JSON.parse(schemaEditJson.value)
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
      throw new Error('Schema 必须是 JSON 对象。')
    }
    return parsed
  } catch (error) {
    throw new Error(error.message || 'Schema JSON 格式不正确。')
  }
}

function clearSchemaWorkspace() {
  schemaVersions.value = []
  selectedSchemaId.value = null
  schemaEditTitle.value = ''
  schemaEditPrompt.value = ''
  schemaEditJson.value = ''
  schemaRewriteInstruction.value = ''
  schemaBuildVersionId.value = 'active'
  compareSchemaId.value = null
}

async function saveDocumentMetadata() {
  if (!selectedDocument.value) return
  isSavingMetadata.value = true
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const updatedDocument = await updateDocumentMetadata(
      props.token,
      selectedDocument.value.id,
      normalizeDocumentMetadata(metadataEdit.value),
    )
    selectedDocument.value = updatedDocument
    metadataEdit.value = metadataFromDocument(updatedDocument)
    successMessage.value = '文档信息已保存'
    await loadDocuments()
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isSavingMetadata.value = false
  }
}

async function viewJobLogs(job) {
  if (!selectedDocument.value) return
  isLoadingDetails.value = true
  errorMessage.value = ''
  try {
    selectedJobLogs.value = {
      job,
      logs: await getDocumentJobLogs(props.token, selectedDocument.value.id, job.id),
    }
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isLoadingDetails.value = false
  }
}

async function removeDocument(document) {
  const confirmed = window.confirm(`确认删除 ${document.filename}？`)
  if (!confirmed) return
  errorMessage.value = ''
  successMessage.value = ''
  try {
    await deleteDocument(props.token, document.id)
    successMessage.value = '文档已删除'
    selectedDocumentIds.value = new Set(
      Array.from(selectedDocumentIds.value).filter((documentId) => documentId !== document.id),
    )
    if (selectedDocument.value?.id === document.id) {
      selectedDocument.value = null
      selectedJobs.value = []
      selectedJobLogs.value = null
    }
    await loadDocuments()
  } catch (error) {
    errorMessage.value = error.message
  }
}

async function removeSelectedDocuments() {
  const documentIds = selectedDocumentIdList.value
  if (documentIds.length === 0) return
  const confirmed = window.confirm(`确认删除已选的 ${documentIds.length} 个文档？`)
  if (!confirmed) return
  isBatchDeleting.value = true
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const result = await deleteDocumentsBatch(props.token, documentIds)
    successMessage.value = `已删除 ${result.deleted_count} 个文档`
    if (selectedDocument.value && documentIds.includes(selectedDocument.value.id)) {
      selectedDocument.value = null
      selectedJobs.value = []
      selectedJobLogs.value = null
    }
    selectedDocumentIds.value = new Set()
    await loadDocuments()
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isBatchDeleting.value = false
  }
}

function toggleDocumentSelection(documentId, checked) {
  const next = new Set(selectedDocumentIds.value)
  if (checked) {
    next.add(documentId)
  } else {
    next.delete(documentId)
  }
  selectedDocumentIds.value = next
}

function toggleAllDocuments(checked) {
  selectedDocumentIds.value = checked
    ? new Set(documents.value.map((document) => document.id))
    : new Set()
}

function formatSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`
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

function statusClass(status) {
  return `status-${status.toLowerCase().replaceAll(' ', '-')}`
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

function canBuildGraph(document) {
  return ['parsed', 'graph_ready', 'success', 'failed'].includes(document.status)
}

function isProcessing(document, stage) {
  return processingAction.value === `${stage}:${document.id}`
}

function latestJobLabel(document) {
  if (!document.latest_job) return '-'
  return `${stageLabel(document.latest_job.stage)} / ${jobStatusLabel(document.latest_job.status)}`
}

function documentMetadataLabel(document) {
  return displayMetadataText(document.subject, document.grade, document.publisher)
}

function uploadProgressLabel() {
  if (!uploadProgress.value) return ''
  if (uploadProgress.value.phase === 'finalizing') {
    return '正在完成上传'
  }
  if (uploadProgress.value.phase === 'retrying') {
    return uploadProgress.value.message ?? '正在重试上传'
  }
  if (uploadProgress.value.phase === 'starting') {
    return '正在准备上传'
  }
  const chunkText =
    uploadProgress.value.chunk_index && uploadProgress.value.total_chunks
      ? ` · 分片 ${uploadProgress.value.chunk_index}/${uploadProgress.value.total_chunks}`
      : ''
  return `正在上传 ${uploadProgress.value.percent}%${chunkText}`
}

function metadataFromDocument(document) {
  return {
    subject: displayValue(document.subject),
    grade: displayValue(document.grade),
    publisher: displayValue(document.publisher),
    textbook: displayValue(document.textbook),
    textbook_version: displayValue(document.textbook_version),
  }
}

function normalizeDocumentMetadata(metadata) {
  return {
    subject: normalizeDisplayInput(metadata.subject),
    grade: normalizeDisplayInput(metadata.grade),
    publisher: normalizeDisplayInput(metadata.publisher),
    textbook: metadata.textbook?.trim() ?? '',
    textbook_version: normalizeDisplayInput(metadata.textbook_version),
  }
}

function schemaSourceLabel(source) {
  const labels = {
    system: '系统推荐',
    user: '用户编辑',
    llm: '模型辅助',
  }
  return labels[String(source || '').toLowerCase()] ?? '自定义'
}

function schemaVersionLabel(version) {
  if (!version) return '未选择'
  return `v${version.version_number} · ${schemaSourceLabel(version.source)}`
}

function schemaSummary(version) {
  const schema = version?.schema ?? {}
  const nodeCount = Array.isArray(schema.node_types) ? schema.node_types.length : 0
  const relationCount = Array.isArray(schema.relation_types) ? schema.relation_types.length : 0
  return `${nodeCount} 类节点 / ${relationCount} 类关系`
}

onMounted(async () => {
  await refreshData()
  startAutoRefresh()
})

onBeforeUnmount(() => {
  if (refreshTimer) {
    window.clearInterval(refreshTimer)
  }
})
</script>

<template>
  <main class="workspace">
    <section class="page-header">
      <div>
        <p class="eyebrow">文档</p>
        <h1>PDF 处理工作台</h1>
      </div>
      <button class="secondary-button" type="button" :disabled="isLoading" @click="refreshData">
        刷新
      </button>
    </section>

    <p v-if="errorMessage" class="error-message page-message">{{ errorMessage }}</p>
    <p v-if="successMessage" class="success-message page-message">{{ successMessage }}</p>

    <section class="upload-panel">
      <div>
        <h2>上传 PDF</h2>
        <p>
          文件会进入 {{ activeKnowledgeBaseName }}。如果 PDF 中包含课程信息，系统会自动识别。
        </p>
      </div>

      <div class="knowledge-base-controls">
        <label class="form-field">
          <span>当前知识库</span>
          <select
            v-model.number="selectedKnowledgeBaseId"
            :disabled="isLoading || knowledgeBases.length === 0"
            @change="handleKnowledgeBaseChange"
          >
            <option v-for="kb in knowledgeBases" :key="kb.id" :value="kb.id">
              {{ displayKnowledgeBaseName(kb.name) }}（{{ kb.document_count }}）
            </option>
          </select>
        </label>

        <form class="inline-form" @submit.prevent="createKnowledgeBaseFromForm">
          <label class="form-field">
            <span>新建知识库</span>
            <input v-model="newKnowledgeBaseName" type="text" placeholder="输入名称" maxlength="80" />
          </label>
          <button class="secondary-button" type="submit" :disabled="isSavingKnowledgeBase || !newKnowledgeBaseName.trim()">
            {{ isSavingKnowledgeBase ? '创建中...' : '创建' }}
          </button>
        </form>

        <form class="inline-form" @submit.prevent="renameActiveKnowledgeBase">
          <label class="form-field">
            <span>重命名</span>
            <input
              v-model="editingKnowledgeBaseName"
              type="text"
              placeholder="当前知识库名称"
              maxlength="80"
              :disabled="!canManageActiveKnowledgeBase"
            />
          </label>
          <button
            class="secondary-button"
            type="submit"
            :disabled="!canManageActiveKnowledgeBase || knowledgeBaseAction === 'rename' || !editingKnowledgeBaseName.trim()"
          >
            {{ knowledgeBaseAction === 'rename' ? '保存中...' : '保存' }}
          </button>
          <button
            class="secondary-button danger"
            type="button"
            :disabled="!canManageActiveKnowledgeBase || knowledgeBaseAction === 'delete'"
            @click="removeActiveKnowledgeBase"
          >
            {{ knowledgeBaseAction === 'delete' ? '删除中...' : '删除知识库' }}
          </button>
        </form>
      </div>

      <div class="upload-actions">
        <label class="secondary-button file-picker">
          选择文件
          <input type="file" accept="application/pdf,.pdf" @change="handleFileChange" />
        </label>
        <span class="selected-file">{{ selectedFile?.name ?? '未选择文件' }}</span>
        <button
          class="primary-button"
          type="button"
          :disabled="!selectedFile || isUploading"
          @click="submitUpload"
        >
          {{ isUploading ? '上传中...' : '上传 PDF' }}
        </button>
      </div>

      <div v-if="uploadProgress" class="upload-progress">
        <div class="upload-progress-head">
          <strong>{{ uploadProgressLabel() }}</strong>
          <span>{{ uploadProgress.percent }}%</span>
        </div>
        <div class="progress-track">
          <div class="progress-fill" :style="{ width: `${uploadProgress.percent}%` }"></div>
        </div>
        <small>
          {{ formatSize(uploadProgress.uploaded_bytes) }} / {{ formatSize(uploadProgress.total_bytes) }}
        </small>
      </div>
    </section>

    <section class="content-panel table-panel">
      <div class="panel-header">
        <div>
          <h2>文档列表</h2>
          <p>{{ documents.length }} 个文件，位于 {{ activeKnowledgeBaseName }}</p>
        </div>
        <button
          class="secondary-button danger"
          type="button"
          :disabled="selectedDocumentCount === 0 || isBatchDeleting"
          @click="removeSelectedDocuments"
        >
          {{ isBatchDeleting ? '删除中...' : `删除已选 ${selectedDocumentCount}` }}
        </button>
      </div>

      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th class="select-cell">
                <input
                  type="checkbox"
                  aria-label="选择全部文档"
                  :checked="allDocumentsSelected"
                  :disabled="documents.length === 0"
                  @change="toggleAllDocuments($event.target.checked)"
                />
              </th>
              <th>文件名</th>
              <th>信息</th>
              <th>上传时间</th>
              <th>大小</th>
              <th>状态</th>
              <th>开始时间</th>
              <th>完成时间</th>
              <th>最新任务</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="document in documents" :key="document.id">
              <tr :class="{ 'document-row-selected': selectedDocument?.id === document.id }">
                <td class="select-cell">
                  <input
                    type="checkbox"
                    :aria-label="`选择 ${document.filename}`"
                    :checked="selectedDocumentIds.has(document.id)"
                    @change="toggleDocumentSelection(document.id, $event.target.checked)"
                  />
                </td>
                <td class="file-name">{{ document.filename }}</td>
                <td>{{ documentMetadataLabel(document) }}</td>
                <td>{{ formatDate(document.uploaded_at) }}</td>
                <td>{{ formatSize(document.file_size_bytes) }}</td>
                <td>
                  <span class="status-badge" :class="statusClass(document.status)">
                    {{ documentStatusLabel(document.status) }}
                  </span>
                </td>
                <td>{{ formatDate(document.processing_started_at) }}</td>
                <td>{{ formatDate(document.processing_completed_at) }}</td>
                <td>
                  <div class="job-cell">
                    <span>{{ latestJobLabel(document) }}</span>
                    <small
                      v-if="document.latest_job?.error_message"
                      :class="{ 'job-warning': document.latest_job?.status === 'degraded' }"
                    >
                      {{ document.latest_job.error_message }}
                    </small>
                  </div>
                </td>
                <td>
                  <div class="row-actions">
                    <button
                      class="text-button"
                      type="button"
                      :disabled="Boolean(processingAction)"
                      @click="startProcessing(document, 'parse_pdf')"
                    >
                      {{ isProcessing(document, 'parse_pdf') ? '启动中...' : '解析 PDF' }}
                    </button>
                    <button
                      class="text-button"
                      type="button"
                      :disabled="Boolean(processingAction) || !canBuildGraph(document)"
                      @click="startProcessing(document, 'build_graph')"
                    >
                      {{ isProcessing(document, 'build_graph') ? '启动中...' : '构建图谱' }}
                    </button>
                    <button class="text-button" type="button" @click="viewDocument(document)">
                      查看
                    </button>
                    <button class="text-button danger" type="button" @click="removeDocument(document)">
                      删除
                    </button>
                  </div>
                </td>
              </tr>
              <tr v-if="selectedDocument?.id === document.id" class="document-detail-row">
                <td :colspan="10">
                  <DocumentDetailPanel
                    :selected-document="selectedDocument"
                    :selected-jobs="selectedJobs"
                    :selected-job-logs="selectedJobLogs"
                    :schema-versions="schemaVersions"
                    :selected-schema-id="selectedSchemaId"
                    :compare-schema-id="compareSchemaId"
                    :schema-edit-title="schemaEditTitle"
                    :schema-edit-prompt="schemaEditPrompt"
                    :schema-edit-json="schemaEditJson"
                    :schema-rewrite-instruction="schemaRewriteInstruction"
                    :schema-build-version-id="schemaBuildVersionId"
                    :is-loading-details="isLoadingDetails"
                    :is-loading-schemas="isLoadingSchemas"
                    :is-saving-metadata="isSavingMetadata"
                    :schema-action="schemaAction"
                    :metadata-edit="metadataEdit"
                    :schema-form-preview="schemaFormPreview"
                    :schema-comparison="schemaComparison"
                    :available-compare-schemas="availableCompareSchemas"
                    :can-build-graph="canBuildGraph"
                    :format-date="formatDate"
                    :format-size="formatSize"
                    :document-status-label="documentStatusLabel"
                    :display-value="displayValue"
                    :schema-version-label="schemaVersionLabel"
                    :schema-summary="schemaSummary"
                    :stage-label="stageLabel"
                    :job-status-label="jobStatusLabel"
                    @close="closeDocumentDetail"
                    @refresh="refreshSelectedDocumentDetail"
                    @generate-template="generateSystemSchemaTemplate"
                    @select-schema="selectSchemaVersion"
                    @save-schema="saveSelectedSchema"
                    @copy-schema="copySelectedSchema"
                    @activate-schema="activateSelectedSchema"
                    @rewrite-schema="rewriteSchemaWithLlm"
                    @build-graph="startBuildGraphWithSelectedSchema"
                    @view-job="viewJobLogs"
                    @save-metadata="saveDocumentMetadata"
                    @add-schema-object-item="addSchemaObjectItem"
                    @update-schema-object-item="updateSchemaObjectItem"
                    @remove-schema-array-item="removeSchemaArrayItem"
                    @add-schema-text-item="addSchemaTextItem"
                    @update-schema-text-item="updateSchemaTextItem"
                    @update:schemaEditTitle="schemaEditTitle = $event"
                    @update:schemaEditPrompt="schemaEditPrompt = $event"
                    @update:schemaEditJson="schemaEditJson = $event"
                    @update:schemaRewriteInstruction="schemaRewriteInstruction = $event"
                    @update:schemaBuildVersionId="schemaBuildVersionId = $event"
                    @update:compareSchemaId="compareSchemaId = $event"
                  />
                </td>
              </tr>
            </template>
          </tbody>
        </table>

        <div v-if="!isLoading && documents.length === 0" class="empty-table-state">
          暂无已上传文档。
        </div>
      </div>
    </section>
  </main>
</template>


