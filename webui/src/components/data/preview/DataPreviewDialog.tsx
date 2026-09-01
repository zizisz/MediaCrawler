import { useQuery } from '@tanstack/react-query'
import { useDeferredValue, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import axios from 'axios'
import { toast } from 'sonner'
import { Download, Sparkles } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { aiApi, dataApi } from '@/lib/api'
import { DataPreviewTable } from './DataPreviewTable'
import type { DataFile } from '@/types/crawler'

interface DataPreviewDialogProps {
  file: DataFile
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function DataPreviewDialog({ file, open, onOpenChange }: DataPreviewDialogProps) {
  const { t } = useTranslation('data')
  const [page, setPage] = useState(0)
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedIndices, setSelectedIndices] = useState<Set<number>>(new Set())
  const [analyzing, setAnalyzing] = useState(false)
  const deferredSearch = useDeferredValue(searchTerm)
  const pageSize = 50

  useEffect(() => {
    setPage(0)
    setSearchTerm('')
    setSelectedIndices(new Set())
  }, [file.path])

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['filePreview', file.path, page, deferredSearch],
    queryFn: async () => {
      const { data } = await dataApi.getFileContent(
        file.path,
        pageSize,
        page * pageSize,
        deferredSearch,
      )
      return data
    },
    enabled: open,
    placeholderData: (previousData) => previousData,
  })

  const handleDownload = () => {
    const url = dataApi.getDownloadUrl(file.path)
    window.open(url, '_blank')
  }

  const toggle = (index: number) => setSelectedIndices((old) => {
    const next = new Set(old)
    next.has(index) ? next.delete(index) : next.add(index)
    return next
  })

  const togglePage = (indices: number[], checked: boolean) => setSelectedIndices((old) => {
    const next = new Set(old)
    indices.forEach((index) => checked ? next.add(index) : next.delete(index))
    return next
  })

  const analyzeSelected = async () => {
    if (!selectedIndices.size || analyzing) return
    setAnalyzing(true)
    try {
      const { data: result } = await aiApi.chat({
        message: '请分析我在数据浏览器中选择的记录：筛选PEEK、PEI、PSU及其改性材料潜在采购企业，并整理相关行业情报、日期、来源和可靠度。',
        history: [],
        platform: file.path.split('/')[0],
        max_records: selectedIndices.size,
        source_file: file.path,
        record_indices: [...selectedIndices],
      })
      toast.success(`AI 已分析 ${result.records_used} 条记录`)
      setSelectedIndices(new Set())
      await refetch()
      window.dispatchEvent(new Event('ai-analysis-updated'))
    } catch (error) {
      toast.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : 'AI 分析失败')
    } finally {
      setAnalyzing(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-6xl h-[85vh] flex flex-col">
        <DialogHeader className="flex-shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <DialogTitle className="font-mono text-cyber-neon-cyan">
                {file.name}
              </DialogTitle>
              <Badge variant="outline" className="font-mono text-[10px]">
                .{file.type.toUpperCase()}
              </Badge>
              {data && (
                <Badge variant="default" className="font-mono text-[10px]">
                  {t('preview.records', { count: data.all_total })}
                </Badge>
              )}
            </div>
            <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={analyzeSelected} disabled={!selectedIndices.size || analyzing} className="font-mono text-xs">
              <Sparkles className="w-3 h-3 mr-1" />
              {analyzing ? '分析中…' : `分析所选 (${selectedIndices.size})`}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleDownload}
              className="font-mono text-xs"
            >
              <Download className="w-3 h-3 mr-1" />
              {t('preview.download')}
            </Button>
            </div>
          </div>
        </DialogHeader>

        {/* 内容区域 */}
        <div className="flex-1 overflow-hidden min-h-0 mt-4">
          {isLoading ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-cyber-text-muted font-mono animate-pulse">
                {t('preview.loading')}
              </div>
            </div>
          ) : error ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-cyber-neon-pink font-mono">
                {t('preview.error')}
              </div>
            </div>
          ) : data ? (
            <DataPreviewTable
              data={data.data}
              rowIndices={data.row_indices}
              analyzed={data.analyzed}
              selectedIndices={selectedIndices}
              onToggle={toggle}
              onTogglePage={togglePage}
              columns={data.columns}
              searchTerm={searchTerm}
              onSearchTermChange={(value) => {
                setSearchTerm(value)
                setPage(0)
              }}
              page={page}
              pageSize={pageSize}
              total={data.total}
              onPageChange={setPage}
            />
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  )
}
