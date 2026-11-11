// The complete user journey in a real browser, against the real API with the fake AI provider (see
// playwright.config.ts). The resume and job description are the synthetic samples the fake provider has canned
// responses for (backend/tests/fixtures/documents.py). Every run registers a new throwaway account in a new
// temporary database and deletes it at the end.
import fs from 'node:fs'
import path from 'node:path'
import { expect, test, type Locator, type Page } from '@playwright/test'

const FIXTURES = path.join(import.meta.dirname, 'fixtures')
const RESUME = path.join(FIXTURES, 'jane-doe-resume.md')
const JOB_TEXT = fs.readFileSync(path.join(FIXTURES, 'job.txt'), 'utf8')
const EMAIL = `e2e-${Date.now()}@example.com`
const PASSWORD = 'correct horse battery staple'

test.describe.configure({ mode: 'serial' })

let page: Page
const consoleErrors: string[] = []
const serverErrors: string[] = []
const clientErrors: string[] = []
const ids = { resume: '', match: '', job: '', rewrite: '' }

const nav = (name: string) => page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name, exact: true })
const h1 = (name: string | RegExp) => page.getByRole('heading', { level: 1, name })
const lastSegment = () => new URL(page.url()).pathname.split('/').pop() ?? ''

async function currentVersion(): Promise<number> {
  const meta = await page.locator('.rewrite-head .report-meta').first().textContent()
  return Number(/version (\d+)/.exec(meta ?? '')?.[1])
}

async function waitForVersion(version: number) {
  await expect(page.locator('.rewrite-head .report-meta').first()).toContainText(`version ${version}`)
}

/**
 * Scrolls to an element, lets the scroll settle, then clicks it. The rewrite page holds a sandboxed preview
 * iframe, which Chrome may render out of process; a click dispatched in the same instant as a long programmatic
 * scroll can then be routed to the iframe using stale hit-test data and never reach the page. A person scrolling
 * and then clicking does not hit this, so the wait models them. (Diagnosed: no pointer events reached the page.)
 */
async function settledClick(locator: Locator) {
  await locator.scrollIntoViewIfNeeded()
  await page.waitForTimeout(300)
  await locator.click()
}

async function noHorizontalScroll() {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow, 'page scrolls horizontally').toBeLessThanOrEqual(1)
}

async function download(format: 'PDF' | 'DOCX') {
  const [file] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: `Download ${format}` }).click(),
  ])
  const target = test.info().outputPath(file.suggestedFilename())
  await file.saveAs(target)
  const head = fs.readFileSync(target).subarray(0, 4).toString('latin1')
  expect(head).toBe(format === 'PDF' ? '%PDF' : 'PK\u0003\u0004')
  await expect(page.getByText(`Downloaded ${file.suggestedFilename()}.`)).toBeVisible()
}

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage()
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('pageerror', (error) => consoleErrors.push(`pageerror: ${error.message}`))
  page.on('response', (response) => {
    const line = `${response.status()} ${response.request().method()} ${new URL(response.url()).pathname}`
    if (response.status() >= 500) serverErrors.push(line)
    else if (response.status() >= 400) clientErrors.push(line)
  })
})

test.afterAll(async () => {
  await page.close()
})

test('a visitor is sent to sign in, and the skip link is the first stop', async () => {
  await page.goto('/rewrites')
  await expect(h1('Sign in')).toBeVisible()
  await expect(page).toHaveURL(/\/login$/)
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to main content' })).toBeFocused()
})

test('register, sign out and sign back in', async () => {
  await page.getByRole('tab', { name: 'Create account' }).click()
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Create account', exact: true }).click()
  // The visitor asked for /rewrites before signing in, so that is where they land.
  await expect(h1('Saved rewrites')).toBeVisible()

  await nav('Account').click()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(h1('Sign in')).toBeVisible()
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(h1('Dashboard')).toBeVisible()
  await expect(page.getByText('No resumes yet. Upload one to see its analysis.')).toBeVisible()
})

test('upload a resume and land on its analysis', async () => {
  await nav('Upload').click()
  await expect(h1('Upload a resume')).toBeFocused()
  await page.getByTestId('dropzone').locator('input[type="file"]').setInputFiles(RESUME)
  await page.getByRole('button', { name: 'Upload and analyse' }).click()
  await expect(h1('Resume analysis')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('Resume uploaded and analysed.')).toBeVisible()
  await expect(page.getByRole('img', { name: /^Resume quality: \d+ out of 100$/ })).toBeVisible()
  await expect(page.getByText(/ATS compatibility estimate/).first()).toBeVisible()
  await expect(page.getByRole('note').filter({ hasText: 'applicant tracking' })).toBeVisible()
  ids.resume = lastSegment()
})

test('match the resume against a pasted job description', async () => {
  await page.locator('.page-actions').getByRole('link', { name: 'Match against a job' }).click()
  await expect(page).toHaveURL(new RegExp(`/match\\?resume=${ids.resume}$`))
  await page.getByLabel('Job description text').fill(JOB_TEXT)
  await page.getByRole('button', { name: 'Analyse job description' }).click()
  await expect(page.getByRole('heading', { name: 'Senior Backend Engineer' })).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: '3. Run match' }).click()
  await expect(h1('Job match report')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('img', { name: /^Job match: \d+%$/ })).toBeVisible()
  ids.match = lastSegment()
  const jobHref = await page.getByRole('link', { name: 'Senior Backend Engineer' }).getAttribute('href')
  ids.job = jobHref?.split('/').pop() ?? ''
  expect(ids.job).not.toBe('')
})

test('generate a rewrite for this job (fake AI)', async () => {
  await page.locator('.page-actions').getByRole('link', { name: 'Rewrite for this job' }).click()
  await expect(h1('Rewrite your resume')).toBeVisible()
  await expect(page.getByLabel('Writing style')).toHaveValue('job_targeted')
  await page.getByRole('button', { name: '4. Rewrite my resume' }).click()
  await expect(page.getByLabel('Rewrite name')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTitle('Resume preview')).toBeVisible()
  ids.rewrite = lastSegment()
  expect(await page.locator('article.suggestion').count()).toBeGreaterThan(0)
})

test('reject and accept suggestions; blocked ones cannot be accepted', async () => {
  const before = await currentVersion()
  await page.locator('article.suggestion').getByRole('button', { name: 'Reject' }).first().click()
  await waitForVersion(before + 1)
  await page.locator('article.suggestion.is-rejected').getByRole('button', { name: 'Accept' }).first().click()
  await waitForVersion(before + 2)
  const blocked = page.locator('article.suggestion.is-blocked')
  for (let i = 0; i < (await blocked.count()); i++) {
    await expect(blocked.nth(i).getByRole('button', { name: 'Accept' })).toHaveCount(0)
  }
})

test('an unverifiable edit blocks downloads until acknowledged; PDF and DOCX download', async () => {
  const summary = page.getByRole('region', { name: 'Professional summary' })
  await summary.getByRole('button', { name: 'Edit' }).click()
  await summary
    .getByLabel('Summary')
    .fill('Backend engineer certified in Terraform with 6 years of experience building Python APIs.')
  await summary.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByText('Saved as a new version.')).toBeVisible()
  await expect(page.getByText(/could not be verified against your original resume/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Download DOCX' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Download PDF' })).toBeDisabled()

  await page.getByRole('checkbox', { name: /confirm they are accurate/ }).check()
  await download('DOCX')
  await download('PDF')
})

test('preview every template', async () => {
  const names = ['Modern professional', 'Minimalist', 'Traditional corporate', 'Technical', 'Graduate']
  for (const name of names) {
    const radio = page.getByRole('group', { name: 'Template' }).getByRole('radio', { name: new RegExp(name) })
    await settledClick(page.locator('.template-option', { hasText: name }))
    await expect(radio).toBeChecked()
    await expect(page.locator('.template-choice input:disabled')).toHaveCount(0)
    await expect(page.getByTitle('Resume preview')).toBeVisible()
  }
})

test('view and restore version 1', async () => {
  const before = await currentVersion()
  await expect(page.locator('.version-row:disabled')).toHaveCount(0)
  await settledClick(page.locator('.version-row', { hasText: 'v1 ·' }))
  await expect(page.getByText(/Viewing version 1 \(read-only\)/)).toBeVisible()
  await settledClick(page.getByRole('button', { name: 'Restore this version' }))
  await expect(page.getByText('Version 1 restored as a new version.')).toBeVisible()
  await waitForVersion(before + 1)
})

test('deep links survive a reload', async () => {
  await page.reload()
  await expect(page.getByLabel('Rewrite name')).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`/rewrites/${ids.rewrite}$`))
})

test('the dashboard shows the real activity', async () => {
  await nav('Dashboard').click()
  await expect(h1('Dashboard')).toBeFocused()
  await expect(
    page.getByRole('region', { name: 'Resumes' }).getByRole('link', { name: 'jane-doe-resume.md' }),
  ).toBeVisible()
  await expect(
    page.getByRole('region', { name: 'Recent job matches' }).getByRole('link', { name: 'Senior Backend Engineer' }),
  ).toBeVisible()
  await expect(
    page
      .getByRole('region', { name: 'Recent rewrites' })
      .getByRole('link', { name: /jane-doe-resume – Senior Backend Engineer/ }),
  ).toBeVisible()
})

test('deleting the target job keeps the rewrite but detaches it (dialog: Escape cancels)', async () => {
  await page.goto(`/jobs/${ids.job}`)
  await expect(page.getByRole('heading', { level: 2, name: 'Senior Backend Engineer' })).toBeVisible()
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()

  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Delete job description' }).click()
  await expect(h1('Saved matches and jobs')).toBeVisible()
  await expect(page.getByText('No saved job descriptions yet.')).toBeVisible()

  await page.goto(`/rewrites/${ids.rewrite}`)
  await expect(page.getByText(/The job this rewrite targeted was deleted/)).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Job match', exact: true })).toHaveCount(0)
})

test('layouts at 390px and 768px have no horizontal scroll', async () => {
  for (const width of [390, 768]) {
    await page.setViewportSize({ width, height: 900 })
    for (const url of ['/', `/rewrites/${ids.rewrite}`, `/resumes/${ids.resume}`, '/upload']) {
      await page.goto(url)
      await expect(page.locator('main h1')).toBeVisible()
      await noHorizontalScroll()
    }
  }
  await page.setViewportSize({ width: 1360, height: 900 })
})

test('unknown pages and missing resources are handled', async () => {
  await page.goto('/definitely/not/here')
  await expect(h1('Page not found')).toBeVisible()
  await page.goto(`/matches/${ids.match}`)
  // The match was deleted together with its job.
  await expect(page.getByText('This match report could not be found.')).toBeVisible()
})

test('delete the account', async () => {
  await page.goto('/account')
  await page.getByLabel('Current password').fill(PASSWORD)
  await page.getByLabel(/to confirm/).fill('delete my account')
  await page.getByRole('button', { name: 'Delete my account' }).click()
  await expect(page.getByText('Your account and all of its data have been deleted.')).toBeVisible()
  await expect(h1('Sign in')).toBeVisible()
})

test('no JavaScript errors, no server errors and only the expected 4xx responses', async () => {
  // Chrome logs every 4xx/5xx response as a console error; those are checked precisely through the response log.
  const jsErrors = consoleErrors.filter(
    (text) => !/^Failed to load resource: the server responded with a status of [45]\d\d/.test(text),
  )
  expect(jsErrors, jsErrors.join('\n')).toEqual([])
  expect(serverErrors, serverErrors.join('\n')).toEqual([])
  // The anonymous session check before sign-in, and the deliberately opened deleted match report.
  // (Each may appear twice: React StrictMode runs effects twice in development.)
  expect(new Set(clientErrors)).toEqual(new Set(['401 GET /api/v1/auth/me', `404 GET /api/v1/matches/${ids.match}`]))
})
