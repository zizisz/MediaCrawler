//da
import { useState } from 'react'
import { Toaster } from 'sonner'
import { Sidebar } from '@/components/layout/Sidebar'
import { MainContent } from '@/components/layout/MainContent'
import { CrawlerConfigPanel } from '@/components/config/CrawlerConfigPanel'
import { EnvironmentCheck, isEnvChecked } from '@/components/env/EnvironmentCheck'
import { LicenseDisclaimer, isLicenseAccepted } from '@/components/license/LicenseDisclaimer'
import { AIWorkspace } from '@/components/ai/AIWorkspace'

function App() {
  // Initialize by checking localStorage if license has been accepted
  const [licenseAccepted, setLicenseAccepted] = useState(() => isLicenseAccepted())
  // Initialize by checking localStorage if env check has passed
  const [envChecked, setEnvChecked] = useState(() => isEnvChecked())
  const [activeView, setActiveView] = useState<'leads' | 'analysis' | 'intelligence' | 'crawler'>('leads')

  const handleEnvCheckComplete = () => {
    setEnvChecked(true)
  }

  const handleLicenseAccept = () => {
    setLicenseAccepted(true)
  }

  return (
    <div className="relative flex h-screen flex-col overflow-hidden cyber-grid">
      <div className="relative z-10 flex h-screen min-h-0 flex-col overflow-hidden">
      {/* License Disclaimer Modal - Shows first or when triggered */}
      {!licenseAccepted && (
        <LicenseDisclaimer onAccept={handleLicenseAccept} />
      )}

      {/* Environment Check Modal - Shows after license accepted */}
      {licenseAccepted && !envChecked && (
        <EnvironmentCheck onCheckComplete={handleEnvCheckComplete} />
      )}

      <Sidebar activeView={activeView} onViewChange={setActiveView} />

      {/* Main Area */}
      <div className="flex min-h-0 w-full flex-1 flex-col overflow-hidden">
        {activeView === 'crawler' && <div className="h-full min-h-0 space-y-2 overflow-y-auto"><CrawlerConfigPanel /><MainContent /></div>}
        {['leads', 'analysis', 'intelligence'].includes(activeView) && <AIWorkspace view={activeView as 'leads' | 'analysis' | 'intelligence'} />}
      </div>

      {/* Author Footer */}
      {/* <AuthorFooter /> */}

      {/* Toast notifications - Theme-aware style */}
      <Toaster
        position="top-right"
        toastOptions={{
          className: 'glass-panel font-mono text-cyber-text-primary',
          style: {
            fontFamily: 'JetBrains Mono, monospace',
          },
        }}
      />
      </div>
    </div>
  )
}

export default App
