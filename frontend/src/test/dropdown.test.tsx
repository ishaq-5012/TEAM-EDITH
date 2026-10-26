import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { describe, expect, it, vi } from 'vitest'
import { Select, SelectField } from '../components/ui/Field'
import { chooseOption, optionNames } from './fixtures'

function Controlled({ onPick = () => {} }: { onPick?: (v: string) => void }) {
  const [v, setV] = useState('b')
  return (
    <label>
      Colour
      <Select
        value={v}
        onChange={(e) => {
          setV(e.target.value)
          onPick(e.target.value)
        }}
      >
        <option value="a">Alpha</option>
        <option value="b">Bravo</option>
        <option value="c" disabled>
          Charlie (unavailable)
        </option>
        <option value="d">Delta</option>
      </Select>
    </label>
  )
}

describe('Dropdown', () => {
  it('shows the selected option, is named by its label, and picks with the mouse', async () => {
    const onPick = vi.fn()
    render(<Controlled onPick={onPick} />)
    const trigger = screen.getByRole('combobox', { name: 'Colour' })
    expect(trigger).toHaveTextContent('Bravo')
    await chooseOption(trigger, 'Delta')
    expect(onPick).toHaveBeenCalledWith('d')
    expect(trigger).toHaveTextContent('Delta')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('works from the keyboard: open, move past a disabled option, choose, Escape returns focus', async () => {
    const onPick = vi.fn()
    const user = userEvent.setup()
    render(<Controlled onPick={onPick} />)
    const trigger = screen.getByRole('combobox')
    trigger.focus()
    await user.keyboard('{ArrowDown}')
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('option', { name: 'Bravo' })).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{ArrowDown}') // skips the disabled "Charlie"
    await user.keyboard('{Enter}')
    expect(onPick).toHaveBeenCalledWith('d')
    expect(trigger).toHaveFocus()

    await user.keyboard('{Enter}')
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
    expect(onPick).toHaveBeenCalledTimes(1)
  })

  it('supports type-ahead, Home and End', async () => {
    const user = userEvent.setup()
    render(<Controlled />)
    screen.getByRole('combobox').focus()
    await user.keyboard('{Enter}')
    await user.keyboard('a')
    await user.keyboard('{Enter}')
    expect(screen.getByRole('combobox')).toHaveTextContent('Alpha')
    await user.keyboard('{Enter}{End}{Enter}')
    expect(screen.getByRole('combobox')).toHaveTextContent('Delta')
    await user.keyboard('{Enter}{Home}{Enter}')
    expect(screen.getByRole('combobox')).toHaveTextContent('Alpha')
  })

  it('does not select a disabled option and closes on an outside click', async () => {
    const onPick = vi.fn()
    const user = userEvent.setup()
    render(
      <>
        <Controlled onPick={onPick} />
        <button>elsewhere</button>
      </>,
    )
    await user.click(screen.getByRole('combobox'))
    await user.click(screen.getByRole('option', { name: /Charlie/ }))
    expect(onPick).not.toHaveBeenCalled()
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'elsewhere' }))
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('renders option groups with headings', async () => {
    const user = userEvent.setup()
    render(
      <Select aria-label="Action" defaultValue="">
        <option value="">All</option>
        <optgroup label="Groups">
          <option value="g1">Group one</option>
        </optgroup>
        <optgroup label="Actions">
          <option value="a1">Action one</option>
        </optgroup>
      </Select>,
    )
    await user.click(screen.getByRole('combobox', { name: 'Action' }))
    expect(optionNames()).toEqual(['All', 'Group one', 'Action one'])
    expect(screen.getByText('Groups')).toBeInTheDocument()
    expect(screen.getByText('Actions')).toBeInTheDocument()
  })

  it('stays a real form field: react-hook-form register reads defaults and changes', async () => {
    const seen: string[] = []
    function Form() {
      const { register, handleSubmit } = useForm<{ role: string }>({ defaultValues: { role: 'reviewer' } })
      return (
        <form onSubmit={handleSubmit((v) => seen.push(v.role))}>
          <SelectField label="Role" {...register('role')}>
            <option value="admin">Administrator</option>
            <option value="reviewer">Reviewer</option>
            <option value="auditor">Auditor</option>
          </SelectField>
          <button type="submit">Save</button>
        </form>
      )
    }
    const user = userEvent.setup()
    render(<Form />)
    const trigger = screen.getByRole('combobox', { name: 'Role' })
    await waitFor(() => expect(trigger).toHaveTextContent('Reviewer'))
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(seen).toEqual(['reviewer']))
    await chooseOption(trigger, 'Auditor')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(seen).toEqual(['reviewer', 'auditor']))
  })

  it('does nothing when disabled', async () => {
    const user = userEvent.setup()
    render(
      <Select aria-label="Locked" disabled defaultValue="a">
        <option value="a">Alpha</option>
      </Select>,
    )
    await user.click(screen.getByRole('combobox', { name: 'Locked' }))
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })
})
