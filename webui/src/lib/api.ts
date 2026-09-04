import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Types
export interface CrawlerConfig {
  platform: string
  login_type: string
  crawler_type: string
  keywords: string
  start_page: number
  enable_comments: boolean
  enable_sub_comments: boolean
  save_option: string
  cookies: string
  headless: boolean
  max_notes_count: number
}

export interface CrawlerStatus {
  status: 'idle' | 'running' | 'stopping' | 'error'
  platform: string | null
  crawler_type: string | null
  started_at: string | null
  error_message: string | null
}

export interface LogEntry {
  id: number
  timestamp: string
  level: 'info' | 'warning' | 'error' | 'success' | 'debug'
  message: string
}

export interface DataFile {
  name: string
  path: string
  size: number
  modified_at: number
  record_count: number | null
  analyzed_count: number
  type: string
}

export interface FilePreviewResponse {
  data: Record<string, unknown>[]
  row_indices: number[]
  analyzed: boolean[]
  total: number
  all_total: number
  columns?: string[]
}

export interface Platform {
  value: string
  label: string
  icon: string
}

export interface ConfigOption {
  value: string
  label: string
}

export interface AILead {
  id: string
  company_name: string
  aliases: string
  company_info: string
  country: string
  website: string
  email: string
  phone: string
  address: string
  contact_person: string
  patents: string
  patent_titles: string
  keywords: string
  source_platform: string
  source_urls: string
  evidence: string
  potential_score: number
  next_action: string
  followed_up: boolean
  created_at: string
  updated_at: string
}

export interface AIIntelligence {
  id: string
  title: string
  summary: string
  event_date: string
  materials: string
  source_platform: string
  source_url: string
  evidence: string
  analysis: string
  reliability_score: number
  reliability_reason: string
  impact: string
  next_action: string
  created_at: string
  updated_at: string
}

// API functions
export const crawlerApi = {
  start: (config: CrawlerConfig) => api.post('/crawler/start', config),
  stop: () => api.post('/crawler/stop'),
  getStatus: () => api.get<CrawlerStatus>('/crawler/status'),
  getLogs: (limit = 100) => api.get<{ logs: LogEntry[] }>('/crawler/logs', { params: { limit } }),
}

export const dataApi = {
  getFiles: (platform?: string, fileType?: string) =>
    api.get<{ files: DataFile[] }>('/data/files', { params: { platform, file_type: fileType } }),
  deleteAllFiles: () => api.delete<{ deleted: number }>('/data/files'),
  deleteFile: (path: string) => api.delete<{ deleted: string }>('/data/files/' + encodeDataPath(path)),
  renameFile: (path: string, name: string) =>
    api.patch<{ file: DataFile }>('/data/files/' + encodeDataPath(path), { name }),
  getFileContent: (path: string, limit = 50, offset = 0, query = '') =>
    api.get<FilePreviewResponse>('/data/files/' + path, {
      params: { preview: true, limit, offset, query },
    }),
  getStats: () => api.get('/data/stats'),
  getDownloadUrl: (path: string) => `/api/data/download/${path}`,
}

function encodeDataPath(path: string) {
  return path.split('/').map(encodeURIComponent).join('/')
}

export const configApi = {
  getPlatforms: () => api.get<{ platforms: Platform[] }>('/config/platforms'),
  getOptions: () =>
    api.get<{
      login_types: ConfigOption[]
      crawler_types: ConfigOption[]
      save_options: ConfigOption[]
    }>('/config/options'),
}

export interface EnvCheckResult {
  success: boolean
  message: string
  output?: string
  error?: string
}

export const envApi = {
  check: () => api.get<EnvCheckResult>('/env/check'),
}

export const aiApi = {
  status: () => api.get<{
    model: string
    api_configured: boolean
    access_configured: boolean
    usage: { calls?: number; input_tokens?: number; output_tokens?: number; total_tokens?: number; tracking_since?: string }
  }>('/ai/status'),
  chat: (payload: {
    message: string
    history: { role: 'user' | 'assistant'; content: string }[]
    platform: string
    max_records: number
    include_search_data?: boolean
    source_file?: string
    source_files?: string[]
    record_indices?: number[]
    target_lead_id?: string
  }) => api.post<{ answer: string; leads_saved: number; intelligence_saved: number; records_used: number; source_file: string }>(
    '/ai/chat', payload, { timeout: 120000 },
  ),
  getLeads: () => api.get<{ leads: AILead[] }>('/ai/leads'),
  getIntelligence: () => api.get<{ items: AIIntelligence[] }>('/ai/intelligence'),
  getHistory: () => api.get<{ messages: { role: 'user' | 'assistant'; content: string; created_at?: string }[] }>(
    '/ai/history',
  ),
  clearHistory: () => api.delete<{ deleted: number }>('/ai/history'),
  updateLead: (id: string, followed_up: boolean) => api.patch(
    `/ai/leads/${encodeURIComponent(id)}`, { followed_up },
  ),
  deleteLead: (id: string) => api.delete(`/ai/leads/${encodeURIComponent(id)}`),
  deleteIntelligence: (id: string) => api.delete(`/ai/intelligence/${encodeURIComponent(id)}`),
  exportLeads: () => api.get<Blob>('/ai/leads/export', { responseType: 'blob' }),
  exportIntelligence: () => api.get<Blob>('/ai/intelligence/export', { responseType: 'blob' }),
}

export default api
