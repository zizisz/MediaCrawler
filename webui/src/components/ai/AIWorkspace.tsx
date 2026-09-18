import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Bot, Building2, Copy, Download, ImagePlus, Linkedin, Mail, Newspaper, RefreshCw, Search, Send, Sparkles, Trash2, Users } from 'lucide-react'
import { aiApi, type AIIntelligence, type AILead } from '@/lib/api'
import { useCrawlerStore } from '@/store/crawlerStore'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog'

type Message = { role: 'user' | 'assistant'; content: string }
type AIStatus = {
  model: string
  provider: 'qwen' | 'gemini'
  providers: { qwen: boolean; gemini: boolean }
  material_scope?: string
  api_configured: boolean
  access_configured: boolean
  usage: { calls?: number; input_tokens?: number; output_tokens?: number; total_tokens?: number; tracking_since?: string }
}
const GREETING: Message = { role: 'assistant', content: '我是工程塑料零件客户分析助手。可分批分析搜索结果，识别企业角色、材料牌号、零件用途及采购线索，也可以询问企业和行业动态。' }
const links = (value = '') => [...new Set(value.match(/https?:\/\/[^\s'"\],;]+/g) || [])]
const webUrl = (value: string) => /^https?:\/\//i.test(value) ? value : `https://${value}`
const keywords = (value = '') => [...new Set(value.replace(/[\[\]'"\u201c\u201d]/g, '').split(/[,;；\n]/).map((item) => item.trim()).filter(Boolean))]
const TAG_SYNONYMS: Record<string, string> = { '耐温': '耐高温', '耐热': '耐高温', '高温耐受': '耐高温', '抗高温': '耐高温', '耐高温性能': '耐高温', '高精密': '高精度', '耐化学': '耐化学腐蚀', '极佳耐化学性': '耐化学腐蚀' }
const tags = (value = '') => [...new Set(keywords(value).map((tag) => TAG_SYNONYMS[tag] || tag))]
const TAG_FIELDS = [['industry_tags', '行业'], ['product_tags', '产品'], ['part_tags', '零件'], ['condition_tags', '工况']] as const
type TagField = typeof TAG_FIELDS[number][0]
const leadDate = (value = '') => value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '未知'
const firstEmail = (value = '') => value.split(/[;；,\s]+/).find((item) => item.includes('@')) || ''
const EMAIL_SUBJECT = '关于工程塑料型材及零部件合作咨询'

function errorMessage(error: unknown) {
  if (axios.isAxiosError(error)) return error.response?.data?.detail || error.message
  return error instanceof Error ? error.message : '请求失败'
}

export function AIWorkspace({ view = 'leads' }: { view?: 'analysis' | 'leads' | 'intelligence' }) {
  const config = useCrawlerStore((state) => state.config)
  const [status, setStatus] = useState<AIStatus>()
  const [input, setInput] = useState('')
  const [leadSearch, setLeadSearch] = useState('')
  const [leadSort, setLeadSort] = useState<'default' | 'potential' | 'created'>('default')
  const [pathFilters, setPathFilters] = useState<Partial<Record<TagField, string>>>({})
  const [localBusy, setBusy] = useState(false)
  const { data: batch, refetch: refetchBatch } = useQuery({
    queryKey: ['aiBatch'], queryFn: async () => (await aiApi.batchStatus()).data, refetchInterval: 2000,
  })
  const batchBusy = batch?.status === 'running' || batch?.status === 'stopping'
  const [updatingLeadId, setUpdatingLeadId] = useState<string>()
  const [similarLeadId, setSimilarLeadId] = useState<string>()
  const { data: similarJob, refetch: refetchSimilar } = useQuery({
    queryKey: ['similarJob'], queryFn: async () => (await aiApi.similarStatus()).data, refetchInterval: 2000,
  })
  const similarBusy = Boolean(similarLeadId) || similarJob?.status === 'running'
  const [seedCompany, setSeedCompany] = useState('')
  const [seedRegion, setSeedRegion] = useState('')
  const [seedDialogOpen, setSeedDialogOpen] = useState(false)
  const [seedSubmitting, setSeedSubmitting] = useState(false)
  const { data: seedJob, refetch: refetchSeed } = useQuery({
    queryKey: ['seedSearchJob'], queryFn: async () => (await aiApi.seedSearchStatus()).data, refetchInterval: 2000,
  })
  const seedBusy = seedSubmitting || seedJob?.status === 'running'
  const busy = localBusy || batchBusy || similarBusy || seedBusy
  const [linkedinLead, setLinkedinLead] = useState<AILead>()
  const [linkedinUrl, setLinkedinUrl] = useState('')
  const [linkedinSubmitting, setLinkedinSubmitting] = useState(false)
  const [emailLead, setEmailLead] = useState<AILead>()
  const [emailDraft, setEmailDraft] = useState('')
  const [emailError, setEmailError] = useState('')
  const [emailGenerating, setEmailGenerating] = useState(false)
  const [emailSaving, setEmailSaving] = useState(false)
  const [emailLanguage, setEmailLanguage] = useState('英语')
  const [emailTranslations, setEmailTranslations] = useState<Record<string, string>>({})
  const [emailTranslation, setEmailTranslation] = useState('')
  const [emailTranslating, setEmailTranslating] = useState(false)
  const [emailRecipient, setEmailRecipient] = useState('')
  const [emailSubject, setEmailSubject] = useState(EMAIL_SUBJECT)
  const [emailTranslationSubject, setEmailTranslationSubject] = useState('')
  const [emailSending, setEmailSending] = useState(false)
  const [emailScheduleAt, setEmailScheduleAt] = useState('')
  const [emailScheduleTimezone, setEmailScheduleTimezone] = useState('America/Toronto')
  const [emailScheduling, setEmailScheduling] = useState(false)
  const [noteImage, setNoteImage] = useState<{ lead: AILead; image: string }>()
  const { data: linkedinJob, refetch: refetchLinkedin } = useQuery({
    queryKey: ['linkedinJob'], queryFn: async () => (await aiApi.linkedinStatus()).data, refetchInterval: 2000,
  })
  const linkedinBusy = linkedinSubmitting || linkedinJob?.status === 'running'
  const [messages, setMessages] = useState<Message[]>([GREETING])
  const [leads, setLeads] = useState<AILead[]>([])
  const [intelligence, setIntelligence] = useState<AIIntelligence[]>([])
  const chatRef = useRef<HTMLDivElement>(null)

  const refreshResults = async () => {
    const [leadResponse, intelResponse] = await Promise.all([aiApi.getLeads(), aiApi.getIntelligence()])
    setLeads(leadResponse.data.leads)
    setIntelligence(intelResponse.data.items)
  }

  const loadWorkspace = async () => {
    const [leadResponse, intelResponse, historyResponse] = await Promise.all([
      aiApi.getLeads(),
      aiApi.getIntelligence(),
      aiApi.getHistory(),
    ])
    setLeads(leadResponse.data.leads)
    setIntelligence(intelResponse.data.items)
    setMessages(historyResponse.data.messages.length ? historyResponse.data.messages : [GREETING])
  }

  useEffect(() => {
    if (linkedinJob?.status === 'completed') refreshResults().catch(() => undefined)
  }, [linkedinJob?.id, linkedinJob?.status])

  useEffect(() => {
    if (similarJob?.status === 'running') setSimilarLeadId(similarJob.lead_id)
    if (similarJob?.status === 'completed' || similarJob?.status === 'error') {
      setSimilarLeadId(undefined)
      loadWorkspace().catch(() => undefined)
    }
  }, [similarJob?.id, similarJob?.status])

  useEffect(() => {
    if (seedJob?.status === 'completed' || seedJob?.status === 'error') loadWorkspace().catch(() => undefined)
  }, [seedJob?.id, seedJob?.status])

  const collectLinkedin = async () => {
    if (!linkedinLead || linkedinBusy) return
    setLinkedinSubmitting(true)
    try {
      await aiApi.collectLinkedin(linkedinLead.id, linkedinUrl.trim())
      await refetchLinkedin()
      setLinkedinLead(undefined)
    } catch (error) {
      window.alert(`领英采集失败：${errorMessage(error)}`)
    } finally {
      setLinkedinSubmitting(false)
    }
  }

  const setSavedEmailLead = (lead: AILead) => {
    setEmailLead(lead)
    setLeads((old) => old.map((item) => item.id === lead.id ? lead : item))
  }

  const generateRecommendedEmail = async (lead: AILead) => {
    setEmailLead(lead)
    setEmailDraft('')
    setEmailTranslations({})
    setEmailTranslation('')
    setEmailError('')
    setEmailGenerating(true)
    try {
      const { data } = await aiApi.recommendedEmail(lead.id)
      setEmailDraft(data.email)
      setEmailSubject(data.subject)
      setSavedEmailLead(data.lead)
    } catch (error) {
      setEmailError(errorMessage(error))
    } finally {
      setEmailGenerating(false)
    }
  }

  const openRecommendedEmail = (lead: AILead) => {
    setEmailLead(lead)
    setEmailDraft(lead.recommended_email || '')
    const translations = lead.recommended_email_translations || {}
    setEmailTranslations(translations)
    setEmailTranslation(translations[emailLanguage] || '')
    setEmailRecipient(firstEmail(lead.email))
    setEmailSubject(lead.recommended_email_subject || EMAIL_SUBJECT)
    setEmailTranslationSubject(lead.recommended_email_translation_subjects?.[emailLanguage] || '')
    setEmailScheduleAt(lead.scheduled_email?.status === 'scheduled' ? lead.scheduled_email.local_time || '' : '')
    setEmailScheduleTimezone(lead.scheduled_email?.timezone || 'America/Toronto')
    setEmailError('')
    if (!lead.recommended_email) void generateRecommendedEmail(lead)
  }

  const saveRecommendedEmail = async () => {
    if (!emailLead) return
    setEmailSaving(true)
    try {
      const { data } = await aiApi.updateLead(emailLead.id, { recommended_email: emailDraft, recommended_email_subject: emailSubject })
      setSavedEmailLead(data.lead)
      setEmailTranslations({})
      setEmailTranslation('')
    } catch (error) {
      setEmailError(errorMessage(error))
    } finally {
      setEmailSaving(false)
    }
  }

  const translateRecommendedEmail = async () => {
    if (!emailLead || !emailDraft.trim()) return
    setEmailError('')
    setEmailTranslating(true)
    try {
      const { data } = await aiApi.translateRecommendedEmail(emailLead.id, emailDraft, emailSubject, emailLanguage)
      setEmailTranslation(data.translation)
      setEmailTranslationSubject(data.subject)
      setEmailTranslations(data.lead.recommended_email_translations || {})
      setSavedEmailLead(data.lead)
    } catch (error) {
      setEmailError(errorMessage(error))
    } finally {
      setEmailTranslating(false)
    }
  }

  const sendRecommendedEmail = async (subject: string, body: string) => {
    if (!emailLead || !emailRecipient.trim() || !subject.trim() || !body.trim()) return
    if (!window.confirm(`确定向 ${emailRecipient.trim()} 发送此邮件吗？`)) return
    setEmailError('')
    setEmailSending(true)
    try {
      const { data } = await aiApi.sendRecommendedEmail(emailLead.id, emailRecipient.trim(), subject.trim(), body)
      setSavedEmailLead(data.lead)
      window.alert(data.warning ? `邮件已投递至 ${emailRecipient.trim()}，但${data.warning}` : `邮件已发送并保存至 Bossmail 已发邮件：${emailRecipient.trim()}`)
    } catch (error) {
      setEmailError(errorMessage(error))
    } finally {
      setEmailSending(false)
    }
  }

  const scheduleRecommendedEmail = async (subject: string, body: string) => {
    if (!emailLead || !emailRecipient.trim() || !subject.trim() || !body.trim() || !emailScheduleAt) return
    if (!window.confirm(`确定按加拿大当地时间 ${emailScheduleAt} 定时发送吗？`)) return
    setEmailError('')
    setEmailScheduling(true)
    try {
      const { data } = await aiApi.scheduleRecommendedEmail(emailLead.id, emailRecipient.trim(), subject.trim(), body, emailScheduleAt, emailScheduleTimezone)
      setSavedEmailLead(data.lead)
      window.alert('已安排定时发送')
    } catch (error) {
      setEmailError(errorMessage(error))
    } finally {
      setEmailScheduling(false)
    }
  }

  const copyRecommendedEmail = async (text = emailDraft, label = '推荐邮件') => {
    if (!text) return
    try {
      await navigator.clipboard?.writeText(text)
    } catch {
      const area = document.createElement('textarea')
      area.value = text
      document.body.append(area)
      area.select()
      document.execCommand('copy')
      area.remove()
    }
    window.alert(`${label}已复制`)
  }

  useEffect(() => {
    aiApi.status().then(({ data }) => setStatus(data)).catch(() => undefined)
    loadWorkspace().catch(() => undefined)
    const refresh = () => loadWorkspace().catch(() => undefined)
    const started = (event: Event) => {
      const fileCount = (event as CustomEvent<{ fileCount: number }>).detail.fileCount
      setBusy(true)
      setMessages((old) => [...old, { role: 'assistant', content: `已接收手动分析任务（${fileCount} 个数据文件），正在分析，请稍候……` }])
    }
    const completed = (event: Event) => {
      const answer = (event as CustomEvent<{ answer: string }>).detail.answer
      setMessages((old) => [...old, { role: 'assistant', content: answer }])
      setBusy(false)
      refreshResults().catch(() => undefined)
      aiApi.status().then(({ data }) => setStatus(data)).catch(() => undefined)
    }
    const failed = (event: Event) => {
      const message = (event as CustomEvent<{ message: string }>).detail.message
      setMessages((old) => [...old, { role: 'assistant', content: `手动分析失败：${message}` }])
      setBusy(false)
    }
    const providerChanged = (event: Event) => setStatus((event as CustomEvent<AIStatus>).detail)
    window.addEventListener('ai-analysis-updated', refresh)
    window.addEventListener('ai-manual-analysis-started', started)
    window.addEventListener('ai-manual-analysis-completed', completed)
    window.addEventListener('ai-manual-analysis-failed', failed)
    window.addEventListener('ai-provider-changed', providerChanged)
    return () => {
      window.removeEventListener('ai-analysis-updated', refresh)
      window.removeEventListener('ai-manual-analysis-started', started)
      window.removeEventListener('ai-manual-analysis-completed', completed)
      window.removeEventListener('ai-manual-analysis-failed', failed)
      window.removeEventListener('ai-provider-changed', providerChanged)
    }
  }, [])

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight
  }, [messages, busy])

  useEffect(() => {
    if (!batch?.id) return
    loadWorkspace().catch(() => undefined)
    aiApi.status().then(({ data }) => setStatus(data)).catch(() => undefined)
  }, [batch?.id, batch?.batches, batch?.status])

  const ask = async (question: string, includeSearchData = false, targetLeadId = '') => {
    const text = question.trim()
    if (!text || busy) return
    const history = messages.slice(-8)
    setMessages((old) => [...old, { role: 'user', content: text }])
    setInput('')
    setBusy(true)
    try {
      const { data } = await aiApi.chat({
        message: text,
        history,
        platform: config.platform,
        max_records: config.max_notes_count,
        include_search_data: includeSearchData,
        target_lead_id: targetLeadId,
      })
      setMessages((old) => [...old, { role: 'assistant', content: data.answer }])
      await refreshResults()
      aiApi.status().then(({ data: nextStatus }) => setStatus(nextStatus))
    } catch (error) {
      setMessages((old) => [...old, { role: 'assistant', content: `分析失败：${errorMessage(error)}` }])
    } finally {
      setBusy(false)
    }
  }

  const removeLead = async (id: string) => {
    await aiApi.deleteLead(id)
    setLeads((old) => old.filter((lead) => lead.id !== id))
  }

  const analyzeLatest = async () => {
    setBusy(true)
    try {
      await aiApi.startBatch([], config.platform)
      await refetchBatch()
      await loadWorkspace()
    } catch (error) {
      setMessages((old) => [...old, { role: 'assistant', content: `分析失败：${errorMessage(error)}` }])
    } finally {
      setBusy(false)
    }
  }

  const removeIntelligence = async (id: string) => {
    await aiApi.deleteIntelligence(id)
    setIntelligence((old) => old.filter((item) => item.id !== id))
  }

  const clearHistory = async () => {
    if (!window.confirm('确定清除全部 AI 聊天记录吗？企业线索不会被删除。')) return
    try {
      await aiApi.clearHistory()
      setMessages([GREETING])
    } catch (error) {
      window.alert(`清除失败：${errorMessage(error)}`)
    }
  }

  const setFollowedUp = async (lead: AILead, followed_up: boolean) => {
    await aiApi.updateLead(lead.id, { followed_up })
    setLeads((old) => old.map((item) => item.id === lead.id ? { ...item, followed_up } : item))
  }

  const setLowRelevance = async (lead: AILead, low_relevance: boolean) => {
    await aiApi.updateLead(lead.id, { low_relevance })
    setLeads((old) => old.map((item) => item.id === lead.id ? { ...item, low_relevance } : item))
  }

  const saveLeadNotes = async (lead: AILead) => {
    try {
      const { data } = await aiApi.updateLead(lead.id, { manual_notes: lead.manual_notes || '' })
      setLeads((old) => old.map((item) => item.id === lead.id ? data.lead : item))
    } catch (error) {
      window.alert(`备注保存失败：${errorMessage(error)}`)
      await refreshResults()
    }
  }

  const updateLeadFromWeb = async (lead: AILead) => {
    setUpdatingLeadId(lead.id)
    try {
      await ask(`请联网搜索并更新企业线索库中“${lead.company_name}”的最新公开资料。按系统定义的完整材料范围，核实其是否为工程塑料零件用户、设备制造商、加工商、贸易商或材料供应商；核实具体材料牌号、零件用途、应用行业和采购证据。若为中国企业，第一步必须执行公开网页检索：site:qcc.com "${lead.company_name}"，读取匹配企查查页面中公开显示的统一社会信用代码、电话、邮箱、官网、地址、法定代表人和经营状态；再以国家企业信用信息公示系统交叉核实，并参考天眼查、爱企查。海外企业优先使用当地公司登记库。官网、专利和技术资料只用于核实产品、材料与应用，不能以营销文案代替工商事实。联系方式必须逐项核验：企查查公开页面、官网首页与“联系我们”页、其他公开B2B企业页；发现公开邮箱、电话或联系人即写入，并把对应页面加入来源链接。不可访问、需登录或无公开展示的信息不要猜测或绕过。仅保存可验证信息，没有找到的字段保持空白。同时提取相关材料供需、价格、扩产、认证、技术、应用和市场传闻，标明日期、来源、可靠度及渠道，并保存到行业情报库。`, false, lead.id)
    } finally {
      setUpdatingLeadId(undefined)
    }
  }

  const findSimilarLeads = async (lead: AILead) => {
    setSimilarLeadId(lead.id)
    try {
      await aiApi.findSimilar(lead.id)
      await refetchSimilar()
    } catch (error) {
      setSimilarLeadId(undefined)
      window.alert(`同类企业搜索失败：${errorMessage(error)}`)
    }
  }

  const searchFromSeed = async () => {
    if (!seedCompany.trim() || seedBusy) return
    setSeedSubmitting(true)
    try {
      await aiApi.seedSearch(seedCompany.trim(), seedRegion.trim())
      await refetchSeed()
      setSeedDialogOpen(false)
    } catch (error) {
      window.alert(`种子企业搜索失败：${errorMessage(error)}`)
    } finally {
      setSeedSubmitting(false)
    }
  }

  const changeProvider = async (provider: 'qwen' | 'gemini') => {
    if (busy || status?.provider === provider) return
    setBusy(true)
    try {
      await aiApi.setProvider(provider)
      const { data } = await aiApi.status()
      setStatus(data)
      window.dispatchEvent(new CustomEvent('ai-provider-changed', { detail: data }))
    } catch (error) {
      window.alert(`切换模型失败：${errorMessage(error)}`)
    } finally {
      setBusy(false)
    }
  }

  const uploadNoteImages = async (lead: AILead, files: File[]) => {
    for (const file of files) {
      if (!file.type.startsWith('image/')) continue
      try {
        if (file.size > 5 * 1024 * 1024) throw new Error('图片须小于 5MB')
        const dataUrl = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader()
          reader.onload = () => resolve(String(reader.result))
          reader.onerror = () => reject(new Error('图片读取失败'))
          reader.readAsDataURL(file)
        })
        const { data } = await aiApi.uploadNoteImage(lead.id, dataUrl)
        setLeads((old) => old.map((item) => item.id === lead.id ? data.lead : item))
      } catch (error) {
        window.alert(`图片保存失败：${errorMessage(error)}`)
        break
      }
    }
  }

  const removeNoteImage = async (lead: AILead, image: string) => {
    if (!window.confirm('删除这张备注图片吗？')) return
    try {
      const { data } = await aiApi.deleteNoteImage(lead.id, image)
      setLeads((old) => old.map((item) => item.id === lead.id ? data.lead : item))
      setNoteImage(undefined)
    } catch (error) {
      window.alert(`图片删除失败：${errorMessage(error)}`)
    }
  }

  const exportCsv = async (kind: 'leads' | 'intelligence') => {
    try {
      const { data } = await (kind === 'leads' ? aiApi.exportLeads() : aiApi.exportIntelligence())
      const url = URL.createObjectURL(data)
      const link = document.createElement('a')
      link.href = url
      link.download = `${kind === 'leads' ? '聚泰企业线索' : '行业情报'}_${new Date().toISOString().slice(0, 10)}.csv`
      link.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      window.alert(`导出失败：${errorMessage(error)}`)
    }
  }

  const ready = status?.api_configured && status?.access_configured
  const leadQuery = leadSearch.trim().toLocaleLowerCase()
  const matchingLeads = leadQuery ? leads.filter((lead) => [
    lead.company_name, lead.aliases, lead.company_info, lead.country, lead.website, lead.email,
    lead.phone, lead.address, lead.contact_person, lead.patents, lead.patent_titles,
    lead.keywords, lead.evidence, lead.next_action, lead.manual_notes, lead.seed_company,
    lead.seed_region, lead.discovery_basis, lead.company_role, lead.relationship_type, lead.evidence_level,
    lead.industry_tags, lead.product_tags, lead.part_tags, lead.condition_tags,
  ].some((value) => String(value || '').toLocaleLowerCase().includes(leadQuery))) : leads
  const pathLeads = matchingLeads.filter((lead) => TAG_FIELDS.every(([field]) => !pathFilters[field] || tags(lead[field]).includes(pathFilters[field]!)))
  const tagOptions = (field: TagField) => {
    const position = TAG_FIELDS.findIndex(([key]) => key === field)
    const scoped = leads.filter((lead) => TAG_FIELDS.slice(0, position).every(([key]) => !pathFilters[key] || tags(lead[key]).includes(pathFilters[key]!)))
    return [...scoped.reduce((all, lead) => {
      tags(lead[field]).forEach((tag) => all.set(tag, (all.get(tag) || 0) + 1))
      return all
    }, new Map<string, number>()).entries()].sort((a, b) => b[1] - a[1])
  }
  const selectPathTag = (field: TagField, tag: string) => {
    const index = TAG_FIELDS.findIndex(([key]) => key === field)
    setPathFilters((previous) => {
      const next: Partial<Record<TagField, string>> = {}
      TAG_FIELDS.slice(0, index).forEach(([key]) => { if (previous[key]) next[key] = previous[key] })
      next[field] = tag
      return next
    })
  }
  const leadStats = {
    followed: leads.filter((lead) => lead.followed_up).length,
    lowRelevance: leads.filter((lead) => lead.low_relevance).length,
    pending: leads.filter((lead) => !lead.followed_up && !lead.low_relevance).length,
  }
  const visibleLeads = [...pathLeads].sort((a, b) => {
    const relevance = Number(Boolean(a.low_relevance)) - Number(Boolean(b.low_relevance))
    if (relevance) return relevance
    if (leadSort === 'potential') return (b.potential_score || 0) - (a.potential_score || 0)
    if (leadSort === 'created') return (Date.parse(b.created_at || '') || 0) - (Date.parse(a.created_at || '') || 0)
    return 0
  })

  return (
    <div id="ai-workspace" className="h-full min-h-0 scroll-mt-4">
      <Dialog open={Boolean(emailLead)} onOpenChange={(open) => { if (!open) setEmailLead(undefined) }}>
        <DialogContent className="max-h-[calc(100vh-2rem)] max-w-5xl overflow-y-auto">
          <DialogTitle>推荐邮件 · {emailLead?.company_name}</DialogTitle>
          <DialogDescription>邮件与译文会保存在线索中；编辑原邮件后请保存，重新生成会覆盖原邮件并清空旧译文。</DialogDescription>
          {emailError && <p className="text-sm text-cyber-neon-pink">操作失败：{emailError}</p>}
          <div className="grid gap-2 rounded-lg border border-white/60 bg-white/25 p-3 text-xs md:grid-cols-[1fr_auto]">
            <label>收件人
              <input type="email" value={emailRecipient} onChange={(event) => setEmailRecipient(event.target.value)} placeholder="输入收件人邮箱"
                className="mt-1 h-8 w-full rounded border border-white/70 bg-white/55 px-2 text-sm outline-none focus:border-cyber-neon-cyan/60" />
            </label>
            <Button variant="outline" className="self-end" onClick={() => setEmailRecipient(firstEmail(emailLead?.email || ''))} disabled={!emailLead?.email}>带入联系方式</Button>
            <label className="md:col-span-2">加拿大当地定时发送
              <span className="mt-1 flex gap-2"><input type="datetime-local" value={emailScheduleAt} onChange={(event) => setEmailScheduleAt(event.target.value)} className="h-8 flex-1 rounded border border-white/70 bg-white/55 px-2 text-sm outline-none" /><select value={emailScheduleTimezone} onChange={(event) => setEmailScheduleTimezone(event.target.value)} className="h-8 rounded border border-white/70 bg-white/55 px-2 text-xs outline-none"><option value="America/Toronto">东部·多伦多</option><option value="America/Winnipeg">中部·温尼伯</option><option value="America/Edmonton">山地·埃德蒙顿</option><option value="America/Vancouver">太平洋·温哥华</option><option value="America/St_Johns">纽芬兰·圣约翰斯</option></select></span>
            </label>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <p className="text-sm font-semibold">原邮件</p>
              <label className="block text-xs">中文主题<input value={emailSubject} onChange={(event) => setEmailSubject(event.target.value)} className="mt-1 h-8 w-full rounded border border-white/70 bg-white/55 px-2 text-sm outline-none focus:border-cyber-neon-cyan/60" /></label>
              {emailGenerating ? <p className="min-h-64 text-sm text-cyber-text-muted animate-pulse">正在生成推荐邮件…</p> : <textarea value={emailDraft} onChange={(event) => setEmailDraft(event.target.value)} aria-label="推荐邮件内容"
                className="min-h-64 w-full resize-y rounded-lg border border-white/70 bg-white/45 p-3 text-sm leading-6 text-cyber-text-primary outline-none" />}
              <div className="flex flex-wrap justify-start gap-2">
                <Button variant="outline" disabled={emailGenerating || emailSaving || !emailLead} onClick={saveRecommendedEmail}>保存修改</Button>
                <Button variant="outline" disabled={emailGenerating || !emailLead} onClick={() => emailLead && generateRecommendedEmail(emailLead)}><RefreshCw className="h-4 w-4" /> 重新生成</Button>
                <Button disabled={!emailDraft} onClick={() => copyRecommendedEmail()}><Copy className="h-4 w-4" /> 复制</Button>
                <Button disabled={emailSending || !emailRecipient.trim() || !emailSubject.trim() || !emailDraft.trim()} onClick={() => sendRecommendedEmail(emailSubject, emailDraft)}><Send className="h-4 w-4" /> {emailSending ? '发送中…' : '发送中文邮件'}</Button>
                <Button variant="outline" disabled={emailScheduling || !emailScheduleAt || !emailRecipient.trim() || !emailDraft.trim()} onClick={() => scheduleRecommendedEmail(emailSubject, emailDraft)}>{emailScheduling ? '安排中…' : '定时发送'}</Button>
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2"><p className="text-sm font-semibold">翻译</p><select value={emailLanguage} onChange={(event) => { const language = event.target.value; setEmailLanguage(language); setEmailTranslation(emailTranslations[language] || ''); setEmailTranslationSubject(emailLead?.recommended_email_translation_subjects?.[language] || '') }} className="h-8 rounded-lg border border-white/70 bg-white/45 px-2 text-xs outline-none">
                {['英语', '韩语', '日语', '德语', '法语', '西班牙语'].map((language) => <option key={language}>{language}</option>)}
              </select></div>
              <label className="block text-xs">{emailLanguage}主题<input readOnly value={emailTranslationSubject} className="mt-1 h-8 w-full rounded border border-white/70 bg-white/35 px-2 text-sm outline-none" /></label>
              {emailTranslating ? <p className="min-h-64 text-sm text-cyber-text-muted animate-pulse">正在翻译…</p> : <textarea readOnly value={emailTranslation} aria-label="邮件译文" placeholder="选择语言后点击翻译"
                className="min-h-64 w-full resize-y rounded-lg border border-white/70 bg-white/35 p-3 text-sm leading-6 text-cyber-text-primary outline-none" />}
              <div className="flex flex-wrap justify-start gap-2">
                <Button variant="outline" disabled={emailTranslating || !emailDraft.trim()} onClick={translateRecommendedEmail}>翻译为{emailLanguage}</Button>
                <Button disabled={!emailTranslation} onClick={() => copyRecommendedEmail(emailTranslation, '译文')}><Copy className="h-4 w-4" /> 复制译文</Button>
                <Button disabled={emailSending || !emailRecipient.trim() || !emailTranslationSubject.trim() || !emailTranslation.trim()} onClick={() => sendRecommendedEmail(emailTranslationSubject, emailTranslation)}><Send className="h-4 w-4" /> {emailSending ? '发送中…' : `发送${emailLanguage}邮件`}</Button>
                <Button variant="outline" disabled={emailScheduling || !emailScheduleAt || !emailRecipient.trim() || !emailTranslation.trim()} onClick={() => scheduleRecommendedEmail(emailTranslationSubject, emailTranslation)}>{emailScheduling ? '安排中…' : '定时发送'}</Button>
              </div>
            </div>
          </div>
          {emailLead?.scheduled_email?.status === 'scheduled' && <p className="text-right text-xs text-cyber-text-muted">已定时：{emailLead.scheduled_email.local_time}（加拿大当地时间）</p>}
          {emailLead?.recommended_email_sent_at && <p className="text-right text-xs text-cyber-text-muted">最近发送时间：{leadDate(emailLead.recommended_email_sent_at)}</p>}
        </DialogContent>
      </Dialog>
      <Dialog open={Boolean(linkedinLead)} onOpenChange={(open) => { if (!open) setLinkedinLead(undefined) }}>
        <DialogContent>
          <DialogTitle>领英搜索 · {linkedinLead?.company_name}</DialogTitle>
          <DialogDescription>
            先搜索并核对公司身份，再粘贴公司页面链接。只读取这一家的公开公司资料，不采集员工、不消耗 AI Token；原资料不会删除。
          </DialogDescription>
          <a className="text-sm text-cyber-neon-cyan underline" target="_blank" rel="noopener noreferrer"
            href={`https://www.linkedin.com/search/results/companies/?keywords=${encodeURIComponent(linkedinLead?.company_name || '')}`}>
            在领英搜索这家企业 ↗
          </a>
          <label className="space-y-2 text-sm">已核对的公司页面链接
            <input type="url" value={linkedinUrl} onChange={(event) => setLinkedinUrl(event.target.value)}
              placeholder="https://www.linkedin.com/company/…/"
              className="mt-2 w-full rounded border bg-white/70 p-2 text-cyber-text-primary" />
          </label>
          <Button onClick={collectLinkedin} disabled={linkedinBusy || !linkedinUrl.trim()}>确认同一企业，抓取并合并</Button>
        </DialogContent>
      </Dialog>
      <Dialog open={seedDialogOpen} onOpenChange={setSeedDialogOpen}>
        <DialogContent>
          <DialogTitle>种子企业搜索</DialogTitle>
          <DialogDescription>先判断这家企业的角色、产品和应用，再联网从官网、专利、展会及公开社交资料寻找有证据的同类企业。使用当前选择的联网模型。</DialogDescription>
          <label className="space-y-1 text-sm">种子企业名称
            <input value={seedCompany} onChange={(event) => setSeedCompany(event.target.value)} placeholder="例如：GEHR Kunststoffwerk GmbH & Co. KG"
              className="mt-1 w-full rounded border bg-white/70 p-2 text-cyber-text-primary" />
          </label>
          <label className="space-y-1 text-sm">目标区域（可留空）
            <input value={seedRegion} onChange={(event) => setSeedRegion(event.target.value)} placeholder="例如：德国、欧洲、泰国、北美"
              className="mt-1 w-full rounded border bg-white/70 p-2 text-cyber-text-primary" />
          </label>
          <Button onClick={searchFromSeed} disabled={seedBusy || !seedCompany.trim()}>{seedBusy ? '搜索中…' : '联网搜索企业'}</Button>
        </DialogContent>
      </Dialog>
      <Dialog open={Boolean(noteImage)} onOpenChange={(open) => { if (!open) setNoteImage(undefined) }}>
        <DialogContent className="max-w-5xl">
          <DialogTitle>{noteImage?.lead.company_name} · 备注图片</DialogTitle>
          {noteImage && <img src={aiApi.noteImageUrl(noteImage.lead.id, noteImage.image)} alt="企业线索备注" className="max-h-[75vh] w-full object-contain" />}
          {noteImage && <Button variant="outline" onClick={() => removeNoteImage(noteImage.lead, noteImage.image)}>删除图片</Button>}
        </DialogContent>
      </Dialog>
      <section className={`glass-panel float-panel h-full min-h-0 overflow-auto rounded-[28px] ${view !== 'analysis' ? 'hidden' : ''}`}>
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-white/60 bg-white/30 px-4 py-2">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-full border border-white/80 bg-white/55">
              <Bot className="h-4 w-4 text-cyber-neon-cyan" />
            </span>
            <div>
              <h2 className="font-mono text-xs font-semibold text-cyber-text-primary">AI 零件客户分析 · {status?.model || '千问 Flash'}</h2>
              <p className="text-[10px] text-cyber-text-muted">目标：高性能工程塑料零件用户 · 识别企业角色、材料牌号、零件用途与采购证据</p>
              <p className="max-w-3xl text-[10px] text-cyber-text-muted">关注：{status?.material_scope || '工程塑料及其改性材料'}</p>
              <p className="mt-1 text-[10px] text-cyber-text-muted">
                本系统累计 {(status?.usage.total_tokens || 0).toLocaleString()} Token
                （输入 {(status?.usage.input_tokens || 0).toLocaleString()} / 输出 {(status?.usage.output_tokens || 0).toLocaleString()}）
                {' · '}
                <a href="https://bailian.console.aliyun.com/?tab=costing-balance" target="_blank" rel="noreferrer" className="font-semibold text-cyber-neon-cyan hover:underline">查看官方剩余额度 ↗</a>
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex rounded-md border border-white/60 p-0.5 text-[10px]">
              <button type="button" onClick={() => changeProvider('qwen')} disabled={busy || !status?.providers?.qwen} className={`rounded px-2 py-1 ${status?.provider === 'qwen' ? 'bg-cyber-neon-cyan text-cyber-bg-primary' : 'text-cyber-text-muted'}`}>千问 Flash</button>
              <button type="button" onClick={() => changeProvider('gemini')} disabled={busy || !status?.providers?.gemini} title={status?.providers?.gemini ? '切换至 Gemini 3.6 Flash（含 Google 搜索）' : '服务器尚未配置 Gemini API Key'} className={`rounded px-2 py-1 ${status?.provider === 'gemini' ? 'bg-cyber-neon-cyan text-cyber-bg-primary' : 'text-cyber-text-muted disabled:opacity-40'}`}>Gemini 3.6 Flash</button>
            </div>
            <span className={`font-mono text-[10px] ${ready ? 'text-cyber-neon-green' : 'text-cyber-neon-orange'}`}>
              {ready ? `${status?.model} 已配置` : '等待服务器配置'}
            </span>
            <Button variant="ghost" size="sm" onClick={clearHistory} disabled={busy} className="text-cyber-text-muted hover:text-cyber-neon-pink">
              <Trash2 className="h-4 w-4" /> 清除聊天
            </Button>
          </div>
        </header>

        <div className="space-y-3 p-4">
          {batch?.id && (
            <div className="rounded-xl border border-white/60 bg-white/50 p-3 text-xs" role="status" aria-live="polite">
              <div className="flex items-center justify-between gap-3">
                <span>{batch.message}</span>
                {batchBusy && <Button variant="outline" size="sm" disabled={batch.status === 'stopping'} onClick={async () => {
                  try { await aiApi.stopBatch(); await refetchBatch() }
                  catch (error) { window.alert(`停止失败：${errorMessage(error)}`) }
                }}>{batch.status === 'stopping' ? '等待本批保存…' : '停止分批分析'}</Button>}
              </div>
              <p className="mt-2">已分析 {batch.analyzed || 0} / {batch.total || 0} · 审核跳过 {batch.skipped || 0} · 剩余 {batch.remaining || 0} · 本次完成 {batch.batches || 0} 批</p>
              <p className="mt-1 text-cyber-text-muted">后台执行，刷新页面不中断；停止会等待当前批次保存。下次重新勾选文件即可继续。</p>
            </div>
          )}
          {!status?.api_configured && <p className="text-[10px] text-cyber-neon-orange">服务器尚未配置当前模型的 API Key</p>}

          <div ref={chatRef} className="h-72 space-y-3 overflow-y-auto rounded-2xl border border-white/60 bg-white/25 p-4 terminal-scroll">
            {messages.map((message, index) => (
              <div key={index} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-xs leading-relaxed ${
                  message.role === 'user'
                    ? 'bg-cyber-neon-cyan text-cyber-bg-primary'
                    : 'apple-subpanel text-cyber-text-primary'
                }`}>
                  {message.content}
                </div>
              </div>
            ))}
            {busy && <div className="text-xs text-cyber-text-muted animate-pulse">{status?.model || 'AI'} 正在分析搜索数据…</div>}
          </div>

          <div className="flex flex-col gap-2 sm:flex-row">
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  ask(input)
                }
              }}
              disabled={busy}
              placeholder="询问企业、专利、材料应用、市场动态或下一步建议…"
              className="min-h-[72px] flex-1 resize-none rounded-xl border border-white/70 bg-white/40 px-3 py-2 text-xs text-cyber-text-primary outline-none focus:border-cyber-neon-cyan/60"
            />
            <div className="flex gap-2 sm:flex-col">
              <Button
                variant="outline"
                disabled={busy}
                onClick={analyzeLatest}
                className="flex-1"
              >
                <Sparkles className="h-4 w-4" /> 分析最新结果
              </Button>
              <Button disabled={busy || !input.trim()} onClick={() => ask(input)} className="flex-1">
                <Send className="h-4 w-4" /> 发送
              </Button>
            </div>
          </div>
        </div>
      </section>

      <section className={`glass-panel float-panel h-full min-h-0 flex-col overflow-hidden rounded-[28px] ${view !== 'leads' ? 'hidden' : 'flex'}`}>
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-white/60 bg-white/30 px-4 py-2">
          <div className="flex items-center gap-3">
            <Building2 className="h-4 w-4 text-cyber-neon-cyan" />
            <div>
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                <h2 className="font-mono text-xs font-semibold text-cyber-text-primary">企业线索库</h2>
                {seedJob?.message && <span role="status" aria-live="polite" className={`text-[10px] ${seedJob.status === 'error' ? 'text-red-600' : 'text-cyber-text-secondary'}`}>种子企业搜索：{seedJob.message}</span>}
              </div>
              <p className="text-[10px] text-cyber-text-muted">
                {leads.length} 家企业 · 已跟进 {leadStats.followed} · 未跟进 {leadStats.pending} · 关联不足 {leadStats.lowRelevance} · 显示 {visibleLeads.length} 家
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" className="h-7 px-2 text-[10px]" onClick={() => setSeedDialogOpen(true)} disabled={busy}>
              <Users className="h-4 w-4" /> 种子企业搜索
            </Button>
            <Button variant={leadSort === 'default' ? 'default' : 'outline'} size="sm"
              className="h-7 px-2 text-[10px]" aria-pressed={leadSort === 'default'} onClick={() => setLeadSort('default')}>默认排序</Button>
            <Button variant={leadSort === 'potential' ? 'default' : 'outline'} size="sm"
              className="h-7 px-2 text-[10px]" aria-pressed={leadSort === 'potential'} onClick={() => setLeadSort('potential')}>潜力排序</Button>
            <Button variant={leadSort === 'created' ? 'default' : 'outline'} size="sm"
              className="h-7 px-2 text-[10px]" aria-pressed={leadSort === 'created'} onClick={() => setLeadSort('created')}>添加日期排序</Button>
            <Button variant="outline" size="sm" className="h-7 px-2 text-[10px]" onClick={() => setPathFilters({})} disabled={!Object.keys(pathFilters).length}>清除路径</Button>
            <label className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-cyber-text-muted" />
              <input type="search" value={leadSearch} onChange={(event) => setLeadSearch(event.target.value)}
                aria-label="搜索企业线索" placeholder="搜索企业、材料或备注…"
                className="h-7 w-56 rounded-lg border border-white/70 bg-white/45 pl-8 pr-3 text-xs outline-none focus:border-cyber-neon-cyan/60" />
            </label>
            <Button variant="outline" size="sm" className="h-7 px-2 text-[10px]" onClick={() => exportCsv('leads')} disabled={leads.length === 0}>
              <Download className="h-4 w-4" /> 导出 CSV
            </Button>
          </div>
        </header>
        {linkedinJob?.message && <p role="status" aria-live="polite" className={`px-5 py-2 text-xs ${linkedinJob.status === 'error' ? 'text-red-600' : 'text-cyber-text-secondary'}`}>
          领英：{linkedinJob.message}（详细流程见系统控制台）
        </p>}
        {similarJob?.message && <p role="status" aria-live="polite" className={`px-5 py-2 text-xs ${similarJob.status === 'error' ? 'text-red-600' : 'text-cyber-text-secondary'}`}>
          同类企业：{similarJob.message}
        </p>}
        <section className="border-b border-white/60 bg-white/20 px-4 py-2">
          <div className="grid gap-2 md:grid-cols-4">
            {TAG_FIELDS.map(([field, label]) => (
              <div key={field} className="rounded-lg border border-white/60 bg-white/35 p-2">
                <p className="mb-1 text-[10px] font-semibold text-cyber-text-muted">{label}{pathFilters[field] ? ` · ${pathFilters[field]}` : ''}</p>
                <div className="flex max-h-20 flex-wrap gap-1 overflow-y-auto pr-1">
                  {tagOptions(field).map(([tag, count]) => <button type="button" key={tag} onClick={() => selectPathTag(field, tag)} className={`rounded-full border px-1.5 py-0.5 text-[10px] ${pathFilters[field] === tag ? 'border-cyber-neon-cyan bg-cyber-neon-cyan/20' : 'border-cyber-neon-cyan/20 hover:border-cyber-neon-cyan/60'}`}>{tag} <span className="text-cyber-text-muted">{count}</span></button>)}
                  {!tagOptions(field).length && <span className="text-[10px] text-cyber-text-muted">暂无已分类企业</span>}
                </div>
              </div>
            ))}
          </div>
        </section>
        <div className="min-h-0 flex-1 overflow-auto terminal-scroll">
          <table className="w-full min-w-[960px] table-fixed text-left text-[10px] leading-4">
            <colgroup>
              {[4, 6, 10, 12, 10, 9, 10, 13, 10, 10, 6].map((width, index) => <col key={index} style={{ width: `${width}%` }} />)}
            </colgroup>
            <thead className="sticky top-0 z-10 bg-white/80 text-cyber-text-secondary backdrop-blur-xl">
              <tr>
                {['跟进', '更新', '企业 / 潜力', '企业信息', '联系方式', '专利', '行业 / 产品 / 零件 / 工况标签', '证据与建议', '来源', '备注', ''].map((title) => (
                  <th key={title} className="border-b border-white/70 px-2 py-2 font-semibold">{title}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visibleLeads.map((lead) => (
                <tr key={lead.id} className="lead-row border-b border-white/45 align-top">
                  <td className="px-2 py-2 text-center">
                    <input
                      type="checkbox"
                      checked={Boolean(lead.followed_up)}
                      onChange={(event) => setFollowedUp(lead, event.target.checked)}
                      aria-label={`${lead.company_name} 已跟进`}
                      className="h-4 w-4 accent-[rgb(var(--cyber-neon-cyan))]"
                    />
                  </td>
                  <td className="px-1 py-2 text-center">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy}
                      onClick={() => updateLeadFromWeb(lead)}
                      className="h-7 px-2 text-[9px]"
                      title={`联网更新 ${lead.company_name}`}
                    >
                      <RefreshCw className={`h-3 w-3 ${updatingLeadId === lead.id ? 'animate-spin' : ''}`} />
                      {updatingLeadId === lead.id ? '更新中' : '更新线索'}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy}
                      onClick={() => findSimilarLeads(lead)}
                      className="mt-1 h-7 px-2 text-[9px]"
                      title={`联网查找与 ${lead.company_name} 同类型的企业`}
                    >
                      {similarLeadId === lead.id
                        ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Users className="h-3 w-3" />}
                      {similarLeadId === lead.id ? '搜索中' : '同类企业'}
                    </Button>
                    <Button variant="outline" size="sm" disabled={linkedinBusy}
                      className="mt-1 h-7 px-2 text-[9px]" title={`搜索并补充 ${lead.company_name} 的领英资料`}
                      onClick={() => {
                        setLinkedinLead(lead)
                        setLinkedinUrl(links(lead.source_urls).find((url) => /^https:\/\/(www\.)?linkedin\.com\/company\//.test(url)) || '')
                      }}>
                      {linkedinJob?.status === 'running' && linkedinJob.lead_id === lead.id
                        ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Linkedin className="h-3 w-3" />}
                      {linkedinJob?.status === 'running' && linkedinJob.lead_id === lead.id ? '读取中' : '领英搜索'}
                    </Button>
                  </td>
                  <td className="break-words px-2 py-2 font-semibold text-cyber-text-primary">
                    <a href={`https://www.qcc.com/web/search?key=${encodeURIComponent(lead.company_name)}`} target="_blank" rel="noreferrer" title={`在企查查搜索 ${lead.company_name}`} className="hover:text-cyber-neon-cyan hover:underline">
                      {lead.company_name}
                    </a>
                    {lead.aliases && <div className="font-normal text-cyber-text-muted">简称：{lead.aliases}</div>}
                    <span className="font-mono text-cyber-neon-cyan">{lead.potential_score}</span>{lead.country ? ` · ${lead.country}` : ''}
                    {(lead.company_role || lead.relationship_type || lead.evidence_level) && <div className="mt-1 font-normal text-cyber-text-muted">{[lead.company_role, lead.relationship_type, lead.evidence_level].filter(Boolean).join(' · ')}</div>}
                    {lead.seed_company && <div className="mt-1 font-normal text-cyber-text-muted">种子：{lead.seed_company}{lead.seed_region ? `（${lead.seed_region}）` : ''}</div>}
                    {lead.discovery_basis && <div className="font-normal text-cyber-text-muted">路径：{lead.discovery_basis}</div>}
                    <div className="mt-1 font-normal text-cyber-text-muted">添加时间：{leadDate(lead.created_at)}</div>
                    <div className="font-normal text-cyber-text-muted">更新时间：{leadDate(lead.updated_at)}</div>
                  </td>
                  <td className="break-words whitespace-pre-wrap px-2 py-2">{lead.company_info || '-'}</td>
                  <td className="break-words px-2 py-2">
                    {lead.contact_person && <div>{lead.contact_person}</div>}
                    {lead.website && lead.website.split(/;\s*/).filter(Boolean).map((website, index) => <div key={website}><a href={webUrl(website)} target="_blank" rel="noreferrer" className="text-cyber-neon-cyan hover:underline">官网{index ? ` ${index + 1}` : ''} ↗</a></div>)}
                    {lead.email && <div><a href={`mailto:${lead.email}`} className="text-cyber-neon-cyan hover:underline">{lead.email}</a></div>}
                    {lead.phone && <div><a href={`tel:${lead.phone}`} className="hover:underline">{lead.phone}</a></div>}
                    {lead.address && <div>{lead.address}</div>}
                    <Button variant="outline" size="sm" disabled={emailGenerating} onClick={() => openRecommendedEmail(lead)}
                      className="mt-1 h-7 px-2 text-[9px]" title={`为 ${lead.company_name} 生成推荐邮件`}>
                      <Mail className="h-3 w-3" /> 推荐邮件
                    </Button>
                  </td>
                  <td className="break-words whitespace-pre-wrap px-2 py-2">{[lead.patents, lead.patent_titles].filter(Boolean).join('\n') || '-'}</td>
                  <td className="px-2 py-2">
                    <div className="flex flex-wrap gap-1">
                      {TAG_FIELDS.flatMap(([field, label]) => tags(lead[field]).map((tag) => (
                        <button type="button" key={`${field}-${tag}`} title={`按${label}筛选：${tag}`} onClick={() => selectPathTag(field, tag)} className={`rounded-full border px-1.5 py-0.5 text-[9px] ${pathFilters[field] === tag ? 'border-cyber-neon-cyan bg-cyber-neon-cyan/20' : 'border-cyber-neon-cyan/20 bg-white/35 text-cyber-text-secondary hover:border-cyber-neon-cyan/60'}`}>{label}·{tag}</button>
                      )))}
                      {!TAG_FIELDS.some(([field]) => Boolean(lead[field])) && keywords(lead.keywords).map((tag) => <span key={tag} className="rounded-full border border-cyber-neon-cyan/20 bg-white/35 px-1.5 py-0.5 text-[9px] text-cyber-text-secondary">{tag}</span>)}
                      {!TAG_FIELDS.some(([field]) => Boolean(lead[field])) && !lead.keywords && '-'}
                    </div>
                  </td>
                  <td className="break-words whitespace-pre-wrap px-2 py-2">{[lead.evidence, lead.next_action].filter(Boolean).join('\n') || '-'}</td>
                  <td className="break-words px-2 py-2">
                    <div>{lead.source_platform || '-'}</div>
                    {links(lead.source_urls).map((url, index) => (
                      <div key={url}><a href={url} target="_blank" rel="noreferrer" className="text-cyber-neon-cyan hover:underline">来源 {index + 1} ↗</a></div>
                    ))}
                  </td>
                  <td className="relative p-0">
                    <textarea value={lead.manual_notes || ''} maxLength={2000}
                      onChange={(event) => setLeads((old) => old.map((item) => item.id === lead.id ? { ...item, manual_notes: event.target.value } : item))}
                      onBlur={() => saveLeadNotes(lead)} aria-label={`${lead.company_name} 备注`}
                      onPaste={(event) => {
                        const files = Array.from(event.clipboardData.files).filter((file) => file.type.startsWith('image/'))
                        if (files.length) { event.preventDefault(); void uploadNoteImages(lead, files) }
                      }}
                      placeholder="输入备注，离开后自动保存"
                      className="absolute inset-2 h-[calc(100%-1rem)] w-[calc(100%-1rem)] resize-none rounded-lg border border-white/70 bg-white/45 p-2 pb-10 text-[10px] leading-4 outline-none focus:border-cyber-neon-cyan/60" />
                    <div className="absolute bottom-3 left-3 right-3 flex flex-wrap gap-1">
                      {lead.manual_note_images?.map((image) => <button key={image} type="button" title="点击放大" onClick={() => setNoteImage({ lead, image })} className="h-7 w-7 overflow-hidden rounded border border-white/80 bg-white">
                        <img src={aiApi.noteImageUrl(lead.id, image)} alt="备注缩略图" className="h-full w-full object-cover" />
                      </button>)}
                      <label title="可直接在备注框粘贴截图" className="flex h-7 w-7 cursor-pointer items-center justify-center rounded border border-dashed border-white/80 bg-white/45 text-cyber-text-muted">
                        <ImagePlus className="h-3.5 w-3.5" />
                        <input type="file" accept="image/jpeg,image/png,image/webp,image/gif" className="hidden" onChange={(event) => {
                          const files = Array.from(event.target.files || [])
                          if (files.length) void uploadNoteImages(lead, files)
                          event.target.value = ''
                        }} />
                      </label>
                    </div>
                  </td>
                  <td className="px-1 py-2 text-center">
                    <Button variant="ghost" size="sm" onClick={() => removeLead(lead.id)} className="text-cyber-neon-pink">
                      <Trash2 className="h-4 w-4" />
                    </Button>
                    <Button variant={lead.low_relevance ? 'default' : 'outline'} size="sm"
                      className="mt-1 h-7 px-1.5 text-[9px]" aria-pressed={Boolean(lead.low_relevance)}
                      onClick={() => setLowRelevance(lead, !lead.low_relevance)}>关联不足</Button>
                  </td>
                </tr>
              ))}
              {visibleLeads.length === 0 && (
                <tr><td colSpan={11} className="px-4 py-12 text-center text-cyber-text-muted">
                  {leads.length ? '没有找到匹配的企业线索。' : '分析搜索结果后，企业线索会保存在这里。'}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className={`glass-panel float-panel h-full min-h-0 flex-col overflow-hidden rounded-[28px] ${view !== 'intelligence' ? 'hidden' : 'flex'}`}>
        <header className="flex items-center gap-3 border-b border-white/60 bg-white/30 px-5 py-4">
          <Newspaper className="h-4 w-4 text-cyber-neon-cyan" />
          <div className="flex-1">
            <h2 className="font-mono text-xs font-semibold text-cyber-text-primary">行业情报库</h2>
            <p className="text-[10px] text-cyber-text-muted">{intelligence.length} 条 · 工程塑料、改性牌号及零件应用动态与市场传闻</p>
          </div>
          <Button variant="outline" size="sm" onClick={() => exportCsv('intelligence')} disabled={intelligence.length === 0}>
            <Download className="h-4 w-4" /> 导出 CSV
          </Button>
        </header>
        <div className="min-h-0 flex-1 overflow-auto terminal-scroll">
          <table className="w-full min-w-[960px] table-fixed text-left text-[10px] leading-4">
            <colgroup>
              {[8, 10, 20, 22, 12, 17, 8, 3].map((width, index) => <col key={index} style={{ width: `${width}%` }} />)}
            </colgroup>
            <thead className="sticky top-0 z-10 bg-white/80 text-cyber-text-secondary backdrop-blur-xl">
              <tr>
                {['日期', '材料', '情报', 'AI 分析', '可靠度', '影响与建议', '来源', ''].map((title) => (
                  <th key={title} className="border-b border-white/70 px-2 py-2 font-semibold">{title}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {intelligence.map((item) => (
                <tr key={item.id} className="border-b border-white/45 align-top hover:bg-white/20">
                  <td className="px-2 py-2 font-mono">{item.event_date || '日期未知'}</td>
                  <td className="px-2 py-2">
                    <div className="flex flex-wrap gap-1">
                      {keywords(item.materials).map((material) => <span key={material} className="rounded-full border border-cyber-neon-cyan/20 bg-white/35 px-1.5 py-0.5 text-[9px]">{material}</span>)}
                      {!item.materials && '-'}
                    </div>
                  </td>
                  <td className="break-words whitespace-pre-wrap px-2 py-2"><strong>{item.title}</strong>{item.summary && `\n${item.summary}`}</td>
                  <td className="break-words whitespace-pre-wrap px-2 py-2">{[item.analysis, item.evidence].filter(Boolean).join('\n') || '-'}</td>
                  <td className="break-words whitespace-pre-wrap px-2 py-2"><span className="font-mono font-semibold text-cyber-neon-cyan">{item.reliability_score}%</span>{item.reliability_reason && `\n${item.reliability_reason}`}</td>
                  <td className="break-words whitespace-pre-wrap px-2 py-2">{[item.impact, item.next_action].filter(Boolean).join('\n') || '-'}</td>
                  <td className="break-words px-2 py-2">
                    <div>{item.source_platform || '-'}</div>
                    {item.source_url && <a href={webUrl(item.source_url)} target="_blank" rel="noreferrer" className="text-cyber-neon-cyan hover:underline">查看来源 ↗</a>}
                  </td>
                  <td className="px-1 py-2">
                    <Button variant="ghost" size="sm" onClick={() => removeIntelligence(item.id)} className="text-cyber-neon-pink"><Trash2 className="h-4 w-4" /></Button>
                  </td>
                </tr>
              ))}
              {intelligence.length === 0 && <tr><td colSpan={8} className="px-4 py-12 text-center text-cyber-text-muted">分析搜索结果后，非企业类行业消息会保存在这里。</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
