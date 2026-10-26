import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import App from '../App'
import { Button } from '../components/ui/Button'
import { Dialog } from '../components/ui/Dialog'
import { Tooltip } from '../components/ui/Tooltip'
import { AuthProvider } from '../features/auth/AuthProvider'
import { makeMe, mockApi } from './fixtures'

function renderApp(path = '/') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Disabled actions explain themselves', () => {
  it('keeps an explained disabled button focusable, described and inert to clicks', async () => {
    const onClick = vi.fn()
    const user = userEvent.setup()
    render(
      <Button disabled disabledReason="There are no unsaved changes." onClick={onClick}>
        Save draft
      </Button>,
    )
    const button = screen.getByRole('button', { name: 'Save draft' })
    expect(button).not.toBeDisabled()
    expect(button).toHaveAttribute('aria-disabled', 'true')
    expect(button).toHaveAccessibleDescription('There are no unsaved changes.')
    await user.tab()
    expect(button).toHaveFocus()
    expect(await screen.findByRole('tooltip', { hidden: true })).toHaveTextContent('There are no unsaved changes.')
    await user.click(button)
    await user.keyboard('{Enter}')
    expect(onClick).not.toHaveBeenCalled()
  })

  it('still uses native disabled when no reason is given (e.g. obvious pagination ends)', () => {
    render(<Button disabled>Previous</Button>)
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
  })

  it('closes a tooltip with Escape and on blur', async () => {
    const user = userEvent.setup()
    render(
      <Tooltip content="Explains the control">
        <button type="button">Control</button>
      </Tooltip>,
    )
    await user.tab()
    expect(await screen.findByRole('tooltip', { hidden: true })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('tooltip', { hidden: true })).not.toBeInTheDocument())
  })
})

describe('Dialogs', () => {
  function Harness({ removeTrigger = false }: { removeTrigger?: boolean }) {
    const [open, setOpen] = useState(false)
    const [gone, setGone] = useState(false)
    return (
      <>
        <main id="main" tabIndex={-1}>
          {!gone && (
            <button type="button" onClick={() => setOpen(true)}>
              Open dialog
            </button>
          )}
        </main>
        <Dialog
          open={open}
          onClose={() => {
            if (removeTrigger) setGone(true)
            setOpen(false)
          }}
          title="Confirm finding"
        >
          <label>
            Reason <input />
          </label>
          <button type="button">Confirm</button>
        </Dialog>
      </>
    )
  }

  it('traps focus, closes on Escape and restores focus to the trigger', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const trigger = screen.getByRole('button', { name: 'Open dialog' })
    await user.click(trigger)
    const dialog = await screen.findByRole('dialog', { name: 'Confirm finding' })
    expect(within(dialog).getByRole('textbox')).toHaveFocus()
    await user.tab()
    await user.tab()
    await user.tab() // past the last control: wraps to the first
    expect(dialog.contains(document.activeElement)).toBe(true)
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
  })

  it('moves focus to the main content when the trigger no longer exists', async () => {
    const user = userEvent.setup()
    render(<Harness removeTrigger />)
    await user.click(screen.getByRole('button', { name: 'Open dialog' }))
    await screen.findByRole('dialog')
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(document.getElementById('main')).toHaveFocus()
  })
})

describe('Shell keyboard support', () => {
  it('traps focus in the mobile navigation drawer, makes the page inert, and restores focus on Escape', async () => {
    mockApi({ me: makeMe('reviewer') })
    const user = userEvent.setup()
    renderApp('/')
    const open = await screen.findByRole('button', { name: 'Open navigation' })
    await user.click(open)
    const drawer = await screen.findByRole('dialog', { name: 'Navigation' })
    expect(drawer.contains(document.activeElement)).toBe(true)
    expect(open.closest('[inert]')).not.toBeNull()
    for (let i = 0; i < 12; i++) await user.tab()
    expect(drawer.contains(document.activeElement)).toBe(true)
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Navigation' })).not.toBeInTheDocument())
    expect(open.closest('[inert]')).toBeNull()
    expect(open).toHaveFocus()
  })

  it('opens the account menu from the keyboard and moves between items with arrows', async () => {
    mockApi({ me: makeMe('reviewer') })
    const user = userEvent.setup()
    renderApp('/')
    const trigger = await screen.findByRole('button', { name: /Account menu for/ })
    act(() => trigger.focus())
    await user.keyboard('{ArrowDown}')
    const items = await screen.findAllByRole('menuitem')
    await waitFor(() => expect(items[0]).toHaveFocus())
    await user.keyboard('{ArrowDown}')
    expect(items[1]).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(items[0]).toHaveFocus()
    await user.keyboard('{End}')
    expect(items[items.length - 1]).toHaveFocus()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
  })

  it('names every governance tab in the breadcrumb trail', async () => {
    mockApi({ me: makeMe('auditor') })
    renderApp('/governance?tab=exports')
    const crumbs = await screen.findByRole('navigation', { name: 'Breadcrumb' })
    expect(await within(crumbs).findByText('Exports')).toHaveAttribute('aria-current', 'page')
  })
})
