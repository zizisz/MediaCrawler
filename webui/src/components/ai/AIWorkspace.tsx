import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Bot, Building2, Download, Linkedin, Newspaper, RefreshCw, Search, Send, Sparkles, Trash2, Users } from 'lucide-react'
import { aiApi, type AIIntelligence, type AILead } from '@/lib/api'
import { useCrawlerStore } from '@/store/crawlerStore'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog'

type Message = { role: 'user' | 'assistant'; content: string }
type AIStatus = {
  model: string
  material_scope?: string
  api_configured: boolean
  access_configured: boolean
  usage: { calls?: number; input_tokens?: number; output_tokens?: number; total_tokens?: number; tracking_since?: string }
}
const GREETING: Message = { role: 'assistant', content: '我是工程塑料零件客户分析助手。可分批分析搜索结果，识别企业角色、材料牌号、零件用途及采购线索，也可以询问企业和行业动态。' }
const links = (value = '') => [...new Set(value.match(/https?:\/\/[^\s'"\],;]+/g) || [])]
const webUrl = (value: string) => /^https?:\/\//i.test(value) ? value : `https://${value}`
const keywords = (value = '') => [...new Set(value.replace(/[\[\]'"\u201c\u201d]/g, '').split(/[,;；\n]/).map((item) => item.trim()).filter(Boolean))]
const leadDate = (value = '') => value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '未知'

function errorMessage(error: unknown) {
  if (axios.isAxiosError(error)) return error.response?.data?.detail || error.message
  return error instanceof Error ? error.message : '请求失败'
}

export function AIWorkspace() {
  const config = useCrawlerStore((state) => state.config)
  const [status, setStatus] = useState<AIStatus>()
  const [input, setInput] = useState('')
  const [leadSearch, setLeadSearch] = useState('')
  const [leadSort, setLeadSort] = useState<'default' | 'potential' | 'created'>('default')
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
  const busy = localBusy || batchBusy || similarBusy
  const [linkedinLead, setLinkedinLead] = useState<AILead>()
  const [linkedinUrl, setLinkedinUrl] = useState('')
  const [linkedinSubmitting, setLinkedinSubmitting] = useState(false)
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
    window.addEventListener('ai-analysis-updated', refresh)
    window.addEventListener('ai-manual-analysis-started', started)
    window.addEventListener('ai-manual-analysis-completed', completed)
    window.addEventListener('ai-manual-analysis-failed', failed)
    return () => {
      window.removeEventListener('ai-analysis-updated', refresh)
      window.removeEventListener('ai-manual-analysis-started', started)
      window.removeEventListener('ai-manual-analysis-completed', completed)
      window.removeEventListener('ai-manual-analysis-failed', failed)
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
      await ask(`请联网搜索并更新企业线索库中“${lead.company_name}”的最新公开资料。按系统定义的完整材料范围，核实其是否为工程塑料零件用户、设备制造商、加工商、贸易商或材料供应商；核实具体材料牌号、零件用途、应用行业和采购证据。核实企业全称和简称、官网、地址、联系人、电话、邮箱、主营业务、专利和来源链接；仅保存可验证信息，没有找到的字段保持空白。同时提取相关材料供需、价格、扩产、认证、技术、应用和市场传闻，标明日期、来源及可靠度，并保存到行业情报库。`, false, lead.id)
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
    lead.keywords, lead.evidence, lead.next_action, lead.manual_notes,
  ].some((value) => String(value || '').toLocaleLowerCase().includes(leadQuery))) : leads
  const visibleLeads = [...matchingLeads].sort((a, b) => {
    const relevance = Number(Boolean(a.low_relevance)) - Number(Boolean(b.low_relevance))
    if (relevance) return relevance
    if (leadSort === 'potential') return (b.potential_score || 0) - (a.potential_score || 0)
    if (leadSort === 'created') return (Date.parse(b.created_at || '') || 0) - (Date.parse(a.created_at || '') || 0)
    return 0
  })

  return (
    <div id="ai-workspace" className="space-y-4 scroll-mt-4">
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
              className="mt-2 w-full rounded border bg-white/70 p-2 text-black" />
          </label>
          <Button onClick={collectLinkedin} disabled={linkedinBusy || !linkedinUrl.trim()}>确认同一企业，抓取并合并</Button>
        </DialogContent>
      </Dialog>
      <section className="glass-panel float-panel overflow-hidden rounded-[28px]">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/60 bg-white/30 px-5 py-4">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-full border border-white/80 bg-white/55">
              <Bot className="h-4 w-4 text-cyber-neon-cyan" />
            </span>
            <div>
              <h2 className="font-mono text-xs font-semibold text-cyber-text-primary">AI 零件客户分析 · 千问 Flash</h2>
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
          {!status?.api_configured && <p className="text-[10px] text-cyber-neon-orange">服务器尚未配置百炼 API Key</p>}

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
            {busy && <div className="text-xs text-cyber-text-muted animate-pulse">千问正在分析搜索数据…</div>}
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

      <section className="glass-panel float-panel overflow-hidden rounded-[28px]">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/60 bg-white/30 px-5 py-4">
          <div className="flex items-center gap-3">
            <Building2 className="h-4 w-4 text-cyber-neon-cyan" />
            <div>
              <h2 className="font-mono text-xs font-semibold text-cyber-text-primary">企业线索库</h2>
              <p className="text-[10px] text-cyber-text-muted">
                {leads.length} 家企业 · 已跟进 {leads.filter((lead) => lead.followed_up).length} · 未跟进 {leads.filter((lead) => !lead.followed_up).length}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant={leadSort === 'default' ? 'default' : 'outline'} size="sm"
              aria-pressed={leadSort === 'default'} onClick={() => setLeadSort('default')}>默认排序</Button>
            <Button variant={leadSort === 'potential' ? 'default' : 'outline'} size="sm"
              aria-pressed={leadSort === 'potential'} onClick={() => setLeadSort('potential')}>潜力排序</Button>
            <Button variant={leadSort === 'created' ? 'default' : 'outline'} size="sm"
              aria-pressed={leadSort === 'created'} onClick={() => setLeadSort('created')}>添加日期排序</Button>
            <label className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-cyber-text-muted" />
              <input type="search" value={leadSearch} onChange={(event) => setLeadSearch(event.target.value)}
                aria-label="搜索企业线索" placeholder="搜索企业、材料或备注…"
                className="h-8 w-56 rounded-lg border border-white/70 bg-white/45 pl-8 pr-3 text-xs outline-none focus:border-cyber-neon-cyan/60" />
            </label>
            <Button variant="outline" size="sm" onClick={() => exportCsv('leads')} disabled={leads.length === 0}>
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
        <div className="max-h-[560px] overflow-auto terminal-scroll">
          <table className="w-full min-w-[960px] table-fixed text-left text-[10px] leading-4">
            <colgroup>
              {[4, 6, 10, 12, 10, 9, 10, 13, 10, 10, 6].map((width, index) => <col key={index} style={{ width: `${width}%` }} />)}
            </colgroup>
            <thead className="sticky top-0 z-10 bg-white/80 text-cyber-text-secondary backdrop-blur-xl">
              <tr>
                {['跟进', '更新', '企业 / 潜力', '企业信息', '联系方式', '专利', '关键词', '证据与建议', '来源', '备注', ''].map((title) => (
                  <th key={title} className="border-b border-white/70 px-2 py-2 font-semibold">{title}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visibleLeads.map((lead) => (
                <tr key={lead.id} className={`border-b border-white/45 align-top hover:bg-white/20 ${lead.followed_up ? 'bg-white/30' : ''}`}>
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
                    {lead.company_name}
                    {lead.aliases && <div className="font-normal text-cyber-text-muted">简称：{lead.aliases}</div>}
                    <span className="font-mono text-cyber-neon-cyan">{lead.potential_score}</span>{lead.country ? ` · ${lead.country}` : ''}
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
                  </td>
                  <td className="break-words whitespace-pre-wrap px-2 py-2">{[lead.patents, lead.patent_titles].filter(Boolean).join('\n') || '-'}</td>
                  <td className="px-2 py-2">
                    <div className="flex flex-wrap gap-1">
                      {keywords(lead.keywords).map((keyword) => (
                        <span key={keyword} className="rounded-full border border-cyber-neon-cyan/20 bg-white/35 px-1.5 py-0.5 text-[9px] text-cyber-text-secondary">{keyword}</span>
                      ))}
                      {!lead.keywords && '-'}
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
                      placeholder="输入备注，离开后自动保存"
                      className="absolute inset-2 h-[calc(100%-1rem)] w-[calc(100%-1rem)] resize-none rounded-lg border border-white/70 bg-white/45 p-2 text-[10px] leading-4 outline-none focus:border-cyber-neon-cyan/60" />
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

      <section className="glass-panel float-panel overflow-hidden rounded-[28px]">
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
        <div className="max-h-[560px] overflow-auto terminal-scroll">
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
