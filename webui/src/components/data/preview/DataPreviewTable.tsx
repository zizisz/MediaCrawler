import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronLeft, ChevronRight, Search } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'

interface DataPreviewTableProps {
  data: Record<string, unknown>[]
  rowIndices: number[]
  analyzed: boolean[]
  selectedIndices: Set<number>
  onToggle: (index: number) => void
  onTogglePage: (indices: number[], checked: boolean) => void
  columns?: string[]
  searchTerm: string
  onSearchTermChange: (value: string) => void
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
}

export function DataPreviewTable({
  data,
  rowIndices,
  analyzed,
  selectedIndices,
  onToggle,
  onTogglePage,
  columns: propColumns,
  searchTerm,
  onSearchTermChange,
  page,
  pageSize,
  total,
  onPageChange,
}: DataPreviewTableProps) {
  const { t } = useTranslation('data')

  // 自动获取列名（JSON 可能没有 columns）
  const columns = useMemo(() => {
    if (propColumns && propColumns.length > 0) return propColumns
    if (data.length === 0) return []
    return Object.keys(data[0])
  }, [data, propColumns])

  // 格式化单元格值
  const formatCellValue = (value: unknown): string => {
    if (value === null || value === undefined) return '-'
    if (typeof value === 'object') return JSON.stringify(value)
    return String(value)
  }

  return (
    <div className="h-full flex flex-col">
      {/* 搜索栏 */}
      <div className="flex-shrink-0 mb-3">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-cyber-text-muted" />
          <Input
            placeholder={t('preview.searchPlaceholder')}
            value={searchTerm}
            onChange={(e) => onSearchTermChange(e.target.value)}
            className="pl-9 h-9 text-xs font-mono"
          />
        </div>
      </div>

      {/* 表格 */}
      <ScrollArea className="flex-1 border border-cyber-border-DEFAULT rounded-lg">
        <div className="min-w-full">
          <table className="w-full text-xs font-mono">
            <thead className="sticky top-0 bg-cyber-bg-tertiary border-b border-cyber-border-DEFAULT">
              <tr>
                <th className="px-3 py-2 text-left whitespace-nowrap">
                  <input
                    type="checkbox"
                    checked={rowIndices.length > 0 && rowIndices.every((index) => selectedIndices.has(index))}
                    onChange={(event) => onTogglePage(rowIndices, event.target.checked)}
                    aria-label="选择本页"
                  />
                </th>
                <th className="px-3 py-2 text-left text-cyber-text-muted whitespace-nowrap">AI 状态</th>
                <th className="px-3 py-2 text-left text-cyber-text-muted w-12">#</th>
                {columns.map((col) => (
                  <th
                    key={col}
                    className="px-3 py-2 text-left text-cyber-neon-cyan whitespace-nowrap"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((row, idx) => {
                const rowIndex = rowIndices[idx]
                return (
                <tr
                  key={rowIndex}
                  className="border-b border-cyber-border-subtle hover:bg-cyber-bg-elevated/50 transition-colors"
                >
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      checked={selectedIndices.has(rowIndex)}
                      onChange={() => onToggle(rowIndex)}
                      aria-label={`选择第 ${rowIndex + 1} 条`}
                    />
                  </td>
                  <td className={`px-3 py-2 whitespace-nowrap ${analyzed[idx] ? 'text-cyber-neon-green' : 'text-cyber-text-muted'}`}>
                    {analyzed[idx] ? '已分析' : '未分析'}
                  </td>
                  <td className="px-3 py-2 text-cyber-text-muted">{page * pageSize + idx + 1}</td>
                  {columns.map((col) => (
                    <td
                      key={col}
                      className="px-3 py-2 text-cyber-text-primary max-w-xs truncate"
                      title={formatCellValue(row[col])}
                    >
                      {formatCellValue(row[col])}
                    </td>
                  ))}
                </tr>
              )})}
            </tbody>
          </table>
        </div>
      </ScrollArea>

      <div className="mt-2 flex flex-shrink-0 items-center justify-between text-xs text-cyber-text-muted font-mono">
        <span>{t('preview.showing', {
          start: total ? page * pageSize + 1 : 0,
          end: Math.min((page + 1) * pageSize, total),
          total,
        })}</span>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => onPageChange(page - 1)} disabled={page === 0}>
            <ChevronLeft className="h-4 w-4" />
            {t('preview.previous')}
          </Button>
          <Button variant="outline" size="sm" onClick={() => onPageChange(page + 1)} disabled={(page + 1) * pageSize >= total}>
            {t('preview.next')}
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  )
}
