import { Terminal } from '@/components/console/Terminal'
import { useLogWebSocket } from '@/hooks/useWebSocket'

export function MainContent() {
  // Connect to WebSocket for logs
  useLogWebSocket()

  return (
    <main className="relative z-10 h-[360px] min-h-[320px] flex-shrink-0">
      <Terminal />
    </main>
  )
}
