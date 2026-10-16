export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''
const TOKEN_STORAGE_KEY = 'famas_admin_token'

export function getStoredToken() {
  const sessionToken = sessionStorage.getItem(TOKEN_STORAGE_KEY) ?? ''
  if (sessionToken) {
    return sessionToken
  }
  const legacyToken = localStorage.getItem(TOKEN_STORAGE_KEY) ?? ''
  if (legacyToken) {
    sessionStorage.setItem(TOKEN_STORAGE_KEY, legacyToken)
    localStorage.removeItem(TOKEN_STORAGE_KEY)
  }
  return legacyToken
}

export function storeToken(token) {
  sessionStorage.setItem(TOKEN_STORAGE_KEY, token)
}

export function clearStoredToken() {
  sessionStorage.removeItem(TOKEN_STORAGE_KEY)
  localStorage.removeItem(TOKEN_STORAGE_KEY)
}

export async function apiRequest(path, options = {}) {
  const { token, headers, ...rest } = options
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    credentials: 'include',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(headers ?? {}),
    },
  })

  const text = await response.text()
  const data = text ? JSON.parse(text) : null
  if (!response.ok) {
    throw new Error(data?.detail ?? `请求失败，状态码：${response.status}`)
  }
  return data
}

function parseJsonResponse(text) {
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

function apiRequestWithProgress(path, options = {}) {
  const { token, headers, onProgress, timeoutMs = 180000, ...rest } = options
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open(rest.method ?? 'GET', `${API_BASE_URL}${path}`)
    xhr.timeout = timeoutMs
    xhr.withCredentials = true
    if (token) {
      xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    }
    for (const [key, value] of Object.entries(headers ?? {})) {
      xhr.setRequestHeader(key, value)
    }
    xhr.onload = () => {
      const text = xhr.responseText ?? ''
      const data = parseJsonResponse(text)
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new Error(data?.detail ?? `请求失败，状态码：${xhr.status}`))
        return
      }
      resolve(data)
    }
    xhr.onerror = () => {
      reject(new Error('网络请求失败，请检查后端服务或网络连接。'))
    }
    xhr.ontimeout = () => {
      reject(new Error('上传分片超时，当前网络可能较慢或不稳定。'))
    }
    if (typeof onProgress === 'function') {
      xhr.upload.onprogress = onProgress
    }
    xhr.send(rest.body ?? null)
  })
}

export async function login(username, password) {
  return apiRequest('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
}

export async function register(username, password) {
  return apiRequest('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
}

export async function getCurrentUser(token) {
  return apiRequest('/api/auth/me', { token })
}

export async function logout(token) {
  return apiRequest('/api/auth/logout', {
    method: 'POST',
    token,
  })
}

export async function listUsers(token) {
  return apiRequest('/api/users', { token })
}

export async function getUserOverview(token, userId) {
  return apiRequest(`/api/users/${userId}/overview`, { token })
}

export async function updateUserStatus(token, userId, isActive) {
  return apiRequest(`/api/users/${userId}/status`, {
    method: 'PUT',
    token,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_active: isActive }),
  })
}

export async function resetUserPassword(token, userId, newPassword) {
  return apiRequest(`/api/users/${userId}/password`, {
    method: 'PUT',
    token,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_password: newPassword }),
  })
}

export async function listKnowledgeBases(token) {
  return apiRequest('/api/knowledge-bases', { token })
}

export async function createKnowledgeBase(token, name) {
  return apiRequest('/api/knowledge-bases', {
    method: 'POST',
    token,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

export async function updateKnowledgeBase(token, knowledgeBaseId, name) {
  return apiRequest(`/api/knowledge-bases/${knowledgeBaseId}`, {
    method: 'PUT',
    token,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

export async function deleteKnowledgeBase(token, knowledgeBaseId) {
  return apiRequest(`/api/knowledge-bases/${knowledgeBaseId}`, {
    method: 'DELETE',
    token,
  })
}

export async function listDocuments(token, knowledgeBaseId) {
  const query = knowledgeBaseId ? `?knowledge_base_id=${knowledgeBaseId}` : ''
  return apiRequest(`/api/documents${query}`, { token })
}

export async function getKnowledgeGraphSummary(token, knowledgeBaseId, documentId = null) {
  const params = new URLSearchParams({ knowledge_base_id: String(knowledgeBaseId) })
  if (documentId) {
    params.set('document_id', String(documentId))
  }
  return apiRequest(`/api/knowledge-graph/summary?${params.toString()}`, { token })
}

export async function uploadPdf(token, knowledgeBaseId, file, metadata = {}, onProgress = null) {
  return uploadPdfChunked(token, knowledgeBaseId, file, metadata, onProgress)
}

export async function uploadPdfDirect(token, knowledgeBaseId, file, metadata = {}) {
  const content = await file.arrayBuffer()
  return apiRequest(`/api/documents?knowledge_base_id=${knowledgeBaseId}`, {
    method: 'POST',
    token,
    headers: {
      'Content-Type': 'application/pdf',
      'X-Filename': encodeURIComponent(file.name),
      'X-Subject': encodeURIComponent(metadata.subject ?? ''),
      'X-Grade': encodeURIComponent(metadata.grade ?? ''),
      'X-Publisher': encodeURIComponent(metadata.publisher ?? ''),
      'X-Textbook': encodeURIComponent(metadata.textbook ?? ''),
      'X-Textbook-Version': encodeURIComponent(metadata.textbook_version ?? ''),
    },
    body: content,
  })
}

export async function uploadPdfChunked(token, knowledgeBaseId, file, metadata = {}, onProgress = null) {
  const init = await apiRequest('/api/documents/chunked/init', {
    method: 'POST',
    token,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      filename: file.name,
      file_size_bytes: file.size,
      knowledge_base_id: knowledgeBaseId,
      subject: metadata.subject ?? '',
      grade: metadata.grade ?? '',
      publisher: metadata.publisher ?? '',
      textbook: metadata.textbook ?? '',
      textbook_version: metadata.textbook_version ?? '',
    }),
  })

  const chunkSize = init.chunk_size_bytes
  const totalChunks = init.total_chunks
  const maxAttempts = 4
  for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex += 1) {
    const start = chunkIndex * chunkSize
    const end = Math.min(start + chunkSize, file.size)
    const chunk = file.slice(start, end)
    await uploadChunkWithRetry({
      token,
      uploadId: init.upload_id,
      chunkIndex,
      chunk,
      start,
      end,
      fileSize: file.size,
      totalChunks,
      maxAttempts,
      onProgress,
    })
    if (onProgress) {
      onProgress({
        phase: 'uploading',
        uploaded_chunks: chunkIndex + 1,
        total_chunks: totalChunks,
        uploaded_bytes: end,
        total_bytes: file.size,
        percent: Math.round(((chunkIndex + 1) / totalChunks) * 100),
      })
    }
  }

  if (onProgress) {
    onProgress({
      phase: 'finalizing',
      uploaded_chunks: totalChunks,
      total_chunks: totalChunks,
      uploaded_bytes: file.size,
      total_bytes: file.size,
      percent: 100,
    })
  }

  return apiRequest(`/api/documents/chunked/${init.upload_id}/complete`, {
    method: 'POST',
    token,
  })
}

async function uploadChunkWithRetry({
  token,
  uploadId,
  chunkIndex,
  chunk,
  start,
  end,
  fileSize,
  totalChunks,
  maxAttempts,
  onProgress,
}) {
  let lastError = null
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    if (attempt > 1 && onProgress) {
      onProgress({
        phase: 'retrying',
        uploaded_chunks: chunkIndex,
        total_chunks: totalChunks,
        uploaded_bytes: start,
        total_bytes: fileSize,
        percent: Math.min(99, Math.round((start / fileSize) * 100)),
        chunk_index: chunkIndex + 1,
        attempt,
        max_attempts: maxAttempts,
        message: `正在重试分片 ${chunkIndex + 1}/${totalChunks}（第 ${attempt}/${maxAttempts} 次）`,
      })
      await wait(800 * attempt)
    }
    try {
      await apiRequestWithProgress(`/api/documents/chunked/${uploadId}/chunks/${chunkIndex}`, {
        method: 'PUT',
        token,
        headers: { 'Content-Type': 'application/octet-stream' },
        body: chunk,
        timeoutMs: 180000,
        onProgress: (event) => {
          if (!onProgress || !event.lengthComputable) return
          const uploadedBytes = Math.min(start + event.loaded, fileSize)
          onProgress({
            phase: 'uploading',
            uploaded_chunks: chunkIndex,
            total_chunks: totalChunks,
            uploaded_bytes: uploadedBytes,
            total_bytes: fileSize,
            percent: Math.min(99, Math.round((uploadedBytes / fileSize) * 100)),
            chunk_index: chunkIndex + 1,
            attempt,
            max_attempts: maxAttempts,
          })
        },
      })
      return
    } catch (error) {
      lastError = error
    }
  }
  throw new Error(
    `第 ${chunkIndex + 1}/${totalChunks} 个分片上传失败，已重试 ${maxAttempts} 次。${lastError?.message ?? ''}`.trim(),
  )
}

function wait(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

export async function startDocumentProcessing(token, documentId, stage = 'full_pipeline', options = {}) {
  const stagePath = {
    parse_pdf: 'parse',
    build_graph: 'build-graph',
    full_pipeline: 'process',
  }[stage]
  const payload = {}
  if (options.schema_version_id) {
    payload.schema_version_id = options.schema_version_id
  }
  return apiRequest(`/api/documents/${documentId}/${stagePath}`, {
    method: 'POST',
    token,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function listDocumentJobs(token, documentId) {
  return apiRequest(`/api/documents/${documentId}/jobs`, { token })
}

export async function getDocumentJobLogs(token, documentId, jobId) {
  return apiRequest(`/api/documents/${documentId}/jobs/${jobId}/logs`, { token })
}

export async function deleteDocument(token, documentId) {
  return apiRequest(`/api/documents/${documentId}`, {
    method: 'DELETE',
    token,
  })
}

export async function deleteDocumentsBatch(token, documentIds) {
  return apiRequest('/api/documents/batch-delete', {
    method: 'POST',
    token,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ document_ids: documentIds }),
  })
}

export async function updateDocumentMetadata(token, documentId, payload) {
  return apiRequest(`/api/documents/${documentId}/metadata`, {
    method: 'PUT',
    token,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function listDocumentSchemas(token, documentId) {
  return apiRequest(`/api/documents/${documentId}/schemas`, { token })
}

export async function createDocumentSchemaTemplate(token, documentId, payload = {}) {
  return apiRequest(`/api/documents/${documentId}/schemas/system-template`, {
    method: 'POST',
    token,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function createDocumentSchema(token, documentId, payload) {
  return apiRequest(`/api/documents/${documentId}/schemas`, {
    method: 'POST',
    token,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function updateDocumentSchema(token, documentId, schemaId, payload) {
  return apiRequest(`/api/documents/${documentId}/schemas/${schemaId}`, {
    method: 'PUT',
    token,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function activateDocumentSchema(token, documentId, schemaId) {
  return apiRequest(`/api/documents/${documentId}/schemas/${schemaId}/activate`, {
    method: 'POST',
    token,
  })
}

export async function rewriteDocumentSchemaWithLlm(token, documentId, schemaId, payload) {
  return apiRequest(`/api/documents/${documentId}/schemas/${schemaId}/llm-rewrite`, {
    method: 'POST',
    token,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function queryRetrieval(token, payload) {
  return apiRequest('/api/retrieval/query', {
    method: 'POST',
    token,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function listQaConversations(token, knowledgeBaseId = null) {
  const query = knowledgeBaseId ? `?knowledge_base_id=${knowledgeBaseId}` : ''
  return apiRequest(`/api/retrieval/conversations${query}`, { token })
}

export async function createQaConversation(token, payload) {
  return apiRequest('/api/retrieval/conversations', {
    method: 'POST',
    token,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function getQaConversation(token, conversationId) {
  return apiRequest(`/api/retrieval/conversations/${conversationId}`, { token })
}

export async function deleteQaConversation(token, conversationId) {
  return apiRequest(`/api/retrieval/conversations/${conversationId}`, {
    method: 'DELETE',
    token,
  })
}

export async function streamRetrievalQa(token, payload, handlers = {}) {
  const response = await fetch(`${API_BASE_URL}/api/retrieval/qa/stream`, {
    method: 'POST',
    credentials: 'include',
    signal: handlers.signal,
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    const text = await response.text()
    const data = parseJsonResponse(text)
    throw new Error(data?.detail ?? `请求失败，状态码：${response.status}`)
  }
  if (!response.body) {
    throw new Error('当前浏览器不支持流式问答。')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    buffer = consumeSseBuffer(buffer, handlers.onEvent)
    await yieldToBrowser()
  }
  buffer += decoder.decode()
  consumeSseBuffer(`${buffer}\n\n`, handlers.onEvent)
}

function yieldToBrowser() {
  return new Promise((resolve) => {
    window.requestAnimationFrame(() => resolve())
  })
}

function consumeSseBuffer(buffer, onEvent) {
  const parts = buffer.split(/\r?\n\r?\n/)
  const remainder = parts.pop() ?? ''
  for (const part of parts) {
    let event = 'message'
    const dataLines = []
    for (const line of part.split(/\r?\n/)) {
      if (line.startsWith('event:')) {
        event = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trim())
      }
    }
    const dataText = dataLines.join('\n')
    if (!dataText) continue
    const data = parseJsonResponse(dataText) ?? { content: dataText }
    onEvent?.(event, data)
  }
  return remainder
}

export async function getSystemSettings(token) {
  return apiRequest('/api/settings/system', { token })
}

export async function changeAccountPassword(token, payload) {
  return apiRequest('/api/settings/system/account/password', {
    method: 'POST',
    token,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function listApiSettings(token) {
  return apiRequest('/api/settings/models', { token })
}

export async function saveApiSetting(token, provider, payload) {
  return apiRequest(`/api/settings/models/${provider}`, {
    method: 'PUT',
    token,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function testApiSetting(token, provider) {
  return apiRequest(`/api/settings/models/${provider}/test`, {
    method: 'POST',
    token,
  })
}

export async function listAvailableModels(token, provider) {
  return apiRequest(`/api/settings/models/${provider}/available-models`, { token })
}
