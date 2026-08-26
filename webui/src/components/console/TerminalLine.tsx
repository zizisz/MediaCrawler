import { cn } from '@/lib/utils'
import type { LogEntry } from '@/types/crawler'

interface TerminalLineProps {
  log: LogEntry
}

const levelConfig: Record<string, { text: string; bg: string; glow: string }> = {
  info: {
    text: 'text-cyber-neon-cyan',
    bg: 'bg-cyber-neon-cyan/10',
    glow: 'shadow-[0_0_3px_rgba(0,255,255,0.3)]'
  },
  success: {
    text: 'text-cyber-neon-green',
    bg: 'bg-cyber-neon-green/10',
    glow: 'shadow-[0_0_3px_rgba(0,255,65,0.3)]'
  },
  warning: {
    text: 'text-cyber-neon-orange',
    bg: 'bg-cyber-neon-orange/10',
    glow: 'shadow-[0_0_3px_rgba(255,152,0,0.3)]'
  },
  error: {
    text: 'text-cyber-neon-pink',
    bg: 'bg-cyber-neon-pink/10',
    glow: 'shadow-[0_0_3px_rgba(255,0,128,0.3)]'
  },
  debug: {
    text: 'text-cyber-text-secondary',
    bg: 'bg-cyber-bg-tertiary/30',
    glow: ''
  },
}

const levelIcons: Record<string, string> = {
  info: 'DATA',
  success: 'OK',
  warning: 'WARN',
  error: 'ERR',
  debug: 'DBG',
}

export function TerminalLine({ log }: TerminalLineProps) {
  const config = levelConfig[log.level] || levelConfig.info

  return (
    <div className="flex gap-2 text-xs leading-relaxed font-mono group hover:bg-cyber-bg-panel/35 px-1 -mx-1 rounded transition-colors">
      {/* Timestamp */}
      <span className="text-cyber-text-muted flex-shrink-0 opacity-70 group-hover:opacity-100 transition-opacity">
        [{log.timestamp}]
      </span>

      {/* Level badge */}
      <span className={cn(
        'flex-shrink-0 w-14 px-1 rounded text-center',
        config.bg,
        config.text,
        config.glow
      )}>
        [{levelIcons[log.level]}]
      </span>

      {/* Message */}
      <span className={cn('break-all', config.text)}>
        {log.message}
      </span>
    </div>
  )
}
