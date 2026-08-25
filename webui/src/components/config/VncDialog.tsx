import { FormEvent, useEffect, useRef, useState } from 'react'
import RFB from '@novnc/novnc'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'

type VncDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function VncDialog({ open, onOpenChange }: VncDialogProps) {
  const { t } = useTranslation('config')
  const screenRef = useRef<HTMLDivElement>(null)
  const [password, setPassword] = useState('')
  const [credential, setCredential] = useState<string | null>(null)
  const [status, setStatus] = useState('password')

  useEffect(() => {
    if (!open || !credential || !screenRef.current) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    let authFailed = false
    screenRef.current.replaceChildren()
    const rfb = new RFB(screenRef.current, `${protocol}//${window.location.host}/api/ws/vnc`, {
      shared: true,
      credentials: { username: '', password: credential, target: '' },
    })
    rfb.scaleViewport = true
    rfb.resizeSession = false
    rfb.background = '#000'
    rfb.addEventListener('connect', () => setStatus('connected'))
    rfb.addEventListener('credentialsrequired', () => {
      authFailed = true
      setCredential(null)
      setStatus('password')
    })
    rfb.addEventListener('securityfailure', () => {
      authFailed = true
      setCredential(null)
      setStatus('authFailed')
    })
    rfb.addEventListener('disconnect', (event) => {
      if (!authFailed) setStatus(event.detail.clean ? 'closed' : 'disconnected')
    })
    return () => {
      rfb.disconnect()
    }
  }, [open, credential])

  useEffect(() => {
    if (!open) {
      setPassword('')
      setCredential(null)
      setStatus('password')
    }
  }, [open])

  const submitPassword = (event: FormEvent) => {
    event.preventDefault()
    setStatus('connecting')
    setCredential(password)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-none w-[96vw] h-[92vh] grid grid-rows-[auto_1fr] p-4">
        <DialogHeader>
          <DialogTitle>{t('vnc.title')}</DialogTitle>
        </DialogHeader>
        <div className="relative min-h-0 overflow-hidden rounded-md bg-black border border-cyber-border-subtle">
          <div ref={screenRef} className="w-full h-full" />
          {status !== 'connected' && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/70">
              {status === 'password' || status === 'authFailed' ? (
                <form onSubmit={submitPassword} className="w-80 space-y-3 rounded-lg glass-panel-dark p-5">
                  <p className="text-sm font-mono text-cyber-text-primary">
                    {t(status === 'authFailed' ? 'vnc.authFailed' : 'vnc.passwordPrompt')}
                  </p>
                  <Input
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder={t('vnc.passwordPlaceholder')}
                    autoFocus
                  />
                  <Button type="submit" className="w-full" disabled={!password}>
                    {t('vnc.connect')}
                  </Button>
                </form>
              ) : (
                <p className="font-mono text-sm text-cyber-text-secondary">
                  {t(`vnc.${status}`)}
                </p>
              )}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
