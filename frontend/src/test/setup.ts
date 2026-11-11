import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// findBy*/waitFor default to 1 s. Multi-step flows (sign in -> session refresh -> dashboard lists) can exceed
// that on shared 2-4 vCPU CI runners (seen once in CI on App.test.tsx, never reproduced locally). A genuine
// failure still fails; it just gets a realistic window. Vitest's testTimeout is raised to match.
configure({ asyncUtilTimeout: 5000 })

// jsdom has <dialog> but not its modal methods. This minimal stand-in opens and closes the element and fires
// "close"; real browsers (and the Playwright run) exercise the native focus trapping and Escape handling.
if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    if (!this.hasAttribute('open')) return
    this.removeAttribute('open')
    this.dispatchEvent(new Event('close'))
  }
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  document.title = ''
})
