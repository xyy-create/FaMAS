<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  API_BASE_URL,
  deleteQaConversation,
  getQaConversation,
  listAvailableModels,
  listApiSettings,
  listDocuments,
  listKnowledgeBases,
  listQaConversations,
  streamRetrievalQa,
} from '../lib/api'
import {
  chineseFirst,
  displayEvidenceKind,
  displayKnowledgeBaseName,
  displayPredicateLabel,
  displayTypeLabel,
  localizeInlineText,
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
const selectedDocumentIds = ref([])
const selectedProvider = ref('dashscope')
const selectedModelName = ref('')
const modelSettings = ref([])
const availableModels = ref({})
const isLoadingModels = ref(false)
const question = ref('')
const messages = ref([])
const conversations = ref([])
const historySearch = ref('')
const activeConversationId = ref(null)
const isLoadingScope = ref(false)
const isLoadingConversations = ref(false)
const isStreaming = ref(false)
const errorMessage = ref('')
const answerMode = ref('free')
const answerStyle = ref('textbook')
const temperature = ref(0.3)
const contextLimit = ref(8)
const maxTokens = ref(1200)
const historyTurns = ref(3)
const activeImage = ref(null)
const activeEvidence = ref(null)
const abortController = ref(null)
const chatPanel = ref(null)
const activeStreamId = ref(0)
const shouldFollowOutput = ref(true)
const activeComposerMenu = ref('')

const ACTIVE_QA_CONVERSATION_KEY = 'shumai_active_qa_conversation_id'

const providerLabels = {
  dashscope: '通义千问',
  deepseek: 'DeepSeek',
}

const answerModeOptions = [
  { id: 'free', label: '通用问答，相关时引用图谱' },
  { id: 'strict', label: '仅依据图谱' },
]

const answerStyleOptions = [
  { id: 'textbook', label: '教材讲解' },
  { id: 'concise', label: '简洁回答' },
  { id: 'exam', label: '考点总结' },
  { id: 'student', label: '学生易懂版' },
]

const providerOptions = computed(() => {
  const providers = ['dashscope', 'deepseek']
  const byProvider = Object.fromEntries(modelSettings.value.map((item) => [item.provider, item]))
  return providers.map((provider) => ({
    id: provider,
    label: providerLabels[provider] ?? provider,
    model: byProvider[provider]?.model_name ?? '',
    hasKey: byProvider[provider]?.has_api_key ?? false,
    keySource: byProvider[provider]?.key_source ?? '',
  }))
})

const selectedProviderInfo = computed(() =>
  providerOptions.value.find((item) => item.id === selectedProvider.value),
)

const selectedModelOptions = computed(() => {
  const models = availableModels.value[selectedProvider.value]?.models ?? []
  const fallbackModel = selectedProviderInfo.value?.model
  if (models.length > 0) return models
  return fallbackModel ? [{ id: fallbackModel, name: fallbackModel }] : []
})

const activeKnowledgeBase = computed(() =>
  knowledgeBases.value.find((item) => item.id === selectedKnowledgeBaseId.value),
)

const activeKnowledgeBaseName = computed(() =>
  displayKnowledgeBaseName(activeKnowledgeBase.value?.name),
)

const selectedDocumentName = computed(() => {
  if (selectedDocumentId.value === 'all') return '全部文档'
  if (selectedDocumentId.value === 'selected') {
    const count = selectedScopeDocumentIds.value.length
    return count ? `已选 ${count} 个 PDF` : '未选择 PDF'
  }
  return documents.value.find((item) => String(item.id) === String(selectedDocumentId.value))?.filename ?? '指定文档'
})

const filteredConversations = computed(() => {
  const keyword = historySearch.value.trim().toLowerCase()
  if (!keyword) return conversations.value
  return conversations.value.filter((conversation) => {
    const title = String(conversation.title || '').toLowerCase()
    const preview = String(conversation.last_message_preview || '').toLowerCase()
    return title.includes(keyword) || preview.includes(keyword)
  })
})

const contextUsagePercent = computed(() => {
  const turns = Math.max(0, Math.min(10, Number(historyTurns.value) || 0))
  if (turns <= 0) return 0
  const maxChars = turns * 2 * 4000
  const usedChars = messages.value
    .filter((message) => ['user', 'assistant'].includes(message.role) && message.content.trim())
    .slice(-turns * 2)
    .reduce((total, message) => total + message.content.length, 0)
  return Math.min(100, Math.round((usedChars / maxChars) * 100))
})

const contextUsageClass = computed(() => {
  if (contextUsagePercent.value >= 85) return 'high'
  if (contextUsagePercent.value >= 60) return 'medium'
  return 'low'
})

const selectedScopeDocumentIds = computed(() => {
  if (selectedDocumentId.value === 'selected') {
    return selectedDocumentIds.value.map((value) => Number(value)).filter((value) => Number.isFinite(value) && value > 0)
  }
  if (selectedDocumentId.value === 'all') return []
  const documentId = Number(selectedDocumentId.value)
  return Number.isFinite(documentId) && documentId > 0 ? [documentId] : []
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
  selectedDocumentIds.value = selectedDocumentIds.value.filter((documentId) =>
    documents.value.some((document) => String(document.id) === String(documentId)),
  )
  if (
    selectedDocumentId.value !== 'all' &&
    selectedDocumentId.value !== 'selected' &&
    !documents.value.some((document) => String(document.id) === String(selectedDocumentId.value))
  ) {
    selectedDocumentId.value = 'all'
  }
}

async function loadModelSettings() {
  modelSettings.value = await listApiSettings(props.token)
  if (!modelSettings.value.some((item) => item.provider === selectedProvider.value && item.has_api_key)) {
    const firstAvailable = modelSettings.value.find((item) => item.has_api_key)
    if (firstAvailable) {
      selectedProvider.value = firstAvailable.provider
    }
  }
  await loadAvailableModelOptions()
  ensureSelectedModel()
}

async function loadAvailableModelOptions() {
  isLoadingModels.value = true
  const providers = providerOptions.value.filter((provider) => provider.hasKey)
  try {
    const results = await Promise.all(
      providers.map(async (provider) => {
        try {
          const result = await listAvailableModels(props.token, provider.id)
          return [provider.id, result]
        } catch (error) {
          return [provider.id, {
            provider: provider.id,
            ok: false,
            message: error.message,
            model_name: provider.model,
            models: provider.model ? [{ id: provider.model, name: provider.model }] : [],
          }]
        }
      }),
    )
    availableModels.value = Object.fromEntries(results)
  } finally {
    isLoadingModels.value = false
  }
}

function ensureSelectedModel() {
  const models = selectedModelOptions.value
  if (models.some((model) => model.id === selectedModelName.value)) return
  selectedModelName.value = selectedProviderInfo.value?.model || models[0]?.id || ''
}

async function loadConversations() {
  if (!selectedKnowledgeBaseId.value) {
    conversations.value = []
    return
  }
  isLoadingConversations.value = true
  try {
    conversations.value = await listQaConversations(props.token, selectedKnowledgeBaseId.value)
  } finally {
    isLoadingConversations.value = false
  }
}

async function refreshScope() {
  isLoadingScope.value = true
  errorMessage.value = ''
  try {
    await loadKnowledgeBases()
    await loadDocuments()
    await loadModelSettings()
    await loadConversations()
    await restoreActiveConversation()
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isLoadingScope.value = false
  }
}

async function askQuestion() {
  const trimmed = question.value.trim()
  if (!trimmed || !selectedKnowledgeBaseId.value || isStreaming.value) return
  if (selectedDocumentId.value === 'selected' && selectedScopeDocumentIds.value.length === 0) {
    errorMessage.value = '请至少选择一个 PDF，或将范围改为全部文档。'
    return
  }
  question.value = ''
  activeComposerMenu.value = ''
  const userMessage = createMessage('user', trimmed)
  messages.value.push(userMessage)
  shouldFollowOutput.value = true
  await scrollToBottom({ force: true })
  await startAssistantStream(trimmed)
}

async function regenerate(message) {
  if (isStreaming.value || !message.question) return
  await startAssistantStream(message.question, message.citations)
}

async function startAssistantStream(nextQuestion, reuseContext = null) {
  const streamId = activeStreamId.value + 1
  activeStreamId.value = streamId
  const assistantMessage = createMessage('assistant', '', {
    question: nextQuestion,
    isStreaming: true,
    citations: reuseContext,
    statusText: '正在准备问答...',
  })
  messages.value.push(assistantMessage)
  await scrollToBottom({ force: true })
  isStreaming.value = true
  errorMessage.value = ''
  abortController.value = new AbortController()

  try {
    await streamRetrievalQa(
      props.token,
      {
        query: nextQuestion,
        knowledge_base_id: selectedKnowledgeBaseId.value,
        document_id: selectedDocumentId.value !== 'all' && selectedDocumentId.value !== 'selected'
          ? Number(selectedDocumentId.value)
          : null,
        document_ids: selectedDocumentId.value === 'selected' ? selectedScopeDocumentIds.value : [],
        conversation_id: activeConversationId.value,
        provider: selectedProvider.value,
        model_name: selectedModelName.value || selectedProviderInfo.value?.model || null,
        answer_mode: answerMode.value,
        answer_style: answerStyle.value,
        temperature: Number(temperature.value),
        max_tokens: Number(maxTokens.value),
        limit: Number(contextLimit.value),
        history_turns: Number(historyTurns.value),
        history: historyPayload(nextQuestion),
        reuse_context: reuseContext,
      },
      {
        signal: abortController.value.signal,
        onEvent: (event, data) => handleStreamEvent(assistantMessage, event, data, streamId),
      },
    )
  } catch (error) {
    if (activeStreamId.value !== streamId) {
      return
    }
    if (error.name === 'AbortError') {
      const liveMessage = getLiveMessage(assistantMessage)
      queueAnswerText(assistantMessage, liveMessage?.content ? '\n\n（已停止生成）' : '（已停止生成）')
    } else {
      updateMessage(assistantMessage, { error: error.message })
      errorMessage.value = error.message
    }
  } finally {
    await waitForReveal(assistantMessage)
    if (activeStreamId.value === streamId) {
      updateMessage(assistantMessage, { isStreaming: false })
      isStreaming.value = false
      abortController.value = null
      await loadConversations()
    }
  }
}

function handleStreamEvent(message, event, data, streamId) {
  if (activeStreamId.value !== streamId) return
  const currentMessage = getLiveMessage(message)
  if (!currentMessage) return
  if (event === 'status') {
    updateMessage(currentMessage, { statusText: data.message ?? '' })
    return
  }
  if (event === 'citations') {
    updateMessage(currentMessage, { citations: data })
    return
  }
  if (event === 'metadata') {
    updateMessage(currentMessage, { metadata: data })
    if (data.conversation_id) {
      activeConversationId.value = data.conversation_id
      saveActiveConversationId(data.conversation_id)
      upsertConversationFromStream(data, currentMessage.question, currentMessage.question)
    }
    return
  }
  if (event === 'delta') {
    updateMessage(currentMessage, { statusText: '' })
    queueAnswerText(currentMessage, data.content ?? '')
    return
  }
  if (event === 'done') {
    updateMessage(currentMessage, { metadata: data })
    if (data.conversation_id) {
      activeConversationId.value = data.conversation_id
      saveActiveConversationId(data.conversation_id)
      upsertConversationFromStream(data, currentMessage.question, currentMessage.content)
    }
    return
  }
  if (event === 'error') {
    const messageText = data.detail ?? '问答生成失败。'
    updateMessage(currentMessage, { error: messageText })
    errorMessage.value = messageText
  }
}

function queueAnswerText(message, content) {
  if (!content) return
  const currentMessage = getLiveMessage(message)
  if (!currentMessage) return
  const updatedMessage = updateMessage(currentMessage, {
    content: currentMessage.content + content,
    pendingContent: currentMessage.pendingContent + content,
  })
  if (!updatedMessage || updatedMessage.revealTimer) return
  const messageId = updatedMessage.id
  let resolveReveal = null
  const revealPromise = new Promise((resolve) => {
    resolveReveal = resolve
  })
  const revealTimer = window.setInterval(() => {
    const liveMessage = getLiveMessageById(messageId)
    if (!liveMessage) {
      window.clearInterval(revealTimer)
      resolveReveal?.()
      return
    }
    if (!liveMessage.pendingContent) {
      window.clearInterval(revealTimer)
      liveMessage.revealResolve?.()
      updateMessage(liveMessage, {
        revealTimer: null,
        revealResolve: null,
        revealPromise: null,
      })
      return
    }
    updateMessage(liveMessage, {
      displayContent: liveMessage.displayContent + liveMessage.pendingContent.slice(0, 1),
      pendingContent: liveMessage.pendingContent.slice(1),
    })
    scrollToBottom()
  }, 24)
  updateMessage(updatedMessage, {
    revealTimer,
    revealPromise,
    revealResolve: resolveReveal,
  })
}

function waitForReveal(message) {
  const liveMessage = getLiveMessage(message)
  if (!liveMessage?.revealTimer) return Promise.resolve()
  return liveMessage.revealPromise ?? Promise.resolve()
}

function stopGeneration() {
  if (!isStreaming.value) return
  abortController.value?.abort()
}

function cancelActiveStreamNow() {
  if (!isStreaming.value) return
  activeStreamId.value += 1
  abortController.value?.abort()
  abortController.value = null
  isStreaming.value = false
}

function startNewConversation() {
  cancelActiveStreamNow()
  messages.value.forEach(clearRevealTimer)
  messages.value = []
  activeConversationId.value = null
  clearActiveConversationId()
  errorMessage.value = ''
  activeComposerMenu.value = ''
}

async function openConversation(conversation) {
  cancelActiveStreamNow()
  errorMessage.value = ''
  try {
    const detail = await getQaConversation(props.token, conversation.id)
    activeConversationId.value = detail.id
    selectedKnowledgeBaseId.value = detail.knowledge_base_id
    selectedDocumentId.value = detail.document_id ? String(detail.document_id) : 'all'
    selectedDocumentIds.value = []
    selectedProvider.value = detail.provider || selectedProvider.value
    answerMode.value = detail.answer_mode || answerMode.value
    answerStyle.value = detail.answer_style || answerStyle.value
    messages.value.forEach(clearRevealTimer)
    messages.value = hydrateMessages(detail.messages ?? [])
    saveActiveConversationId(detail.id)
    activeComposerMenu.value = ''
    await scrollToBottom({ force: true })
  } catch (error) {
    errorMessage.value = error.message
  }
}

async function removeConversation(conversation) {
  if (activeConversationId.value === conversation.id) {
    cancelActiveStreamNow()
  }
  try {
    await deleteQaConversation(props.token, conversation.id)
    if (activeConversationId.value === conversation.id) {
      startNewConversation()
    }
    await loadConversations()
  } catch (error) {
    errorMessage.value = error.message
  }
}

function upsertConversationFromStream(data, fallbackTitle = '', preview = '') {
  const conversationId = Number(data.conversation_id || 0)
  if (!conversationId) return
  const now = new Date().toISOString()
  const existing = conversations.value.find((item) => item.id === conversationId)
  const next = {
    id: conversationId,
    knowledge_base_id: data.knowledge_base_id ?? selectedKnowledgeBaseId.value,
    document_id: data.document_id ?? (selectedDocumentId.value === 'all' ? null : Number(selectedDocumentId.value)),
    title: existing?.title || conversationTitle(fallbackTitle),
    provider: data.provider ?? selectedProvider.value,
    answer_mode: data.answer_mode ?? answerMode.value,
    answer_style: data.answer_style ?? answerStyle.value,
    message_count: Math.max(existing?.message_count ?? 0, messages.value.filter((message) => message.content.trim()).length),
    last_message_role: preview ? 'assistant' : (existing?.last_message_role ?? ''),
    last_message_preview: conversationPreview(preview || existing?.last_message_preview || fallbackTitle),
    created_at: existing?.created_at || now,
    updated_at: now,
  }
  conversations.value = [
    next,
    ...conversations.value.filter((item) => item.id !== conversationId),
  ]
}

function conversationTitle(value) {
  const title = String(value || '').trim().replace(/\s+/g, ' ')
  return title ? title.slice(0, 48) : '新会话'
}

function conversationPreview(value) {
  const preview = String(value || '').trim().replace(/\s+/g, ' ')
  return preview ? preview.slice(0, 96) : ''
}

function historyPayload(currentQuestion = '') {
  const items = messages.value
    .filter((message) => ['user', 'assistant'].includes(message.role) && message.content.trim())
  const last = items.at(-1)
  if (last?.role === 'user' && last.content === currentQuestion) {
    items.pop()
  }
  return items
    .slice(-Number(historyTurns.value) * 2)
    .map((message) => ({
      role: message.role,
      content: message.content,
    }))
}

function createMessage(role, content, extra = {}) {
  return {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    role,
    content,
    displayContent: role === 'assistant' ? '' : content,
    createdAt: new Date(),
    citations: null,
    citationsExpanded: false,
    metadata: null,
    error: '',
    isStreaming: false,
    statusText: '',
    pendingContent: '',
    revealTimer: null,
    revealPromise: null,
    revealResolve: null,
    question: '',
    ...extra,
  }
}

function getLiveMessage(message) {
  return getLiveMessageById(message.id)
}

function getLiveMessageById(messageId) {
  return messages.value.find((item) => item.id === messageId) ?? null
}

function updateMessage(message, patch) {
  const index = messages.value.findIndex((item) => item.id === message.id)
  if (index === -1) return null
  const updated = {
    ...messages.value[index],
    ...patch,
  }
  messages.value[index] = updated
  return updated
}

function hydrateMessages(storedMessages) {
  const hydrated = storedMessages.map((message) => createMessage(message.role, message.content, {
    id: `stored-${message.id}`,
    createdAt: new Date(message.created_at),
    displayContent: message.role === 'assistant' ? message.content : message.content,
    citations: Object.keys(message.citations ?? {}).length ? message.citations : null,
    metadata: Object.keys(message.metadata ?? {}).length ? message.metadata : null,
  }))
  let lastQuestion = ''
  for (const message of hydrated) {
    if (message.role === 'user') {
      lastQuestion = message.content
    } else if (message.role === 'assistant' && !message.question) {
      message.question = lastQuestion
    }
  }
  return hydrated
}

async function restoreActiveConversation() {
  if (messages.value.length > 0 || isStreaming.value || conversations.value.length === 0) return
  const storedId = Number(sessionStorage.getItem(ACTIVE_QA_CONVERSATION_KEY) || 0)
  const conversation = conversations.value.find((item) => item.id === storedId) ?? conversations.value[0]
  if (conversation) {
    await openConversation(conversation)
  }
}

function saveActiveConversationId(conversationId) {
  if (conversationId) {
    sessionStorage.setItem(ACTIVE_QA_CONVERSATION_KEY, String(conversationId))
  }
}

function clearActiveConversationId() {
  sessionStorage.removeItem(ACTIVE_QA_CONVERSATION_KEY)
}

function modelLabel(model) {
  if (!model) return '未保存密钥'
  const source = model.keySource === 'system' ? '系统默认' : '个人密钥'
  return model.model ? `${model.model} · ${source}` : source
}

function evidenceLevelLabel(level, usesKg = true) {
  if (!usesKg) return '通用问答'
  const labels = {
    sufficient: '依据充分',
    limited: '依据有限',
    none: '无直接依据',
  }
  return labels[level] ?? '待判断'
}

function evidenceLevelClass(level) {
  const classes = {
    sufficient: 'status-graph-ready',
    limited: 'status-degraded',
    none: 'status-failed',
  }
  return classes[level] ?? 'status-uploaded'
}

function hasKgCitations(citations) {
  return Boolean(citations?.uses_kg_context)
}

function citationItems(citations) {
  return Array.isArray(citations?.evidence_items) ? citations.evidence_items : []
}

function evidenceByRef(citations, ref) {
  const normalized = String(ref || '').replace(/[^\d]/g, '')
  return citationItems(citations).find((item) => String(item.ref || '').replace(/[^\d]/g, '') === normalized) ?? null
}

function openEvidence(message, evidence) {
  if (!evidence) return
  activeEvidence.value = {
    messageId: message.id,
    ref: evidence.ref,
    item: evidence,
  }
}

function handleAnswerClick(event, message) {
  if (!(event.target instanceof Element)) return
  const target = event.target.closest('.qa-evidence-link')
  if (!target) return
  const evidence = evidenceByRef(message.citations, target.dataset.evidenceRef)
  if (evidence) {
    openEvidence(message, evidence)
  }
}

function isActiveEvidence(message, evidence) {
  return activeEvidence.value?.messageId === message.id && activeEvidence.value?.ref === evidence.ref
}

function evidenceKindClass(evidence) {
  const kind = displayEvidenceKind(evidence?.kind)
  if (kind === '关系') return 'status-graph-ready'
  if (kind === '图片') return 'status-degraded'
  return 'status-uploaded'
}

function tripleText(triple) {
  return `${localizeInlineText(triple.subject)} → ${displayPredicateLabel(triple.predicate)} → ${localizeInlineText(triple.object)}`
}

function evidenceTitle(evidence) {
  if (evidence?.triple) return tripleText(evidence.triple)
  return localizeInlineText(evidence?.title || '依据')
}

function evidenceSummary(evidence) {
  return chineseFirst(evidence?.summary, evidence?.quote)
}

function evidenceQuote(evidence) {
  return chineseFirst(evidence?.quote)
}

function evidenceRationale(triple) {
  return chineseFirst(triple?.evidence?.quote_or_summary, triple?.rationale)
}

function evidenceText(evidence) {
  if (!evidence) return ''
  return chineseFirst(evidence.quote_or_summary, evidence.section_title, evidence.source_path)
}

function evidenceMessage(citations) {
  return localizeInlineText(citations?.message || '')
}

function evidenceKindLabel(evidence) {
  return displayEvidenceKind(evidence?.kind)
}

function nodeTitle(node) {
  return chineseFirst(node?.title, node?.description, node?.evidence?.quote_or_summary) || displayTypeLabel(node?.label)
}

function nodeDescription(node) {
  return chineseFirst(node?.description, node?.evidence?.quote_or_summary)
}

function evidenceSection(evidence) {
  return chineseFirst(evidence?.section)
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

function imageUrl(imagePath) {
  if (!imagePath || !selectedKnowledgeBaseId.value) return ''
  const params = new URLSearchParams({
    knowledge_base_id: String(selectedKnowledgeBaseId.value),
    image_path: imagePath,
    access_token: props.token,
  })
  if (selectedDocumentId.value !== 'all') {
    if (selectedDocumentId.value === 'selected') {
      return `${API_BASE_URL}/api/knowledge-graph/image?${params.toString()}`
    }
    params.set('document_id', String(selectedDocumentId.value))
  }
  return `${API_BASE_URL}/api/knowledge-graph/image?${params.toString()}`
}

function imageTitle(image) {
  return chineseFirst(image.description, image.value_marker, image.category) || image.figure_id || image.image_path || '图片依据'
}

function evidenceImageTitle(image) {
  return chineseFirst(image?.description) || image?.image_path || '图片依据'
}

function renderMarkdown(text, citations = null) {
  const escaped = escapeHtml(text || '')
  return escaped
    .replace(/\[依据\s*(\d+)\]/g, (_match, ref) => {
      if (!evidenceByRef(citations, ref)) {
        return `[依据${ref}]`
      }
      return `<button type="button" class="qa-evidence-link" data-evidence-ref="${ref}">依据${ref}</button>`
    })
    .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
    .replace(/^### (.*)$/gm, '<h3>$1</h3>')
    .replace(/^## (.*)$/gm, '<h2>$1</h2>')
    .replace(/^# (.*)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/^- (.*)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>')
    .replace(/\n{2,}/g, '</p><p>')
    .replace(/\n/g, '<br>')
    .replace(/^(.+)$/s, '<p>$1</p>')
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

async function copyAnswer(content) {
  await navigator.clipboard.writeText(content)
}

function toggleCitations(message) {
  message.citationsExpanded = !message.citationsExpanded
}

function scrollChat(direction) {
  const element = chatPanel.value
  if (!element) return
  const distance = Math.max(240, Math.floor(element.clientHeight * 0.72))
  element.scrollBy({
    top: direction === 'up' ? -distance : distance,
    behavior: 'smooth',
  })
}

function toggleComposerMenu(menu) {
  activeComposerMenu.value = activeComposerMenu.value === menu ? '' : menu
}

function closeComposerMenu() {
  activeComposerMenu.value = ''
}

function scrollToBottom(options = {}) {
  if (!options.force && !shouldFollowOutput.value) {
    return Promise.resolve()
  }
  return new Promise((resolve) => {
    window.requestAnimationFrame(() => {
      const element = chatPanel.value
      if (element) {
        element.scrollTop = element.scrollHeight
      }
      resolve()
    })
  })
}

function handleChatScroll() {
  if (isNearChatBottom()) {
    shouldFollowOutput.value = true
  } else if (isStreaming.value) {
    shouldFollowOutput.value = false
  }
}

function isNearChatBottom() {
  const element = chatPanel.value
  if (!element) return true
  return element.scrollHeight - element.scrollTop - element.clientHeight < 80
}

watch(selectedKnowledgeBaseId, async (_newId, oldId) => {
  if (oldId !== null && oldId !== undefined && !isStreaming.value) {
    messages.value.forEach(clearRevealTimer)
    messages.value = []
    activeConversationId.value = null
    clearActiveConversationId()
  }
  selectedDocumentId.value = 'all'
  selectedDocumentIds.value = []
  await refreshScope()
})

watch(selectedProvider, ensureSelectedModel)

onMounted(() => {
  window.addEventListener('click', closeComposerMenu)
  refreshScope()
})

onBeforeUnmount(() => {
  window.removeEventListener('click', closeComposerMenu)
  abortController.value?.abort()
  messages.value.forEach(clearRevealTimer)
})

function clearRevealTimer(message) {
  if (message.revealTimer) {
    window.clearInterval(message.revealTimer)
    message.revealTimer = null
  }
  message.revealResolve?.()
  message.revealResolve = null
  message.revealPromise = null
}
</script>

<template>
  <main class="workspace qa-workspace" @click="activeComposerMenu = ''">
    <p v-if="errorMessage" class="error-message page-message">{{ errorMessage }}</p>

    <aside class="qa-history-sidebar">
      <div class="qa-history-panel">
        <div class="qa-sidebar-head">
          <div>
            <p class="eyebrow">书脉问答</p>
            <h1>工作台</h1>
            <p class="qa-current-kb">当前知识库：{{ activeKnowledgeBaseName }}</p>
          </div>
          <button class="secondary-button" type="button" @click="startNewConversation">
            新对话
          </button>
        </div>
        <div class="qa-history-head">
          <h2>历史对话</h2>
          <span>{{ isLoadingConversations ? '加载中' : `${conversations.length} 条` }}</span>
        </div>
        <div class="qa-history-list">
          <article
            v-for="conversation in filteredConversations"
            :key="conversation.id"
            class="qa-history-item"
            :class="{ active: activeConversationId === conversation.id }"
          >
            <button
              class="qa-history-open"
              type="button"
              :title="conversation.title || conversation.last_message_preview || '新会话'"
              @click="openConversation(conversation)"
            >
              <strong>{{ conversation.title || conversation.last_message_preview || '新会话' }}</strong>
            </button>
            <button
              class="qa-history-delete"
              type="button"
              title="删除会话"
              aria-label="删除会话"
              @click="removeConversation(conversation)"
            >
              ×
            </button>
          </article>
          <p v-if="!isLoadingConversations && conversations.length === 0" class="empty-table-state">暂无历史对话。</p>
          <p v-else-if="!isLoadingConversations && filteredConversations.length === 0" class="empty-table-state">没有匹配的对话。</p>
        </div>
        <div class="qa-sidebar-footer">
          <div class="qa-sidebar-search-row">
            <label class="qa-history-search">
              <span>搜索历史</span>
              <input v-model="historySearch" type="search" placeholder="搜索历史" />
            </label>
            <div class="qa-context-meter" :class="contextUsageClass">
              <span>上下文记忆</span>
              <strong>{{ contextUsagePercent }}%</strong>
            </div>
          </div>
          <button v-if="isStreaming" class="qa-settings-button danger" type="button" @click="stopGeneration">
            <span>停止生成</span>
          </button>
        </div>
      </div>
    </aside>

    <section ref="chatPanel" class="qa-chat-panel content-panel" @scroll="handleChatScroll">
      <div v-if="messages.length === 0" class="empty-state qa-empty-state">
        <h2>输入问题，开始从当前知识库中找答案</h2>
        <p>每次提问都会重新检索知识图谱，引用依据会先显示，答案随后流式生成。</p>
      </div>

      <article
        v-for="message in messages"
        :key="message.id"
        class="qa-message"
        :class="`qa-message-${message.role}`"
      >
        <div v-if="message.role === 'user'" class="qa-user-content">
          {{ message.content }}
        </div>

        <template v-else>
          <div v-if="message.citations" class="qa-citations">
            <div class="qa-citation-head">
              <span class="status-badge" :class="evidenceLevelClass(message.citations.evidence_level)">
                {{ evidenceLevelLabel(message.citations.evidence_level, message.citations.uses_kg_context) }}
              </span>
              <span>{{ evidenceMessage(message.citations) }}</span>
              <button
                v-if="hasKgCitations(message.citations)"
                class="qa-citation-toggle"
                type="button"
                @click="toggleCitations(message)"
              >
                {{ message.citationsExpanded ? '收起依据' : '展开依据' }}
              </button>
            </div>

            <div v-if="message.citationsExpanded && hasKgCitations(message.citations)" class="qa-citation-grid">
              <section class="qa-evidence-index">
                <h2>关键依据</h2>
                <article
                  v-for="evidence in citationItems(message.citations)"
                  :key="evidence.ref"
                  class="retrieval-item-card qa-evidence-card"
                  :class="{ active: isActiveEvidence(message, evidence) }"
                  @click="openEvidence(message, evidence)"
                >
                  <div class="retrieval-item-head">
                    <strong>{{ evidence.ref }} · {{ evidenceTitle(evidence) }}</strong>
                    <span class="status-badge" :class="evidenceKindClass(evidence)">
                      {{ evidenceKindLabel(evidence) }}
                    </span>
                  </div>
                  <p v-if="evidenceSummary(evidence)">{{ evidenceSummary(evidence) }}</p>
                  <small v-if="evidenceQuote(evidence)">{{ evidenceQuote(evidence) }}</small>
                </article>
              </section>

              <section>
                <h2>相关节点</h2>
                <article v-for="node in message.citations.related_nodes" :key="node.id" class="retrieval-item-card">
                  <strong>{{ nodeTitle(node) }}</strong>
                  <p v-if="nodeDescription(node)">{{ nodeDescription(node) }}</p>
                  <small v-if="evidenceText(node.evidence)">{{ evidenceText(node.evidence) }}</small>
                  <span class="muted-inline">{{ displayTypeLabel(node.label) }}</span>
                </article>
                <p v-if="message.citations.related_nodes.length === 0" class="empty-table-state">暂无相关节点。</p>
              </section>

              <section>
                <h2>相关三元组</h2>
                <article v-for="triple in message.citations.triples" :key="triple.id" class="retrieval-item-card">
                  <strong>{{ tripleText(triple) }}</strong>
                  <p v-if="evidenceRationale(triple)">{{ evidenceRationale(triple) }}</p>
                  <small v-if="evidenceText(triple.evidence)">{{ evidenceText(triple.evidence) }}</small>
                </article>
                <p v-if="message.citations.triples.length === 0" class="empty-table-state">暂无相关三元组。</p>
              </section>
            </div>

            <div
              v-if="message.citationsExpanded && hasKgCitations(message.citations) && message.citations.images.length"
              class="qa-image-strip"
            >
              <button
                v-for="image in message.citations.images"
                :key="image.image_path || image.figure_id"
                class="qa-image-thumb"
                type="button"
                @click="activeImage = image"
              >
                <img :src="imageUrl(image.image_path)" :alt="imageTitle(image)" />
                <span>{{ imageTitle(image) }}</span>
              </button>
            </div>

            <ul
              v-if="message.citationsExpanded && hasKgCitations(message.citations) && message.citations.sources.length"
              class="plain-list qa-source-list"
            >
              <li v-for="source in message.citations.sources" :key="source.id">
                {{ source.filename }} <span class="muted-inline">({{ documentStatusLabel(source.status) }})</span>
              </li>
            </ul>
          </div>

          <div
            class="qa-answer"
            @click="handleAnswerClick($event, message)"
            v-html="renderMarkdown(message.displayContent || message.statusText || (message.isStreaming ? '正在生成...' : ''), message.citations)"
          ></div>
          <p v-if="message.error" class="error-message">{{ message.error }}</p>

        </template>

        <div class="qa-message-actions">
          <time :datetime="message.createdAt.toISOString()">{{ message.createdAt.toLocaleString() }}</time>
          <button
            class="qa-icon-button"
            type="button"
            :disabled="!message.content"
            title="复制消息"
            aria-label="复制消息"
            @click.stop="copyAnswer(message.content)"
          >
            ⧉
          </button>
          <button
            v-if="message.role === 'assistant'"
            class="qa-icon-button"
            type="button"
            :disabled="isStreaming || !message.citations"
            title="重新生成"
            aria-label="重新生成"
            @click.stop="regenerate(message)"
          >
            ↻
          </button>
        </div>
      </article>
    </section>

    <form class="qa-composer" @submit.prevent="askQuestion" @click.stop>
      <div v-if="activeComposerMenu" class="qa-composer-popover" @click.stop>
        <div class="qa-popover-head">
          <strong>
            {{
              activeComposerMenu === 'scope'
                ? '知识范围'
                : activeComposerMenu === 'model'
                  ? '模型选择'
                  : activeComposerMenu === 'style'
                    ? '回答方式'
                    : '高级参数'
            }}
          </strong>
          <button type="button" title="关闭设置面板" aria-label="关闭设置面板" @click="activeComposerMenu = ''">
            ×
          </button>
        </div>

        <div v-if="activeComposerMenu === 'scope'" class="qa-popover-grid">
          <label class="form-field">
            <span>知识库</span>
            <select v-model="selectedKnowledgeBaseId" :disabled="isLoadingScope">
              <option v-for="kb in knowledgeBases" :key="kb.id" :value="kb.id">
                {{ displayKnowledgeBaseName(kb.name) }}
              </option>
            </select>
          </label>
          <label class="form-field">
            <span>PDF 范围</span>
            <select v-model="selectedDocumentId" :disabled="isLoadingScope">
              <option value="all">全部文档</option>
              <option value="selected">多选 PDF</option>
              <option v-for="document in documents" :key="document.id" :value="String(document.id)">
                {{ document.filename }}
              </option>
            </select>
          </label>
          <div v-if="selectedDocumentId === 'selected'" class="qa-document-picker qa-popover-picker">
            <label v-for="document in documents" :key="document.id">
              <input v-model="selectedDocumentIds" type="checkbox" :value="document.id" :disabled="isLoadingScope" />
              <span>{{ document.filename }}</span>
            </label>
            <p v-if="documents.length === 0" class="empty-table-state">当前知识库暂无文档。</p>
          </div>
        </div>

        <div v-else-if="activeComposerMenu === 'model'" class="qa-popover-grid">
          <label class="form-field">
            <span>模型平台</span>
            <select v-model="selectedProvider">
              <option v-for="provider in providerOptions" :key="provider.id" :value="provider.id">
                {{ provider.label }} - {{ provider.hasKey ? modelLabel(provider) : '未保存密钥' }}
              </option>
            </select>
          </label>
          <label class="form-field">
            <span>模型</span>
            <select v-model="selectedModelName" :disabled="isLoadingModels || selectedModelOptions.length === 0">
              <option v-for="model in selectedModelOptions" :key="model.id" :value="model.id">
                {{ model.name || model.id }}
              </option>
            </select>
          </label>
        </div>

        <div v-else-if="activeComposerMenu === 'style'" class="qa-popover-grid">
          <label class="form-field">
            <span>回答模式</span>
            <select v-model="answerMode">
              <option v-for="option in answerModeOptions" :key="option.id" :value="option.id">
                {{ option.label }}
              </option>
            </select>
          </label>
          <label class="form-field">
            <span>回答风格</span>
            <select v-model="answerStyle">
              <option v-for="option in answerStyleOptions" :key="option.id" :value="option.id">
                {{ option.label }}
              </option>
            </select>
          </label>
        </div>

        <div v-else class="qa-popover-grid qa-popover-grid-compact">
          <label class="form-field">
            <span>温度</span>
            <input v-model.number="temperature" type="number" min="0" max="2" step="0.1" />
          </label>
          <label class="form-field">
            <span>引用数量</span>
            <input v-model.number="contextLimit" type="number" min="1" max="20" step="1" />
          </label>
          <label class="form-field">
            <span>最大输出</span>
            <input v-model.number="maxTokens" type="number" min="100" max="8000" step="100" />
          </label>
          <label class="form-field">
            <span>追问轮数</span>
            <input v-model.number="historyTurns" type="number" min="0" max="10" step="1" />
          </label>
        </div>
      </div>

      <textarea
        v-model="question"
        rows="2"
        placeholder="在这里输入消息，按 Ctrl + Enter 发送"
        :disabled="isStreaming"
        @keydown.ctrl.enter.prevent="askQuestion"
      ></textarea>
      <div class="qa-composer-toolbar">
        <div class="qa-composer-tools">
          <button
            class="qa-tool-button"
            type="button"
            :class="{ active: activeComposerMenu === 'scope' }"
            title="选择知识库和 PDF 范围"
            aria-label="选择知识库和 PDF 范围"
            @click="toggleComposerMenu('scope')"
          >
            ⊞
          </button>
          <button
            class="qa-tool-button"
            type="button"
            :class="{ active: activeComposerMenu === 'model' }"
            title="选择模型平台和模型名称"
            aria-label="选择模型平台和模型名称"
            @click="toggleComposerMenu('model')"
          >
            ◇
          </button>
          <button
            class="qa-tool-button"
            type="button"
            :class="{ active: activeComposerMenu === 'style' }"
            title="调整回答模式和回答风格"
            aria-label="调整回答模式和回答风格"
            @click="toggleComposerMenu('style')"
          >
            ◎
          </button>
          <button
            class="qa-tool-button"
            type="button"
            :class="{ active: activeComposerMenu === 'advanced' }"
            title="调整温度、引用数量、最大输出和追问轮数"
            aria-label="调整温度、引用数量、最大输出和追问轮数"
            @click="toggleComposerMenu('advanced')"
          >
            ⌁
          </button>
        </div>
        <button
          class="qa-send-button"
          type="submit"
          title="发送消息"
          aria-label="发送消息"
          :disabled="
            isStreaming ||
            !question.trim() ||
            !selectedKnowledgeBaseId ||
            (selectedDocumentId === 'selected' && selectedScopeDocumentIds.length === 0)
          "
        >
          <span aria-hidden="true"></span>
        </button>
      </div>
    </form>

    <div v-if="activeImage" class="image-modal" @click.self="activeImage = null">
      <div class="image-modal-card">
        <button class="text-button" type="button" @click="activeImage = null">关闭</button>
        <img :src="imageUrl(activeImage.image_path)" :alt="imageTitle(activeImage)" />
        <p>{{ imageTitle(activeImage) }}</p>
      </div>
    </div>

    <aside v-if="activeEvidence" class="qa-evidence-drawer">
      <div class="qa-evidence-drawer-head">
        <div>
          <p class="eyebrow">{{ activeEvidence.item.ref }}</p>
          <h2>{{ evidenceTitle(activeEvidence.item) }}</h2>
        </div>
        <button class="text-button" type="button" @click="activeEvidence = null">关闭</button>
      </div>

      <div class="qa-evidence-drawer-body">
        <span class="status-badge" :class="evidenceKindClass(activeEvidence.item)">
          {{ evidenceKindLabel(activeEvidence.item) }}
        </span>
        <p v-if="evidenceSummary(activeEvidence.item)">{{ evidenceSummary(activeEvidence.item) }}</p>
        <blockquote v-if="evidenceQuote(activeEvidence.item)">{{ evidenceQuote(activeEvidence.item) }}</blockquote>
        <small v-if="evidenceSection(activeEvidence.item)">章节：{{ evidenceSection(activeEvidence.item) }}</small>

        <div v-if="activeEvidence.item.triple" class="qa-evidence-detail">
          <h3>对应关系</h3>
          <p>{{ tripleText(activeEvidence.item.triple) }}</p>
          <small v-if="evidenceRationale(activeEvidence.item.triple)">
            {{ evidenceRationale(activeEvidence.item.triple) }}
          </small>
        </div>

        <div v-if="activeEvidence.item.node" class="qa-evidence-detail">
          <h3>对应节点</h3>
          <p>{{ nodeTitle(activeEvidence.item.node) }}</p>
          <small>{{ displayTypeLabel(activeEvidence.item.node.label) }}</small>
        </div>

        <div v-if="activeEvidence.item.images?.length" class="qa-evidence-images">
          <h3>相关图片</h3>
          <button
            v-for="image in activeEvidence.item.images"
            :key="image.image_path || image.description"
            class="qa-image-thumb"
            type="button"
            @click="activeImage = image"
          >
            <img :src="imageUrl(image.image_path)" :alt="evidenceImageTitle(image)" />
            <span>{{ evidenceImageTitle(image) }}</span>
          </button>
        </div>
      </div>
    </aside>
  </main>
</template>
