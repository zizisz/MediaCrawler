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
  // State for showing disclaimer manually
  const [showDisclaimer, setShowDisclaimer] = useState(false)
  const [backgroundVersion, setBackgroundVersion] = useState(0)

  const handleEnvCheckComplete = () => {
    setEnvChecked(true)
  }

  const handleLicenseAccept = () => {
    setLicenseAccepted(true)
    setShowDisclaimer(false)
  }

  const handleShowDisclaimer = () => {
    setShowDisclaimer(true)
  }

  return (
    <div className="flex flex-col min-h-screen cyber-grid relative overflow-hidden">
      <img
        key={backgroundVersion}
        className="terranova-bg custom-background"
        src={`/api/background?v=${backgroundVersion}`}
        alt=""
        aria-hidden="true"
        onError={(event) => { event.currentTarget.hidden = true }}
      />

      <div className="relative z-10 flex min-h-screen flex-col">
      {/* License Disclaimer Modal - Shows first or when triggered */}
      {(!licenseAccepted || showDisclaimer) && (
        <LicenseDisclaimer onAccept={handleLicenseAccept} />
      )}

      {/* Environment Check Modal - Shows after license accepted */}
      {licenseAccepted && !showDisclaimer && !envChecked && (
        <EnvironmentCheck onCheckComplete={handleEnvCheckComplete} />
      )}

      {/* Header Bar */}
      <Sidebar
        onShowDisclaimer={handleShowDisclaimer}
        onBackgroundUploaded={() => setBackgroundVersion(Date.now())}
      />

      {/* Main Area */}
      <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-4 p-4">
        {/* Config Panel - Primary Action Area (Always Expanded) */}
        <div className="flex-shrink-0">
          <CrawlerConfigPanel />
        </div>

        {/* Console - Collapsible Terminal */}
        <MainContent />

        {/* AI analysis and persistent company leads */}
        <AIWorkspace />
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
