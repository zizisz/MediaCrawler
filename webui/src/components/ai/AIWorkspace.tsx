import { useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { Bot, Building2, Download, Newspaper, RefreshCw, Send, Sparkles, Trash2 } from 'lucide-react'
import { aiApi, type AIIntelligence, type AILead } from '@/lib/api'
import { useCrawlerStore } from '@/store/crawlerStore'
import { Button } from '@/components/ui/button'

type Message = { role: 'user' | 'assistant'; content: string }
type AIStatus = {
  model: string
  api_configured: boolean
  access_configured: boolean
  usage: { calls?: number; input_tokens?: number; output_tokens?: number; total_tokens?: number; tracking_since?: string }
}
const GREETING: Message = { role: 'assistant', content: '我是潜客分析助手。连接后可点击“分析最新搜索结果”，也可以继续询问企业、专利和采购线索。' }
const links = (value = '') => [...new Set(value.match(/https?:\/\/[^\s'"\],;]+/g) || [])]
const webUrl = (value: string) => /^https?:\/\//i.test(value) ? value : `https://${value}`
const keywords = (value = '') => [...new Set(value.replace(/[\[\]'"\u201c\u201d]/g, '').split(/[,;；\n]/).map((item) => item.trim()).filter(Boolean))]

function errorMessage(error: unknown) {
  if (axios.isAxiosError(error)) return error.response?.data?.detail || error.message
  return error instanceof Error ? error.message : '请求失败'
}

export function AIWorkspace() {
  const config = useCrawlerStore((state) => state.config)
  const [status, setStatus] = useState<AIStatus>()
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [updatingLeadId, setUpdatingLeadId] = useState<string>()
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
    await aiApi.updateLead(lead.id, followed_up)
    setLeads((old) => old.map((item) => item.id === lead.id ? { ...item, followed_up } : item))
  }

  const updateLeadFromWeb = async (lead: AILead) => {
    setUpdatingLeadId(lead.id)
    try {
      await ask(`请联网搜索并更新企业线索库中“${lead.company_name}”的最新公开资料。核实企业全称和简称，并重点核实官网、地址、联系人、电话、邮箱、主营业务、PEEK、PEI、PSU或改性材料相关证据、专利和来源链接；仅保存可验证信息，没有找到的字段保持空白。同时提取搜索中发现的材料供需、价格、扩产、认证、技术、应用和市场传闻，标明日期、来源及可靠度，并保存到行业情报库。`, false, lead.id)
    } finally {
      setUpdatingLeadId(undefined)
    }
  }

  const exportLeads = async () => {
    const { data } = await aiApi.exportLeads()
    const url = URL.createObjectURL(data)
    const link = document.createElement('a')
    link.href = url
    link.download = `聚泰企业线索_${new Date().toISOString().slice(0, 10)}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }

  const ready = status?.api_configured && status?.access_configured

  return (
    <div id="ai-workspace" className="space-y-4 scroll-mt-4">
      <section className="glass-panel float-panel overflow-hidden rounded-[28px]">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/60 bg-white/30 px-5 py-4">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-full border border-white/80 bg-white/55">
              <Bot className="h-4 w-4 text-cyber-neon-cyan" />
            </span>
            <div>
              <h2 className="font-mono text-xs font-semibold text-cyber-text-primary">AI 潜客分析 · 千问 Flash</h2>
              <p className="text-[10px] text-cyber-text-muted">同步分析企业线索，以及 PEEK、PEI、PSU 和改性材料行业情报</p>
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
                onClick={() => ask('请分析最新一次搜索结果：筛选与PEEK、PEI、PSU及其改性材料采购相关性最高的企业，同时整理供需、价格、扩产、技术、应用和市场传闻等行业情报，标明日期、来源、可靠度及判断理由。', true)}
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
        <header className="flex items-center justify-between gap-3 border-b border-white/60 bg-white/30 px-5 py-4">
          <div className="flex items-center gap-3">
            <Building2 className="h-4 w-4 text-cyber-neon-cyan" />
            <div>
              <h2 className="font-mono text-xs font-semibold text-cyber-text-primary">企业线索库</h2>
              <p className="text-[10px] text-cyber-text-muted">
                {leads.length} 家企业 · 已跟进 {leads.filter((lead) => lead.followed_up).length} · 未跟进 {leads.filter((lead) => !lead.followed_up).length}
              </p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={exportLeads} disabled={leads.length === 0}>
            <Download className="h-4 w-4" /> 导出 CSV
          </Button>
        </header>
        <div className="max-h-[560px] overflow-auto terminal-scroll">
          <table className="w-full min-w-[960px] table-fixed text-left text-[10px] leading-4">
            <colgroup>
              {[4, 6, 11, 14, 12, 10, 11, 17, 12, 3].map((width, index) => <col key={index} style={{ width: `${width}%` }} />)}
            </colgroup>
            <thead className="sticky top-0 z-10 bg-white/80 text-cyber-text-secondary backdrop-blur-xl">
              <tr>
                {['跟进', '更新', '企业 / 潜力', '企业信息', '联系方式', '专利', '关键词', '证据与建议', '来源', ''].map((title) => (
                  <th key={title} className="border-b border-white/70 px-2 py-2 font-semibold">{title}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {leads.map((lead) => (
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
                  </td>
                  <td className="break-words px-2 py-2 font-semibold text-cyber-text-primary">
                    {lead.company_name}
                    {lead.aliases && <div className="font-normal text-cyber-text-muted">简称：{lead.aliases}</div>}
                    <span className="font-mono text-cyber-neon-cyan">{lead.potential_score}</span>{lead.country ? ` · ${lead.country}` : ''}
                  </td>
                  <td className="break-words whitespace-pre-wrap px-2 py-2">{lead.company_info || '-'}</td>
                  <td className="break-words px-2 py-2">
                    {lead.contact_person && <div>{lead.contact_person}</div>}
                    {lead.website && <div><a href={webUrl(lead.website)} target="_blank" rel="noreferrer" className="text-cyber-neon-cyan hover:underline">官网 ↗</a></div>}
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
                  <td className="px-1 py-2">
                    <Button variant="ghost" size="sm" onClick={() => removeLead(lead.id)} className="text-cyber-neon-pink">
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </td>
                </tr>
              ))}
              {leads.length === 0 && (
                <tr><td colSpan={10} className="px-4 py-12 text-center text-cyber-text-muted">
                  分析搜索结果后，企业线索会保存在这里。
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="glass-panel float-panel overflow-hidden rounded-[28px]">
        <header className="flex items-center gap-3 border-b border-white/60 bg-white/30 px-5 py-4">
          <Newspaper className="h-4 w-4 text-cyber-neon-cyan" />
          <div>
            <h2 className="font-mono text-xs font-semibold text-cyber-text-primary">行业情报库</h2>
            <p className="text-[10px] text-cyber-text-muted">{intelligence.length} 条 · PEEK / PEI / PSU / 改性材料动态与市场传闻</p>
          </div>
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
