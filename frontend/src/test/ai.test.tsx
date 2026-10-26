import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AiExplanationPanel } from '../features/ai/AiExplanationPanel'
import { AiStatusCard } from '../features/ai/AiStatusCard'
import { DocumentAssistPanel } from '../features/ai/DocumentAssistPanel'
import { AuthProvider } from '../features/auth/AuthProvider'
import type { AiDocumentAssist, AiEgressManifest, AiExplanation, AiInteraction, AiProviderState, AiStatement } from '../lib/types'
import { aiProviderOff, aiStatusDisabled, json, makeMe, mockApi } from './fixtures'

const providerOn = (): AiProviderState => ({
  ...aiProviderOff(),
  name: 'anthropic',
  configured_name: 'anthropic',
  enabled: true,
  configured: true,
  model: 'claude-opus-5-5',
  detail: 'Claude (claude-opus-5-5) via the Anthropic SDK 1.17.0',
  health: { ...aiProviderOff().health, state: 'healthy', calls: 3 },
})

const egress = (over: Partial<AiEgressManifest> = {}): AiEgressManifest => ({
  policy: 'none', categories: ['rule_metadata'], documents: [], pages: [], masked_values: 0, withheld: ['extracted_values', 'document_names'],
  truncated: false, chars_sent: 1800, injection_signals: [], ...over,
})

const fallbackStatements: AiStatement[] = [
  {
    text: 'Rule “Applicant is an adult” (version 1) returned “fail” with high severity on 2026-10-23: the rule’s condition did not hold.',
    references: [
      { id: 'rule_result:' + 'a'.repeat(32), kind: 'rule_result', label: 'Result of “Applicant is an adult” in validation run', link: { type: 'rule_result', application_id: 'app1', run_id: 'run1' } },
      { id: 'rule_version:' + 'b'.repeat(32), kind: 'rule_version', label: '“Applicant is an adult” version 1', link: { type: 'rule_version', rule_id: 'rule1', version_id: 'v1' } },
    ],
  },
  {
    text: 'Date of birth on minor.pdf, page 1 was “2015-01-01”; evidence quality high.',
    references: [{ id: 'field:' + 'c'.repeat(32), kind: 'field', label: 'Date of birth — minor.pdf', link: { type: 'field', application_id: 'app1', document_id: 'doc2', page_number: 1, field_key: 'date_of_birth' } }],
  },
]

function interaction<O>(output: O | null, over: Partial<AiInteraction<O>> = {}): AiInteraction<O> {
  return {
    interaction_id: 'i1', status: 'succeeded', error: null, output, validation: {}, provider: 'anthropic', model: 'claude-opus-5-5',
    prompt_version: '2026-10-assist-1', created_at: '2026-10-23T10:00:00Z', created_by: { id: 'u1', full_name: 'Ada Example' },
    cached: false, stale: false, egress: egress(), usage: { input_tokens: 1200, output_tokens: 300, cost_usd: 0.0108, attempts: 1, duration_ms: 900 },
    ...over,
  }
}

function explanation(over: Partial<AiExplanation> = {}): AiExplanation {
  return {
    subject: { type: 'review_item', id: 'item1', application_id: 'app1', application_reference: 'APP-2026-AAA111' },
    deterministic: {
      kind: 'rule_result', outcome: 'fail', severity: 'high', reason: 'condition_not_met', message: '',
      rule: { rule_id: 'rule1', key: 'adult_applicant', name: 'Applicant is an adult', version_id: 'v1', version_number: 1, source_reference: 'Synthetic SYN-1' },
    },
    fallback: { statements: fallbackStatements },
    ai: null,
    error: null,
    provider: aiProviderOff(),
    can_request: false,
    limitations: ['AI output is advisory. The deterministic result shown with it is the one VerifyFlow uses; AI never changes it.'],
    ...over,
  }
}

type Routes = Record<string, (body: unknown) => Response>

function setup(routes: Routes, role: 'reviewer' | 'admin' | 'auditor' = 'reviewer') {
  const calls: { key: string; body: unknown }[] = []
  mockApi({
    me: makeMe(role),
    handlers: [
      (url, init) => {
        const path = url.replace(/^.*\/api\/v1/, '').split('?')[0]
        const key = `${(init.method ?? 'GET').toUpperCase()} ${path}`
        const body = init.body ? JSON.parse(String(init.body)) : undefined
        calls.push({ key, body })
        return routes[key]?.(body)
      },
    ],
  })
  return calls
}

function renderWith(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>{ui}</AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AI explanation panel', () => {
  it('shows the authoritative result and the deterministic explanation when AI is off', async () => {
    const calls = setup({ 'GET /ai/explanations': () => json(200, explanation()) })
    renderWith(<AiExplanationPanel subjectType="review_item" subjectId="item1" />)

    expect(await screen.findByText(/Result · authoritative/i)).toBeInTheDocument()
    expect(screen.getByText(/AI never changes this result/)).toBeInTheDocument()
    expect(screen.getByText('AI off')).toBeInTheDocument()
    const list = screen.getByRole('list', { name: 'Deterministic explanation' })
    expect(within(list).getByText(/returned “fail”/)).toBeInTheDocument()
    expect(within(list).getByRole('link', { name: /Extracted field: Date of birth — minor.pdf/ })).toHaveAttribute(
      'href',
      '/applications/app1/documents/doc2?page=1&field=date_of_birth',
    )
    expect(within(list).getByRole('link', { name: /Rule version/ })).toHaveAttribute('href', '/compliance/rules/rule1')
    expect(screen.queryByRole('button', { name: /Explain with AI/ })).not.toBeInTheDocument()
    expect(calls.some((c) => c.key === 'POST /ai/explanations')).toBe(false)
  })

  it('requests an explanation and shows verified statements, filtering notes and the egress manifest', async () => {
    const ai = interaction(
      {
        statements: [{ text: 'The adult-applicant rule failed because one document gives a date of birth in 2015.', references: fallbackStatements[1].references }],
        limitations: ['Values come from a baseline extractor.'],
      },
      {
        status: 'partial',
        validation: {
          dropped_statements: [{ index: 1, reasons: ['unverified_reference'] }, { index: 2, reasons: ['authenticity_claim', 'decision_claim'] }],
          rejected_references: [{ ref: 'field:' + 'd'.repeat(32), reason: 'not_found' }],
          dropped_limitations: 0,
        },
        egress: egress({ injection_signals: [{ where: 'page 1', signals: ['ignore_instructions', 'verdict_injection'] }] }),
      },
    )
    const calls = setup({
      'GET /ai/explanations': () => json(200, explanation({ provider: providerOn(), can_request: true })),
      'POST /ai/explanations': () => json(200, explanation({ provider: providerOn(), can_request: true, ai })),
    })
    const user = userEvent.setup()
    renderWith(<AiExplanationPanel subjectType="review_item" subjectId="item1" />)

    await user.click(await screen.findByRole('button', { name: /Explain with AI/ }))
    const statements = await screen.findByRole('list', { name: 'AI explanation statements' })
    expect(within(statements).getByText(/date of birth in 2015/)).toBeInTheDocument()
    expect(within(statements).getByRole('link', { name: /Date of birth — minor.pdf/ })).toHaveAttribute('href', '/applications/app1/documents/doc2?page=1&field=date_of_birth')
    expect(screen.getByText('Partly filtered')).toBeInTheDocument()
    expect(screen.getByText(/Removed 2 statements that cited a record that could not be verified; made an authenticity claim; made an approval or rejection claim/)).toBeInTheDocument()
    expect(screen.getByText(/Citations rejected: 1 no such record/)).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent(/asks to ignore instructions/)
    expect(screen.getByText('What was sent to the AI provider')).toBeInTheDocument()
    expect(screen.getByText(/claude-opus-5-5 · requested by Ada Example/)).toBeInTheDocument()
    // The deterministic result stays on screen alongside the AI text.
    expect(screen.getByText(/Result · authoritative/i)).toBeInTheDocument()
    expect(calls.find((c) => c.key === 'POST /ai/explanations')?.body).toEqual({ subject_type: 'review_item', subject_id: 'item1', refresh: false })

    await user.click(screen.getByRole('button', { name: /Regenerate/ }))
    await vi.waitFor(() => expect(calls.filter((c) => c.key === 'POST /ai/explanations').at(-1)?.body).toMatchObject({ refresh: true }))
  })

  it('falls back to the deterministic explanation when the AI request fails', async () => {
    const failed = interaction<never>(null, { status: 'failed', error: { code: 'ai_timeout', message: 'The AI provider did not respond in time.' } })
    setup({ 'GET /ai/explanations': () => json(200, explanation({ provider: providerOn(), can_request: true, ai: failed })) })
    renderWith(<AiExplanationPanel subjectType="review_item" subjectId="item1" />)

    expect(await screen.findByText(/did not respond in time/)).toBeInTheDocument()
    expect(screen.getByText('ai_timeout')).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Deterministic explanation' })).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'AI explanation statements' })).not.toBeInTheDocument()
  })
})

function assist(over: Partial<AiDocumentAssist> = {}): AiDocumentAssist {
  return {
    application_id: 'app1', document_id: 'doc1', document_name: 'adult.pdf',
    fallback: { document_type: null, document_type_source: null, fields: 'Extracted values from the deterministic extractor are in the Extraction Inspector.' },
    provider: providerOn(), can_request: true, egress_allows_page_text: true, tasks: [],
    limitations: ['Suggestions are never applied automatically.'],
    classification: null, classification_error: null, field_suggestions: null, field_suggestions_error: null,
    ...over,
  }
}

describe('Document AI suggestions', () => {
  it('explains that the egress policy blocks page-text tasks and offers no request', async () => {
    setup({ 'GET /ai/applications/app1/documents/doc1': () => json(200, assist({ egress_allows_page_text: false })) })
    renderWith(<DocumentAssistPanel applicationId="app1" documentId="doc1" />)
    expect(await screen.findByText(/data-egress policy doesn’t allow that/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Ask AI/ })).not.toBeInTheDocument()
  })

  it('shows grounded field suggestions without applying them', async () => {
    const suggestions = interaction(
      {
        suggestions: [
          {
            field_key: 'date_of_birth', label: 'Date of birth', value: '03 March 1990', normalized_value: '1990-03-03', normalization_status: 'ok',
            normalization_note: null, page_number: 1, quoted_text: 'Date of birth: 03 March 1990', comparison: 'differs_from_extraction' as const,
            current_value: '1990-03-30', current_field_id: 'f1',
            link: { type: 'field' as const, application_id: 'app1', document_id: 'doc1', page_number: 1, field_key: 'date_of_birth' },
          },
        ],
      },
      { status: 'partial', validation: { dropped_suggestions: [{ reason: 'quote_not_found' }] }, egress: egress({ policy: 'page_text', categories: ['page_text'] }) },
    )
    const calls = setup({
      'GET /ai/applications/app1/documents/doc1': () => json(200, assist()),
      'POST /ai/applications/app1/documents/doc1/field-suggestions': () => json(200, assist({ field_suggestions: suggestions })),
    })
    const onShow = vi.fn()
    const user = userEvent.setup()
    renderWith(<DocumentAssistPanel applicationId="app1" documentId="doc1" onShowField={onShow} />)

    const section = await screen.findByRole('region', { name: 'Field suggestions' })
    await user.click(within(section).getByRole('button', { name: 'Ask AI' }))
    expect(await within(section).findByText('Differs from extraction')).toBeInTheDocument()
    expect(within(section).getByText(/Quoted from page 1: “Date of birth: 03 March 1990”/)).toBeInTheDocument()
    expect(within(section).getByText(/Removed 1 suggestion that quoted text that is not on the cited page/)).toBeInTheDocument()
    await user.click(within(section).getByRole('button', { name: 'Show field and page' }))
    expect(onShow).toHaveBeenCalledWith('date_of_birth', 1)
    // Nothing writes to extracted fields: the only write is the suggestion request itself.
    expect(calls.filter((c) => c.key.startsWith('POST')).map((c) => c.key)).toEqual(['POST /ai/applications/app1/documents/doc1/field-suggestions'])
  })
})

describe('AI status card', () => {
  it('reports AI off without offering a connection check', async () => {
    setup({}, 'admin')
    renderWith(<AiStatusCard />)
    expect(await screen.findByText('AI off')).toBeInTheDocument()
    expect(screen.getByText(/\$0.0000 of \$5.00 spent/)).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'AI tasks' })).toHaveTextContent(/Plain-language explanations of findings/)
    expect(screen.queryByRole('button', { name: 'Check connection' })).not.toBeInTheDocument()
  })

  it('lets an administrator check the provider connection', async () => {
    const status = { ...aiStatusDisabled(), provider: providerOn() }
    setup(
      {
        'GET /ai/status': () => json(200, status),
        'POST /ai/status/check': () => json(200, { ok: true, detail: 'Reachable; model claude-opus-5-5 is available', error_code: null, provider: providerOn() }),
      },
      'admin',
    )
    const user = userEvent.setup()
    renderWith(<AiStatusCard />)
    await user.click(await screen.findByRole('button', { name: 'Check connection' }))
    expect(await screen.findByText(/Reachable; model claude-opus-5-5 is available/)).toBeInTheDocument()
  })
})
