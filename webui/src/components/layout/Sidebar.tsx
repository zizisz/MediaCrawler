import { useRef, useState, type ChangeEvent } from 'react'
import { Bug, Wifi, AlertTriangle, Github, ImagePlus, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { useCrawlerStore } from '@/store/crawlerStore'
import { useCrawlerStatus } from '@/hooks/useCrawler'
import { LanguageSwitch } from './LanguageSwitch'
import { ThemeToggle } from './ThemeToggle'

interface SidebarProps {
  onShowDisclaimer?: () => void
  onBackgroundUploaded?: () => void
}

export function Sidebar({ onShowDisclaimer, onBackgroundUploaded }: SidebarProps) {
  const { t } = useTranslation()
  const { t: tLicense } = useTranslation('license')
  const status = useCrawlerStore((state) => state.status)
  const backgroundInput = useRef<HTMLInputElement>(null)
  const [uploadingBackground, setUploadingBackground] = useState(false)

  // Poll status
  useCrawlerStatus()

  const isRunning = status === 'running'

  const handleBackground = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (!['image/jpeg', 'image/png', 'image/webp', 'image/gif'].includes(file.type) || file.size > 10 * 1024 * 1024) {
      toast.error(t('sidebar.backgroundInvalid'))
      return
    }

    setUploadingBackground(true)
    try {
      const response = await fetch('/api/background', {
        method: 'PUT',
        headers: { 'Content-Type': file.type },
        body: file,
      })
      if (!response.ok) throw new Error(await response.text())
      onBackgroundUploaded?.()
      toast.success(t('sidebar.backgroundUploaded'))
    } catch {
      toast.error(t('sidebar.backgroundFailed'))
    } finally {
      setUploadingBackground(false)
    }
  }

  return (
    <header className="h-14 flex-shrink-0 glass-panel border-b border-cyber-border-subtle relative z-10">
      <div className="h-full px-4 flex items-center justify-between">
        {/* Left: Logo and GitHub Star */}
        <div className="flex items-center gap-3">
          <Bug className="w-5 h-5 text-cyber-neon-cyan" />
          <span className="font-mono font-bold text-cyber-text-primary tracking-wider text-sm">
            MediaCrawler
          </span>
          <a
            href="https://github.com/NanmiCoder/MediaCrawler"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 px-2 py-1 rounded-md border border-cyber-border-subtle hover:border-cyber-neon-cyan hover:shadow-glow-cyan-sm transition-all bg-cyber-bg-tertiary"
          >
            <Github className="w-4 h-4 text-cyber-text-secondary" />
            <span className="text-xs font-mono text-cyber-text-secondary">Star</span>
          </a>
          {isRunning && (
            <Badge variant="running" className="text-[10px]">
              {t('status.active')}
            </Badge>
          )}
          {isRunning && (
            <span className="w-2 h-2 bg-cyber-neon-green rounded-full shadow-glow-green-sm animate-pulse-fast" />
          )}
        </div>

        {/* Center: Warning Text */}
        <button
          onClick={onShowDisclaimer}
          className="flex items-center gap-3 px-4 py-1.5 rounded-lg border border-cyber-neon-orange/50 bg-cyber-neon-orange/10 hover:bg-cyber-neon-orange/20 transition-all cursor-pointer"
        >
          <AlertTriangle className="w-4 h-4 text-cyber-neon-orange flex-shrink-0" />
          <div className="flex items-center gap-4 text-xs font-mono">
            <span className="text-cyber-neon-orange">
              <span className="text-cyber-neon-pink font-bold">1.</span> {tLicense('content.line1')}
            </span>
            <span className="text-cyber-neon-orange">
              <span className="text-cyber-neon-pink font-bold">2.</span> {tLicense('content.line2')}
            </span>
          </div>
        </button>

        {/* Right: Actions and Status */}
        <div className="flex items-center gap-3">
          <input
            ref={backgroundInput}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/gif"
            className="hidden"
            onChange={handleBackground}
          />
          <button
            type="button"
            onClick={() => backgroundInput.current?.click()}
            disabled={uploadingBackground}
            className="inline-flex h-9 items-center gap-2 rounded-full border border-white/55 bg-white/25 px-3 text-xs font-mono text-cyber-text-primary backdrop-blur-xl transition hover:bg-white/40 disabled:opacity-50"
            title={t('sidebar.background')}
          >
            {uploadingBackground
              ? <Loader2 className="h-4 w-4 animate-spin" />
              : <ImagePlus className="h-4 w-4" />}
            <span className="hidden xl:inline">{t('sidebar.background')}</span>
          </button>
          {/* Theme Toggle */}
          <ThemeToggle />
          {/* Language Switch */}
          <LanguageSwitch />

          {/* Status Info */}
          <div className="hidden lg:flex items-center gap-2 text-xs font-mono">
            <span className="text-cyber-text-muted">{t('sidebar.api')}:</span>
            <span className="text-cyber-neon-green">v1.0.0</span>
            <div className="flex items-center gap-1.5">
              <Wifi className="w-3 h-3 text-cyber-text-secondary" />
              <span className="text-cyber-text-secondary">{t('sidebar.local')}</span>
              <span className="status-dot status-dot-online" />
            </div>
          </div>
        </div>
      </div>
    </header>
  )
}
