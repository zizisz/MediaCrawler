import { useEffect, useState } from 'react'
import { Wifi } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { aiApi } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { useCrawlerStore } from '@/store/crawlerStore'
import { useCrawlerStatus } from '@/hooks/useCrawler'
import { LanguageSwitch } from './LanguageSwitch'
import { ThemeToggle } from './ThemeToggle'

type WorkspaceView = 'leads' | 'analysis' | 'intelligence' | 'crawler'
type AIProviderStatus = {
  model: string
  provider: 'qwen' | 'gemini'
  providers: { qwen: boolean; gemini: boolean }
}

interface SidebarProps {
  activeView: WorkspaceView
  onViewChange: (view: WorkspaceView) => void
}

export function Sidebar({ activeView, onViewChange }: SidebarProps) {
  const { t } = useTranslation()
  const status = useCrawlerStore((state) => state.status)
  const [aiStatus, setAIStatus] = useState<AIProviderStatus>()
  const [switchingProvider, setSwitchingProvider] = useState(false)

  // Poll status
  useCrawlerStatus()

  const isRunning = status === 'running'

  useEffect(() => {
    aiApi.status().then(({ data }) => setAIStatus(data)).catch(() => undefined)
    const syncProvider = (event: Event) => setAIStatus((event as CustomEvent<AIProviderStatus>).detail)
    window.addEventListener('ai-provider-changed', syncProvider)
    return () => window.removeEventListener('ai-provider-changed', syncProvider)
  }, [])

  const changeProvider = async (provider: 'qwen' | 'gemini') => {
    if (switchingProvider || aiStatus?.provider === provider) return
    setSwitchingProvider(true)
    try {
      await aiApi.setProvider(provider)
      const { data } = await aiApi.status()
      setAIStatus(data)
      window.dispatchEvent(new CustomEvent('ai-provider-changed', { detail: data }))
    } catch {
      window.alert('模型切换失败，请检查服务器配置')
    } finally {
      setSwitchingProvider(false)
    }
  }

  return (
    <header className="h-14 flex-shrink-0 glass-panel border-b border-cyber-border-subtle relative z-10">
      <div className="h-full px-4 flex items-center gap-4">
        <div className="flex items-center gap-3">
          <span className="font-mono font-bold text-cyber-text-primary tracking-wider text-sm">
            聚泰企业线索系统
          </span>
          <nav className="ml-2 flex flex-wrap gap-1" aria-label="功能切换">
            {[
              ['leads', '企业线索库'],
              ['analysis', 'AI 分析'],
              ['intelligence', '行业情报'],
              ['crawler', '平台搜索'],
            ].map(([view, title]) => (
              <button key={view} type="button" onClick={() => onViewChange(view as WorkspaceView)}
                className={`h-7 rounded-md border px-2.5 text-xs font-semibold transition-colors ${activeView === view ? 'border-cyber-neon-cyan bg-white text-cyber-text-primary' : 'border-white/70 bg-white/80 text-cyber-text-secondary hover:border-cyber-neon-cyan/60'}`}>
                {title}
              </button>
            ))}
          </nav>
          {isRunning && (
            <Badge variant="running" className="text-[10px]">
              {t('status.active')}
            </Badge>
          )}
          {isRunning && (
            <span className="w-2 h-2 bg-cyber-neon-green rounded-full shadow-glow-green-sm animate-pulse-fast" />
          )}
        </div>

        <div className="ml-auto flex items-center gap-3">
          <div className="flex rounded-md border border-white/70 p-0.5 text-[10px]" aria-label="AI 模型切换">
            <button type="button" onClick={() => changeProvider('qwen')} disabled={switchingProvider || !aiStatus?.providers.qwen}
              className={`h-6 rounded px-2 ${aiStatus?.provider === 'qwen' ? 'bg-cyber-neon-cyan text-white' : 'text-cyber-text-muted hover:bg-white disabled:opacity-40'}`}>千问 Flash</button>
            <button type="button" onClick={() => changeProvider('gemini')} disabled={switchingProvider || !aiStatus?.providers.gemini}
              title={aiStatus?.providers.gemini ? '切换至 Gemini 3.6 Flash（含 Google 搜索）' : '服务器尚未配置 Gemini API Key'}
              className={`h-6 rounded px-2 ${aiStatus?.provider === 'gemini' ? 'bg-cyber-neon-cyan text-white' : 'text-cyber-text-muted hover:bg-white disabled:opacity-40'}`}>Gemini 3.6 Flash</button>
          </div>
          {/* Theme Toggle */}
          <ThemeToggle />
          {/* Language Switch */}
          <LanguageSwitch />

          {/* Status Info */}
          <div className="hidden lg:flex items-center gap-2 text-xs font-mono">
            <span className="text-cyber-text-muted">系统版本:</span>
            <span className="text-cyber-neon-green">v2.9.18</span>
            <div className="flex items-center gap-1.5">
              <Wifi className="w-3 h-3 text-cyber-text-secondary" />
              <span className="text-cyber-text-secondary">服务器</span>
              <span className="status-dot status-dot-online" />
            </div>
          </div>
        </div>
      </div>
    </header>
  )
}
