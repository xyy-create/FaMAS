<script setup>
import { computed } from 'vue'

const props = defineProps({
  selectedDocument: {
    type: Object,
    required: true,
  },
  selectedJobs: {
    type: Array,
    required: true,
  },
  selectedJobLogs: {
    type: Object,
    default: null,
  },
  schemaVersions: {
    type: Array,
    required: true,
  },
  selectedSchemaId: {
    type: [Number, String, null],
    default: null,
  },
  compareSchemaId: {
    type: [Number, String, null],
    default: null,
  },
  schemaEditTitle: {
    type: String,
    required: true,
  },
  schemaEditPrompt: {
    type: String,
    required: true,
  },
  schemaEditJson: {
    type: String,
    required: true,
  },
  schemaRewriteInstruction: {
    type: String,
    required: true,
  },
  schemaBuildVersionId: {
    type: String,
    required: true,
  },
  isLoadingDetails: {
    type: Boolean,
    required: true,
  },
  isLoadingSchemas: {
    type: Boolean,
    required: true,
  },
  isSavingMetadata: {
    type: Boolean,
    required: true,
  },
  schemaAction: {
    type: String,
    required: true,
  },
  metadataEdit: {
    type: Object,
    required: true,
  },
  schemaFormPreview: {
    type: Object,
    required: true,
  },
  schemaComparison: {
    type: Object,
    default: null,
  },
  availableCompareSchemas: {
    type: Array,
    required: true,
  },
  canBuildGraph: {
    type: Function,
    required: true,
  },
  formatDate: {
    type: Function,
    required: true,
  },
  formatSize: {
    type: Function,
    required: true,
  },
  documentStatusLabel: {
    type: Function,
    required: true,
  },
  displayValue: {
    type: Function,
    required: true,
  },
  schemaVersionLabel: {
    type: Function,
    required: true,
  },
  schemaSummary: {
    type: Function,
    required: true,
  },
  stageLabel: {
    type: Function,
    required: true,
  },
  jobStatusLabel: {
    type: Function,
    required: true,
  },
})

const emit = defineEmits([
  'close',
  'refresh',
  'generate-template',
  'select-schema',
  'save-schema',
  'copy-schema',
  'activate-schema',
  'rewrite-schema',
  'build-graph',
  'view-job',
  'save-metadata',
  'add-schema-object-item',
  'update-schema-object-item',
  'remove-schema-array-item',
  'add-schema-text-item',
  'update-schema-text-item',
  'update:schemaEditTitle',
  'update:schemaEditPrompt',
  'update:schemaEditJson',
  'update:schemaRewriteInstruction',
  'update:schemaBuildVersionId',
  'update:compareSchemaId',
])

const selectedSchemaVersion = computed(() =>
  props.schemaVersions.find((version) => version.id === props.selectedSchemaId) ?? null,
)

const schemaEditTitleModel = computed({
  get: () => props.schemaEditTitle,
  set: (value) => emit('update:schemaEditTitle', value),
})

const schemaEditPromptModel = computed({
  get: () => props.schemaEditPrompt,
  set: (value) => emit('update:schemaEditPrompt', value),
})

const schemaEditJsonModel = computed({
  get: () => props.schemaEditJson,
  set: (value) => emit('update:schemaEditJson', value),
})

const schemaRewriteInstructionModel = computed({
  get: () => props.schemaRewriteInstruction,
  set: (value) => emit('update:schemaRewriteInstruction', value),
})

const schemaBuildVersionIdModel = computed({
  get: () => props.schemaBuildVersionId,
  set: (value) => emit('update:schemaBuildVersionId', value),
})

const compareSchemaIdModel = computed({
  get: () => props.compareSchemaId,
  set: (value) => emit('update:compareSchemaId', value),
})
</script>

<template>
  <section class="content-panel document-detail-panel embedded-document-detail">
    <div class="panel-header">
      <div>
        <h2>{{ selectedDocument.filename }}</h2>
        <p>处理任务与日志</p>
      </div>
      <div class="inline-actions">
        <button class="secondary-button" type="button" @click="emit('refresh')">
          刷新详情
        </button>
        <button class="secondary-button" type="button" @click="emit('close')">
          关闭
        </button>
      </div>
    </div>

    <div class="detail-grid">
      <div>
        <div class="detail-list">
          <div class="detail-item">
            <span>状态</span>
            <strong>{{ documentStatusLabel(selectedDocument.status) }}</strong>
          </div>
          <div class="detail-item">
            <span>上传时间</span>
            <strong>{{ formatDate(selectedDocument.uploaded_at) }}</strong>
          </div>
          <div class="detail-item">
            <span>大小</span>
            <strong>{{ formatSize(selectedDocument.file_size_bytes) }}</strong>
          </div>
          <div class="detail-item">
            <span>学科</span>
            <strong>{{ displayValue(selectedDocument.subject) || '-' }}</strong>
          </div>
          <div class="detail-item">
            <span>年级</span>
            <strong>{{ displayValue(selectedDocument.grade) || '-' }}</strong>
          </div>
          <div class="detail-item">
            <span>出版社</span>
            <strong>{{ displayValue(selectedDocument.publisher) || '-' }}</strong>
          </div>
          <div class="detail-item">
            <span>教材</span>
            <strong>{{ displayValue(selectedDocument.textbook) || '-' }}</strong>
          </div>
          <div class="detail-item">
            <span>教材版本</span>
            <strong>{{ displayValue(selectedDocument.textbook_version) || '-' }}</strong>
          </div>
        </div>

        <section class="schema-workspace">
          <div class="schema-workspace-head">
            <div>
              <h3>Schema 工作区</h3>
              <p>为当前 PDF 管理可预览、可编辑、可启用的 schema 版本。</p>
            </div>
            <button
              class="secondary-button"
              type="button"
              :disabled="isLoadingSchemas || schemaAction === 'template'"
              @click="emit('generate-template')"
            >
              {{ schemaAction === 'template' ? '生成中...' : '生成推荐模板' }}
            </button>
          </div>

          <div v-if="schemaVersions.length" class="schema-workspace-grid">
            <div class="schema-version-list">
              <button
                v-for="version in schemaVersions"
                :key="version.id"
                class="schema-version-button"
                :class="{ active: selectedSchemaId === version.id }"
                type="button"
                @click="emit('select-schema', version)"
              >
                <span>{{ schemaVersionLabel(version) }}</span>
                <strong>{{ version.title }}</strong>
                <small>{{ schemaSummary(version) }}</small>
                <em v-if="version.is_active">启用中</em>
              </button>
            </div>

            <form class="schema-editor" @submit.prevent="$emit('save-schema')">
              <label class="form-field">
                <span>版本名称</span>
                <input v-model="schemaEditTitleModel" type="text" placeholder="schema 名称" maxlength="255" />
              </label>
              <label class="form-field">
                <span>修改要求 / 提示词</span>
                <textarea
                  v-model="schemaEditPromptModel"
                  rows="3"
                  placeholder="可写下你希望这个 schema 重点抽取什么"
                ></textarea>
              </label>
              <section class="schema-structured-editor">
                <div class="schema-structured-head">
                  <div>
                    <h4>表格式预览与编辑</h4>
                    <p>常用字段可以直接在这里改，下面的 JSON 会同步更新。</p>
                  </div>
                  <span v-if="schemaFormPreview.invalid" class="schema-form-error">
                    {{ schemaFormPreview.error }}
                  </span>
                </div>

                <div class="schema-structured-columns">
                  <div class="schema-structured-block">
                    <div class="schema-block-head">
                      <strong>节点类型</strong>
                      <button class="text-button" type="button" @click="emit('add-schema-object-item', 'node_types')">
                        新增节点
                      </button>
                    </div>
                    <div v-if="schemaFormPreview.nodeTypes.length" class="schema-form-list">
                      <div
                        v-for="(item, index) in schemaFormPreview.nodeTypes"
                        :key="`node-${index}`"
                        class="schema-form-row"
                      >
                        <input
                          :value="item.type ?? ''"
                          type="text"
                          placeholder="类型标识"
                          @input="emit('update-schema-object-item', 'node_types', index, 'type', $event.target.value)"
                        />
                        <input
                          :value="item.display_name ?? ''"
                          type="text"
                          placeholder="中文名称"
                          @input="emit('update-schema-object-item', 'node_types', index, 'display_name', $event.target.value)"
                        />
                        <input
                          :value="item.description ?? ''"
                          type="text"
                          placeholder="说明"
                          @input="emit('update-schema-object-item', 'node_types', index, 'description', $event.target.value)"
                        />
                        <button
                          class="schema-mini-button"
                          type="button"
                          title="删除节点类型"
                          @click="emit('remove-schema-array-item', 'node_types', index)"
                        >
                          ×
                        </button>
                      </div>
                    </div>
                    <p v-else class="schema-empty-note">暂无节点类型。</p>
                  </div>

                  <div class="schema-structured-block">
                    <div class="schema-block-head">
                      <strong>关系类型</strong>
                      <button class="text-button" type="button" @click="emit('add-schema-object-item', 'relation_types')">
                        新增关系
                      </button>
                    </div>
                    <div v-if="schemaFormPreview.relationTypes.length" class="schema-form-list">
                      <div
                        v-for="(item, index) in schemaFormPreview.relationTypes"
                        :key="`relation-${index}`"
                        class="schema-form-row"
                      >
                        <input
                          :value="item.type ?? ''"
                          type="text"
                          placeholder="关系标识"
                          @input="emit('update-schema-object-item', 'relation_types', index, 'type', $event.target.value)"
                        />
                        <input
                          :value="item.display_name ?? ''"
                          type="text"
                          placeholder="中文名称"
                          @input="emit('update-schema-object-item', 'relation_types', index, 'display_name', $event.target.value)"
                        />
                        <input
                          :value="item.description ?? ''"
                          type="text"
                          placeholder="说明"
                          @input="emit('update-schema-object-item', 'relation_types', index, 'description', $event.target.value)"
                        />
                        <button
                          class="schema-mini-button"
                          type="button"
                          title="删除关系类型"
                          @click="emit('remove-schema-array-item', 'relation_types', index)"
                        >
                          ×
                        </button>
                      </div>
                    </div>
                    <p v-else class="schema-empty-note">暂无关系类型。</p>
                  </div>
                </div>

                <div class="schema-structured-columns">
                  <div class="schema-structured-block">
                    <div class="schema-block-head">
                      <strong>抽取规则</strong>
                      <button class="text-button" type="button" @click="emit('add-schema-text-item', 'extraction_rules')">
                        新增规则
                      </button>
                    </div>
                    <div class="schema-form-list">
                      <div
                        v-for="(rule, index) in schemaFormPreview.extractionRules"
                        :key="`rule-${index}`"
                        class="schema-text-row"
                      >
                        <input
                          :value="rule"
                          type="text"
                          placeholder="抽取规则"
                          @input="emit('update-schema-text-item', 'extraction_rules', index, $event.target.value)"
                        />
                        <button
                          class="schema-mini-button"
                          type="button"
                          title="删除规则"
                          @click="emit('remove-schema-array-item', 'extraction_rules', index)"
                        >
                          ×
                        </button>
                      </div>
                    </div>
                  </div>

                  <div class="schema-structured-block">
                    <div class="schema-block-head">
                      <strong>质量约束</strong>
                      <button class="text-button" type="button" @click="emit('add-schema-text-item', 'quality_constraints')">
                        新增约束
                      </button>
                    </div>
                    <div class="schema-form-list">
                      <div
                        v-for="(rule, index) in schemaFormPreview.qualityConstraints"
                        :key="`constraint-${index}`"
                        class="schema-text-row"
                      >
                        <input
                          :value="rule"
                          type="text"
                          placeholder="质量约束"
                          @input="emit('update-schema-text-item', 'quality_constraints', index, $event.target.value)"
                        />
                        <button
                          class="schema-mini-button"
                          type="button"
                          title="删除约束"
                          @click="emit('remove-schema-array-item', 'quality_constraints', index)"
                        >
                          ×
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </section>

              <section v-if="availableCompareSchemas.length" class="schema-compare-panel">
                <div class="schema-structured-head">
                  <div>
                    <h4>版本对比</h4>
                    <p>用当前正在编辑的版本，对比另一个 schema 的类型与规则差异。</p>
                  </div>
                  <label class="form-field">
                    <span>对比版本</span>
                    <select v-model="compareSchemaIdModel">
                      <option :value="null">选择版本</option>
                      <option v-for="version in availableCompareSchemas" :key="version.id" :value="version.id">
                        v{{ version.version_number }} · {{ version.title }}
                      </option>
                    </select>
                  </label>
                </div>

                <div v-if="schemaComparison" class="schema-compare-grid">
                  <div class="schema-compare-block">
                    <strong>节点类型</strong>
                    <div class="schema-compare-list">
                      <span
                        v-for="item in schemaComparison.nodes"
                        :key="`compare-node-${item.key}`"
                        class="schema-compare-item"
                        :class="`schema-compare-${item.status}`"
                      >
                        <span>{{ item.label }}</span>
                        <em>{{ item.statusLabel }}</em>
                      </span>
                    </div>
                  </div>
                  <div class="schema-compare-block">
                    <strong>关系类型</strong>
                    <div class="schema-compare-list">
                      <span
                        v-for="item in schemaComparison.relations"
                        :key="`compare-relation-${item.key}`"
                        class="schema-compare-item"
                        :class="`schema-compare-${item.status}`"
                      >
                        <span>{{ item.label }}</span>
                        <em>{{ item.statusLabel }}</em>
                      </span>
                    </div>
                  </div>
                  <div class="schema-compare-block">
                    <strong>抽取规则</strong>
                    <div class="schema-compare-list">
                      <span
                        v-for="item in schemaComparison.extractionRules"
                        :key="`compare-rule-${item.key}`"
                        class="schema-compare-item"
                        :class="`schema-compare-${item.status}`"
                      >
                        <span>{{ item.label }}</span>
                        <em>{{ item.statusLabel }}</em>
                      </span>
                    </div>
                  </div>
                  <div class="schema-compare-block">
                    <strong>质量约束</strong>
                    <div class="schema-compare-list">
                      <span
                        v-for="item in schemaComparison.qualityConstraints"
                        :key="`compare-constraint-${item.key}`"
                        class="schema-compare-item"
                        :class="`schema-compare-${item.status}`"
                      >
                        <span>{{ item.label }}</span>
                        <em>{{ item.statusLabel }}</em>
                      </span>
                    </div>
                  </div>
                </div>
                <p v-else class="schema-empty-note">请选择一个版本进行对比。</p>
              </section>

              <label class="form-field">
                <span>Schema JSON</span>
                <textarea
                  v-model="schemaEditJsonModel"
                  class="schema-json-editor"
                  rows="14"
                  spellcheck="false"
                  placeholder="这里预览和编辑 schema JSON"
                ></textarea>
              </label>

              <div class="schema-editor-actions">
                <button class="primary-button" type="submit" :disabled="!selectedSchemaVersion || Boolean(schemaAction)">
                  {{ schemaAction === 'save' ? '保存中...' : '保存修改' }}
                </button>
                <button
                  class="secondary-button"
                  type="button"
                  :disabled="!selectedSchemaVersion || Boolean(schemaAction)"
                  @click="emit('copy-schema')"
                >
                  {{ schemaAction === 'copy' ? '复制中...' : '复制为新版本' }}
                </button>
                <button
                  class="secondary-button"
                  type="button"
                  :disabled="!selectedSchemaVersion || selectedSchemaVersion.is_active || Boolean(schemaAction)"
                  @click="emit('activate-schema')"
                >
                  {{ schemaAction === 'activate' ? '启用中...' : '设为启用' }}
                </button>
              </div>

              <section class="schema-assist-panel">
                <div>
                  <h4>模型辅助修改</h4>
                  <p>基于当前版本生成新版本，不会直接覆盖正在编辑的 schema。</p>
                </div>
                <textarea
                  v-model="schemaRewriteInstructionModel"
                  rows="3"
                  placeholder="写下你希望模型怎样调整 schema，例如：更重视教材插图和实验步骤。"
                ></textarea>
                <div class="schema-editor-actions">
                  <button class="secondary-button" type="button" @click="emit('rewrite-schema', 'image')">
                    强化图片证据
                  </button>
                  <button class="secondary-button" type="button" @click="emit('rewrite-schema', 'classroom')">
                    面向课堂讲解
                  </button>
                  <button class="secondary-button" type="button" @click="emit('rewrite-schema', 'dedupe')">
                    减少无效关系
                  </button>
                  <button class="secondary-button" type="button" @click="emit('rewrite-schema', '')">
                    {{ schemaAction === 'llm' ? '生成中...' : '按输入修改' }}
                  </button>
                </div>
              </section>

              <section class="schema-assist-panel">
                <div>
                  <h4>本次构图 schema</h4>
                  <p>只影响下一次从这里启动的构图任务，不会改变启用版本。</p>
                </div>
                <div class="schema-build-row">
                  <label class="form-field">
                    <span>选择版本</span>
                      <select v-model="schemaBuildVersionIdModel">
                      <option value="active">使用当前启用版本</option>
                      <option v-for="version in schemaVersions" :key="version.id" :value="String(version.id)">
                        v{{ version.version_number }} · {{ version.title }}
                      </option>
                    </select>
                  </label>
                  <button
                    class="primary-button"
                    type="button"
                    :disabled="Boolean(schemaAction) || !canBuildGraph(selectedDocument)"
                    @click="emit('build-graph')"
                  >
                    {{ canBuildGraph(selectedDocument) ? '用所选版本构图' : '无法构图' }}
                  </button>
                </div>
              </section>
            </form>
          </div>

          <p v-else class="empty-table-state">
            当前 PDF 还没有 schema 版本，可先生成一份系统推荐模板。
          </p>
        </section>

        <div class="job-list">
          <button
            v-for="job in selectedJobs"
            :key="job.id"
            class="job-log-button"
            type="button"
            @click="emit('view-job', job)"
          >
            <span>{{ stageLabel(job.stage) }}</span>
            <strong>{{ jobStatusLabel(job.status) }}</strong>
            <small>{{ formatDate(job.created_at) }}</small>
          </button>
        </div>

        <p v-if="!isLoadingDetails && selectedJobs.length === 0" class="empty-table-state">
          暂无任务记录。
        </p>

        <form class="settings-form metadata-edit-form" @submit.prevent="emit('save-metadata')">
          <h3>文档信息</h3>
          <label class="form-field">
            <span>学科</span>
            <input v-model="metadataEdit.subject" type="text" placeholder="如：化学" />
          </label>
          <label class="form-field">
            <span>年级</span>
            <input v-model="metadataEdit.grade" type="text" placeholder="如：高中" />
          </label>
          <label class="form-field">
            <span>出版社</span>
            <input v-model="metadataEdit.publisher" type="text" placeholder="如：苏教版" />
          </label>
          <label class="form-field">
            <span>教材</span>
            <input v-model="metadataEdit.textbook" type="text" placeholder="教材名称" />
          </label>
          <label class="form-field">
            <span>教材版本</span>
            <input
              v-model="metadataEdit.textbook_version"
              type="text"
              placeholder="可选版本"
            />
          </label>
          <button class="primary-button" type="submit" :disabled="isSavingMetadata">
            {{ isSavingMetadata ? '保存中...' : '保存文档信息' }}
          </button>
        </form>
      </div>

      <div class="log-viewer">
        <div class="log-header">
          <strong>
            {{ selectedJobLogs ? `${stageLabel(selectedJobLogs.job.stage)}日志` : '日志' }}
          </strong>
          <span v-if="isLoadingDetails">加载中...</span>
        </div>
        <pre v-if="selectedJobLogs">{{ selectedJobLogs.logs.stdout || '暂无标准输出日志。' }}</pre>
        <pre v-if="selectedJobLogs?.logs?.stderr">{{ selectedJobLogs.logs.stderr }}</pre>
        <pre v-if="selectedJobLogs?.logs?.traceback">{{ selectedJobLogs.logs.traceback }}</pre>
        <p v-if="!selectedJobLogs" class="empty-table-state">选择任务后查看日志。</p>
      </div>
    </div>
  </section>
</template>
