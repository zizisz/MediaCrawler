import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import axios from 'axios'
import { toast } from 'sonner'
import { FileJson, FileSpreadsheet, FileText, Download, Eye, Pencil, Trash2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { dataApi } from '@/lib/api'
import { formatFileSize, formatDateTime } from '@/lib/utils'
import { DataPreviewDialog } from './preview/DataPreviewDialog'
import type { DataFile } from '@/types/crawler'

interface FileCardProps {
  file: DataFile
  onChanged: () => void | Promise<unknown>
  selected: boolean
  onSelectedChange: (selected: boolean) => void
}

const fileIcons: Record<string, typeof FileJson> = {
  json: FileJson,
  csv: FileSpreadsheet,
  xlsx: FileSpreadsheet,
  xls: FileSpreadsheet,
}

const fileStyles: Record<string, { icon: string; border: string; badge: string }> = {
  json: {
    icon: 'text-cyber-neon-yellow',
    border: 'hover:border-cyber-neon-yellow/50',
    badge: 'border-cyber-neon-yellow/30 bg-cyber-neon-yellow/10 text-cyber-neon-yellow'
  },
  csv: {
    icon: 'text-cyber-neon-green',
    border: 'hover:border-cyber-neon-green/50',
    badge: 'border-cyber-neon-green/30 bg-cyber-neon-green/10 text-cyber-neon-green'
  },
  xlsx: {
    icon: 'text-cyber-neon-cyan',
    border: 'hover:border-cyber-neon-cyan/50',
    badge: 'border-cyber-neon-cyan/30 bg-cyber-neon-cyan/10 text-cyber-neon-cyan'
  },
  xls: {
    icon: 'text-cyber-neon-cyan',
    border: 'hover:border-cyber-neon-cyan/50',
    badge: 'border-cyber-neon-cyan/30 bg-cyber-neon-cyan/10 text-cyber-neon-cyan'
  },
}

export function FileCard({ file, onChanged, selected, onSelectedChange }: FileCardProps) {
  const { t } = useTranslation('data')
  const [previewOpen, setPreviewOpen] = useState(false)

  const Icon = fileIcons[file.type] || FileText
  const styles = fileStyles[file.type] || {
    icon: 'text-cyber-text-muted',
    border: 'hover:border-cyber-neon-cyan/50',
    badge: 'border-cyber-border-DEFAULT bg-cyber-bg-tertiary text-cyber-text-secondary'
  }

  // 检查是否支持预览
  const isPreviewable = ['json', 'csv', 'xlsx', 'xls'].includes(file.type.toLowerCase())

  const handleDownload = () => {
    const url = dataApi.getDownloadUrl(file.path)
    window.open(url, '_blank')
  }

  const errorMessage = (error: unknown) =>
    axios.isAxiosError(error) ? error.response?.data?.detail : undefined

  const handleRename = async () => {
    const stem = file.name.slice(0, -(file.type.length + 1))
    const name = window.prompt(t('file.renamePrompt'), stem)?.trim()
    if (!name) return
    try {
      await dataApi.renameFile(file.path, name)
      await onChanged()
      toast.success(t('file.renameSuccess'))
    } catch (error) {
      toast.error(errorMessage(error) || t('file.actionError'))
    }
  }

  const handleDelete = async () => {
    if (!window.confirm(t('file.deleteConfirm', { name: file.name }))) return
    try {
      await dataApi.deleteFile(file.path)
      await onChanged()
      toast.success(t('file.deleteSuccess'))
    } catch (error) {
      toast.error(errorMessage(error) || t('file.actionError'))
    }
  }

  return (
    <>
      <Card className={`relative overflow-hidden card-scan group transition-all ${styles.border} hover:shadow-[0_0_15px_rgb(var(--cyber-neon-cyan)/0.15)]`}>
        <label className="absolute right-3 top-3 z-10 flex items-center gap-1.5 rounded-full border border-white/70 bg-white/75 px-2 py-1 text-[10px] text-cyber-text-secondary shadow-sm">
          <input type="checkbox" checked={selected} onChange={(event) => onSelectedChange(event.target.checked)} aria-label={`选择 ${file.name}`} />
          选择
        </label>
        {/* Scan effect overlay */}
        <div className="absolute inset-0 bg-gradient-to-r from-transparent via-cyber-neon-cyan/5 to-transparent -translate-x-full group-hover:translate-x-full transition-transform duration-700 pointer-events-none" />

        <CardContent className="p-4 pt-11 relative">
          <div className="flex items-start gap-3">
            <div className={`relative group/file p-2 rounded bg-cyber-bg-panel border border-cyber-border-DEFAULT ${styles.icon}`}>
              <Icon className="w-6 h-6 transition-opacity group-hover/file:opacity-0" />
              <div className="absolute inset-0 flex items-center justify-center gap-0.5 opacity-0 group-hover/file:opacity-100 transition-opacity">
                <button
                  type="button"
                  title={t('file.rename')}
                  aria-label={t('file.rename')}
                  onClick={handleRename}
                  className="rounded p-1 text-cyber-neon-cyan hover:bg-cyber-neon-cyan/15"
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  title={t('file.delete')}
                  aria-label={t('file.delete')}
                  onClick={handleDelete}
                  className="rounded p-1 text-cyber-neon-pink hover:bg-cyber-neon-pink/15"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="font-mono font-medium text-sm text-cyber-text-primary truncate" title={file.name}>
                {file.name}
              </h3>
              <p className="text-xs text-cyber-text-muted mt-1 font-mono">
                {formatFileSize(file.size)}
                {file.record_count !== null && (
                  <span className="text-cyber-neon-green"> | {t('file.entries', { count: file.record_count })}</span>
                )}
              </p>
              <p className="text-xs text-cyber-text-muted mt-1 font-mono">
                {formatDateTime(file.modified_at)}
              </p>
              {file.record_count !== null && (
                <span className={`mt-1 inline-flex rounded-full border px-2 py-0.5 text-[10px] font-mono ${
                  file.analyzed_count >= file.record_count && file.record_count > 0
                    ? 'border-cyber-neon-green/40 bg-cyber-neon-green/10 text-cyber-neon-green'
                    : file.analyzed_count > 0
                      ? 'border-cyber-neon-cyan/30 bg-cyber-neon-cyan/10 text-cyber-neon-cyan'
                      : 'border-cyber-border-subtle text-cyber-text-muted'
                }`}>
                  {file.analyzed_count >= file.record_count && file.record_count > 0
                    ? 'AI 已分析'
                    : file.analyzed_count > 0
                      ? `AI 已分析 ${file.analyzed_count}/${file.record_count}`
                      : 'AI 未分析'}
                </span>
              )}
            </div>
          </div>

          <div className="flex items-center justify-between mt-3 pt-3 border-t border-cyber-border-subtle">
            <Badge variant="outline" className={`text-[10px] font-mono ${styles.badge}`}>
              .{file.type.toUpperCase()}
            </Badge>
            <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              {isPreviewable && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 font-mono text-cyber-neon-cyan hover:text-cyber-neon-cyan hover:bg-cyber-neon-cyan/10"
                  onClick={() => setPreviewOpen(true)}
                >
                  <Eye className="w-3 h-3 mr-1" />
                  {t('file.preview')}
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2 font-mono text-cyber-neon-cyan hover:text-cyber-neon-cyan hover:bg-cyber-neon-cyan/10"
                onClick={handleDownload}
              >
                <Download className="w-3 h-3 mr-1" />
                {t('file.extract')}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 预览对话框 */}
      {isPreviewable && (
        <DataPreviewDialog
          file={file}
          open={previewOpen}
          onOpenChange={setPreviewOpen}
        />
      )}
    </>
  )
}
