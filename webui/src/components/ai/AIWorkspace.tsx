import { useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { Bot, Building2, Download, KeyRound, Send, Sparkles, Trash2 } from 'lucide-react'
import { aiApi, type AILead } from '@/lib/api'
import { useCrawlerStore } from '@/store/crawlerStore'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

type Message = { role: 'user' | 'assistant'; content: string }

function errorMessage(error: unknown) {
  if (axios.isAxiosError(error)) return error.response?.data?.detail || error.message
  return error instanceof Error ? error.message : '请求失败'
}

export function AIWorkspace() {
  const config = useCrawlerStore((state) => state.config)
  const [status, setStatus] = useState<{ model: string; api_configured: boolean; access_configured: boolean }>()
  const [password, setPassword] = useState(() => sessionStorage.getItem('ai_access_token') || '')
  const [token, setToken] = useState('')
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', content: '我是聚泰潜客分析助手。连接后可点击“分析最新搜索结果”，也可以继续询问企业、专利和采购线索。' },
  ])
  const [leads, setLeads] = useState<AILead[]>([])
  const chatRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    aiApi.status().then(({ data }) => setStatus(data)).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight
  }, [messages, busy])

  const refreshLeads = async (accessToken = token) => {
    const { data } = await aiApi.getLeads(accessToken)
    setLeads(data.leads)
  }

  const connect = async () => {
    try {
      await refreshLeads(password)
      setToken(password)
      sessionStorage.setItem('ai_access_token', password)
    } catch (error) {
      setMessages((old) => [...old, { role: 'assistant', content: `连接失败：${errorMessage(error)}` }])
    }
  }

  const ask = async (question: string) => {
    const text = question.trim()
    if (!text || !token || busy) return
    const history = messages.slice(-8)
    setMessages((old) => [...old, { role: 'user', content: text }])
    setInput('')
    setBusy(true)
    try {
      const { data } = await aiApi.chat(token, {
        message: text,
        history,
        platform: config.platform,
        max_records: config.max_notes_count,
      })
      const suffix = `\n\n已读取 ${data.records_used} 条记录${data.source_file ? `（${data.source_file}）` : ''}，保存/更新 ${data.leads_saved} 家企业线索。`
      setMessages((old) => [...old, { role: 'assistant', content: data.answer + suffix }])
      await refreshLeads()
    } catch (error) {
      setMessages((old) => [...old, { role: 'assistant', content: `分析失败：${errorMessage(error)}` }])
    } finally {
      setBusy(false)
    }
  }

  const removeLead = async (id: string) => {
    await aiApi.deleteLead(token, id)
    setLeads((old) => old.filter((lead) => lead.id !== id))
  }

  const exportLeads = async () => {
    const { data } = await aiApi.exportLeads(token)
    const url = URL.createObjectURL(data)
    const link = document.createElement('a')
    link.href = url
    link.download = `聚泰企业线索_${new Date().toISOString().slice(0, 10)}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }

  const ready = status?.api_configured && status?.access_configured

  return (
    <div className="space-y-4">
      <section className="glass-panel float-panel overflow-hidden rounded-[28px]">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/60 bg-white/30 px-5 py-4">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-full border border-white/80 bg-white/55">
              <Bot className="h-4 w-4 text-cyber-neon-cyan" />
            </span>
            <div>
              <h2 className="font-mono text-xs font-semibold text-cyber-text-primary">AI 潜客分析 · GPT-5.6 Luna</h2>
              <p className="text-[10px] text-cyber-text-muted">分析最新搜索数据，并把有效企业线索写入下方表格</p>
            </div>
          </div>
          <span className={`font-mono text-[10px] ${ready ? 'text-cyber-neon-green' : 'text-cyber-neon-orange'}`}>
            {ready ? `${status?.model} 已配置` : '等待服务器配置'}
          </span>
        </header>

        <div className="space-y-3 p-4">
          {!token && (
            <div className="apple-subpanel flex flex-col gap-2 rounded-2xl p-3 sm:flex-row">
              <div className="relative flex-1">
                <KeyRound className="absolute left-3 top-2.5 h-4 w-4 text-cyber-text-muted" />
                <Input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  onKeyDown={(event) => { if (event.key === 'Enter') connect() }}
                  placeholder="AI 访问密码"
                  className="h-9 pl-9 text-xs"
                />
              </div>
              <Button onClick={connect} disabled={!password || !ready} className="h-9">连接 AI</Button>
              {!status?.api_configured && <p className="self-center text-[10px] text-cyber-neon-orange">服务器尚未配置 OpenAI API Key</p>}
            </div>
          )}

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
            {busy && <div className="text-xs text-cyber-text-muted animate-pulse">Luna 正在分析搜索数据…</div>}
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
              disabled={!token || busy}
              placeholder="询问企业、专利、应用方向或下一步跟进建议…"
              className="min-h-[72px] flex-1 resize-none rounded-xl border border-white/70 bg-white/40 px-3 py-2 text-xs text-cyber-text-primary outline-none focus:border-cyber-neon-cyan/60"
            />
            <div className="flex gap-2 sm:flex-col">
              <Button
                variant="outline"
                disabled={!token || busy}
                onClick={() => ask('请分析最新一次搜索结果，筛选与PEEK等工程塑料采购相关性最高的企业，并整理可验证的专利证据和下一步建议。')}
                className="flex-1"
              >
                <Sparkles className="h-4 w-4" /> 分析最新结果
              </Button>
              <Button disabled={!token || busy || !input.trim()} onClick={() => ask(input)} className="flex-1">
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
              <p className="text-[10px] text-cyber-text-muted">{leads.length} 家企业 · 同名企业自动合并专利记录</p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={exportLeads} disabled={!token || leads.length === 0}>
            <Download className="h-4 w-4" /> 导出 CSV
          </Button>
        </header>
        <div className="max-h-[460px] overflow-auto terminal-scroll">
          <table className="min-w-[1450px] w-full text-left text-[11px]">
            <thead className="sticky top-0 z-10 bg-white/80 text-cyber-text-secondary backdrop-blur-xl">
              <tr>
                {['企业名称', '潜力', '国家/地区', '企业信息', '联系方式', '专利', '关键词', '证据与建议', '来源', '操作'].map((title) => (
                  <th key={title} className="border-b border-white/70 px-3 py-3 font-mono font-semibold">{title}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {leads.map((lead) => (
                <tr key={lead.id} className="border-b border-white/45 align-top hover:bg-white/20">
                  <td className="max-w-[180px] px-3 py-3 font-semibold text-cyber-text-primary">{lead.company_name}</td>
                  <td className="px-3 py-3 font-mono text-cyber-neon-cyan">{lead.potential_score}</td>
                  <td className="max-w-[120px] px-3 py-3">{lead.country || '-'}</td>
                  <td className="max-w-[260px] whitespace-pre-wrap px-3 py-3">{lead.company_info || '-'}</td>
                  <td className="max-w-[240px] whitespace-pre-wrap px-3 py-3">
                    {[lead.contact_person, lead.website, lead.email, lead.phone, lead.address].filter(Boolean).join('\n') || '-'}
                  </td>
                  <td className="max-w-[260px] whitespace-pre-wrap px-3 py-3">{[lead.patents, lead.patent_titles].filter(Boolean).join('\n') || '-'}</td>
                  <td className="max-w-[150px] px-3 py-3">{lead.keywords || '-'}</td>
                  <td className="max-w-[300px] whitespace-pre-wrap px-3 py-3">{[lead.evidence, lead.next_action].filter(Boolean).join('\n') || '-'}</td>
                  <td className="max-w-[220px] whitespace-pre-wrap px-3 py-3">{[lead.source_platform, lead.source_urls].filter(Boolean).join('\n') || '-'}</td>
                  <td className="px-3 py-3">
                    <Button variant="ghost" size="sm" onClick={() => removeLead(lead.id)} className="text-cyber-neon-pink">
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </td>
                </tr>
              ))}
              {leads.length === 0 && (
                <tr><td colSpan={10} className="px-4 py-12 text-center text-cyber-text-muted">连接 AI 并分析搜索结果后，企业线索会保存在这里。</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
