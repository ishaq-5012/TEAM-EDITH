import { Brackets, ListPlus, Plus, Trash2 } from 'lucide-react'
import { useEffect, useId, useState } from 'react'
import { cn } from '../../components/ui/cn'
import type { CatalogField, ConditionNode, LeafNode, LeafValue, RuleCatalog } from '../../lib/types'
import { defaultValue, fieldOf, groupKind, newLeaf, OP_LABEL, shapeOf } from './ruleMeta'
import { Tooltip } from '../../components/ui/Tooltip'
import { controlClass } from '../../components/ui/controlClass'
import { Select } from '../../components/ui/Field'

// Dense inline editor controls: shared look, natural width.
const input = controlClass({ size: 'sm', full: false })

const SOURCE_LABEL: Record<CatalogField['source'], string> = {
  extracted: 'Extracted document fields',
  evidence: 'Cross-document evidence',
  application: 'Application',
}
const OUTCOME_VALUES = ['pass', 'fail', 'review', 'insufficient']

interface Props {
  node: ConditionNode
  catalog: RuleCatalog
  onChange: (next: ConditionNode) => void
  onRemove?: () => void
  readOnly?: boolean
  depth?: number
  /** Accessible name prefix, e.g. "Condition" or "Applies when". */
  label: string
}

/**
 * Structured editor for the declarative condition tree. It can only produce allowlisted
 * operators from the server catalog; there is no free-form expression input anywhere.
 */
export function ConditionBuilder({ node, catalog, onChange, onRemove, readOnly, depth = 0, label }: Props) {
  const kind = groupKind(node)
  if (kind === 'leaf') {
    return (
      <LeafEditor
        leaf={node as LeafNode}
        catalog={catalog}
        onChange={onChange}
        onRemove={onRemove}
        onWrap={depth < 5 ? () => onChange({ all: [node] }) : undefined}
        readOnly={readOnly}
        label={label}
      />
    )
  }
  const children: ConditionNode[] = kind === 'not' ? [(node as { not: ConditionNode }).not] : (node as Record<'all' | 'any', ConditionNode[]>)[kind as 'all' | 'any']
  const setKind = (k: 'all' | 'any' | 'not') => {
    if (k === kind) return
    if (k === 'not') onChange({ not: children.length === 1 ? children[0] : { [kind]: children } as ConditionNode })
    else onChange({ [k]: children } as ConditionNode)
  }
  const setChild = (i: number, c: ConditionNode) => {
    if (kind === 'not') onChange({ not: c })
    else onChange({ [kind]: children.map((x, j) => (j === i ? c : x)) } as ConditionNode)
  }
  const removeChild = (i: number) => {
    const rest = children.filter((_, j) => j !== i)
    // A group with a single child collapses to that child, keeping the tree minimal and readable.
    if (rest.length === 1 && kind !== 'not') onChange(rest[0])
    else onChange({ [kind]: rest } as ConditionNode)
  }
  const add = (c: ConditionNode) => onChange({ [kind]: [...children, c] } as ConditionNode)

  return (
    <fieldset
      className={cn(
        'rounded-xl border p-3',
        depth % 2 === 0 ? 'border-violet-200 bg-violet-50/40' : 'border-line bg-surface',
      )}
    >
      <legend className="sr-only">{`${label} group`}</legend>
      <div className="mb-2.5 flex flex-wrap items-center gap-2">
        <div role="radiogroup" aria-label={`${label}: how to combine`} className="inline-flex rounded-lg border border-line-strong bg-surface p-0.5">
          {(['all', 'any', 'not'] as const).map((k) => {
            // A blocked NOT stays focusable and says why; read-only editors disable everything (stated by the page).
            const blocked = !readOnly && k === 'not' && children.length > 1
            const button = (
              <button
                key={k}
                type="button"
                role="radio"
                aria-checked={kind === k}
                disabled={readOnly}
                aria-disabled={blocked || undefined}
                onClick={() => !blocked && setKind(k)}
                className={cn(
                  'rounded-md px-2.5 py-1 text-[12px] font-semibold uppercase tracking-wide transition-colors disabled:cursor-not-allowed aria-disabled:cursor-not-allowed',
                  kind === k ? 'bg-violet-600 text-white' : 'text-ink-muted hover:text-ink disabled:opacity-50 aria-disabled:opacity-50 aria-disabled:hover:text-ink-muted',
                )}
              >
                {k === 'all' ? 'All of' : k === 'any' ? 'Any of' : 'Not'}
              </button>
            )
            return blocked ? (
              <Tooltip key={k} content="NOT applies to a single condition. Remove the other conditions first.">
                {button}
              </Tooltip>
            ) : (
              button
            )
          })}
        </div>
        <span className="text-[12px] text-ink-subtle">
          {kind === 'all' ? 'every condition must hold' : kind === 'any' ? 'at least one condition must hold' : 'the condition must not hold'}
        </span>
        {!readOnly && onRemove && (
          <button type="button" onClick={onRemove} className="ml-auto rounded-md p-1 text-ink-subtle hover:bg-fail-bg hover:text-fail" aria-label={`Remove ${label} group`}>
            <Trash2 className="size-3.5" aria-hidden />
          </button>
        )}
      </div>
      <ol className="space-y-2">
        {children.map((c, i) => (
          <li key={i}>
            <ConditionBuilder
              node={c}
              catalog={catalog}
              onChange={(n) => setChild(i, n)}
              onRemove={children.length > 1 || kind === 'not' ? () => (kind === 'not' ? onChange(c) : removeChild(i)) : undefined}
              readOnly={readOnly}
              depth={depth + 1}
              label={`${label} ${i + 1}`}
            />
          </li>
        ))}
      </ol>
      {!readOnly && kind !== 'not' && (
        <div className="mt-2.5 flex flex-wrap gap-2">
          <button type="button" onClick={() => add(newLeaf(catalog))} className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[12.5px] font-medium text-violet-700 hover:bg-violet-50">
            <Plus className="size-3.5" aria-hidden /> Add condition
          </button>
          {depth < 4 && (
            <button
              type="button"
              onClick={() => add({ any: [newLeaf(catalog), newLeaf(catalog)] })}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[12.5px] font-medium text-violet-700 hover:bg-violet-50"
            >
              <ListPlus className="size-3.5" aria-hidden /> Add group
            </button>
          )}
        </div>
      )}
    </fieldset>
  )
}

function LeafEditor({
  leaf,
  catalog,
  onChange,
  onRemove,
  onWrap,
  readOnly,
  label,
}: {
  leaf: LeafNode
  catalog: RuleCatalog
  onChange: (n: LeafNode) => void
  onRemove?: () => void
  onWrap?: () => void
  readOnly?: boolean
  label: string
}) {
  const field = fieldOf(catalog, leaf.field)
  const ops = field ? Object.keys(catalog.operators[field.type]) : []
  const shape = shapeOf(catalog, leaf)
  const groups = (['extracted', 'evidence', 'application'] as const).map((s) => [s, catalog.fields.filter((f) => f.source === s)] as const)

  const setField = (ref: string) => {
    const f = fieldOf(catalog, ref)
    if (!f) return
    // Keep the operator when the new field's type allows it; otherwise pick its first operator.
    const op = catalog.operators[f.type][leaf.op] ? leaf.op : Object.keys(catalog.operators[f.type])[0]
    const keepValue = f.type === field?.type && op === leaf.op
    const next: LeafNode = { field: ref, op }
    const v = keepValue ? leaf.value : defaultValue(catalog.operators[f.type][op], f.type)
    if (v !== undefined) next.value = v
    if (f.source === 'extracted' && leaf.quantifier) next.quantifier = leaf.quantifier
    onChange(next)
  }
  const setOp = (op: string) => {
    const next: LeafNode = { field: leaf.field, op }
    const newShape = field ? catalog.operators[field.type][op] : undefined
    const v = newShape === shape ? leaf.value : defaultValue(newShape, field?.type)
    if (v !== undefined) next.value = v
    if (leaf.quantifier) next.quantifier = leaf.quantifier
    onChange(next)
  }
  const setValue = (value: LeafValue | undefined) => {
    const next = { ...leaf }
    if (value === undefined) delete next.value
    else next.value = value
    onChange(next)
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-surface p-2.5 shadow-[var(--shadow-card)]">
      <Select aria-label={`${label}: field`} size="sm" full={false} className="min-w-44 max-w-full" value={leaf.field} onChange={(e) => setField(e.target.value)} disabled={readOnly}>
        {!field && <option value={leaf.field}>{leaf.field || 'Choose a field'} (unknown)</option>}
        {groups.map(([s, fields]) =>
          fields.length ? (
            <optgroup key={s} label={SOURCE_LABEL[s]}>
              {fields.map((f) => (
                <option key={f.ref} value={f.ref}>
                  {f.label}
                </option>
              ))}
            </optgroup>
          ) : null,
        )}
      </Select>
      {field?.source === 'extracted' && (
        <Select
          aria-label={`${label}: which documents`}
          size="sm" full={false}
          value={leaf.quantifier ?? 'all'}
          onChange={(e) => onChange({ ...leaf, quantifier: e.target.value as 'all' | 'any' })}
          disabled={readOnly}
          title="Documents without a value for this field are not counted"
        >
          <option value="all">in every document</option>
          <option value="any">in at least one document</option>
        </Select>
      )}
      <Select aria-label={`${label}: operator`} size="sm" full={false} value={leaf.op} onChange={(e) => setOp(e.target.value)} disabled={readOnly || !field}>
        {!ops.includes(leaf.op) && <option value={leaf.op}>{leaf.op} (not allowed)</option>}
        {ops.map((op) => (
          <option key={op} value={op}>
            {OP_LABEL[op] ?? op}
          </option>
        ))}
      </Select>
      <ValueInput leaf={leaf} type={field?.type} shape={shape} onChange={setValue} readOnly={readOnly} label={label} />
      {!readOnly && (
        <span className="ml-auto flex items-center gap-0.5">
          {onWrap && (
            <button type="button" onClick={onWrap} className="rounded-md p-1.5 text-ink-subtle hover:bg-violet-50 hover:text-violet-700" aria-label={`Group ${label} with another condition`} title="Group with another condition">
              <Brackets className="size-3.5" aria-hidden />
            </button>
          )}
          {onRemove && (
            <button type="button" onClick={onRemove} className="rounded-md p-1.5 text-ink-subtle hover:bg-fail-bg hover:text-fail" aria-label={`Remove ${label}`}>
              <Trash2 className="size-3.5" aria-hidden />
            </button>
          )}
        </span>
      )}
    </div>
  )
}

function ValueInput({
  leaf,
  type,
  shape,
  onChange,
  readOnly,
  label,
}: {
  leaf: LeafNode
  type?: string
  shape?: string
  onChange: (v: LeafValue | undefined) => void
  readOnly?: boolean
  label: string
}) {
  const v = leaf.value
  const htmlType = type === 'date' ? 'date' : type === 'number' ? 'number' : 'text'
  const parse = (s: string): string | number => (type === 'number' && s.trim() !== '' && !Number.isNaN(Number(s)) ? Number(s) : s)

  if (shape === 'none' || !shape) return null
  if (shape === 'int') {
    const unit = leaf.op.startsWith('age_') ? 'years' : 'days (negative = earlier)'
    return (
      <span className="inline-flex items-center gap-1.5">
        <input
          type="number"
          step={1}
          aria-label={`${label}: ${unit}`}
          className={cn(input, 'w-24')}
          value={typeof v === 'number' ? v : ''}
          onChange={(e) => onChange(e.target.value === '' ? null : Math.trunc(Number(e.target.value)))}
          disabled={readOnly}
        />
        <span className="text-[12px] text-ink-subtle">{unit}</span>
      </span>
    )
  }
  if (shape === 'pair') {
    const [a, b] = Array.isArray(v) ? v : ['', '']
    return (
      <span className="inline-flex items-center gap-1.5">
        <input type={htmlType} aria-label={`${label}: from`} className={cn(input, 'w-36')} value={String(a ?? '')} onChange={(e) => onChange([parse(e.target.value), b])} disabled={readOnly} />
        <span className="text-[12px] text-ink-subtle">and</span>
        <input type={htmlType} aria-label={`${label}: to`} className={cn(input, 'w-36')} value={String(b ?? '')} onChange={(e) => onChange([a, parse(e.target.value)])} disabled={readOnly} />
      </span>
    )
  }
  if (type === 'outcome') {
    if (shape === 'list') {
      const selected = Array.isArray(v) ? v.map(String) : []
      return (
        <span role="group" aria-label={`${label}: outcomes`} className="inline-flex flex-wrap gap-1">
          {OUTCOME_VALUES.map((o) => (
            <label key={o} className={cn('inline-flex cursor-pointer items-center gap-1 rounded-md border px-2 py-1 text-[12px]', selected.includes(o) ? 'border-violet-400 bg-violet-50 text-violet-700' : 'border-line-strong')}>
              <input
                type="checkbox"
                className="sr-only"
                checked={selected.includes(o)}
                disabled={readOnly}
                onChange={(e) => onChange(e.target.checked ? [...selected, o] : selected.filter((x) => x !== o))}
              />
              {o}
            </label>
          ))}
        </span>
      )
    }
    return (
      <Select aria-label={`${label}: value`} size="sm" full={false} value={String(v ?? 'pass')} onChange={(e) => onChange(e.target.value)} disabled={readOnly}>
        {OUTCOME_VALUES.map((o) => (
          <option key={o}>{o}</option>
        ))}
      </Select>
    )
  }
  if (shape === 'list') return <ListInput value={Array.isArray(v) ? v : []} onChange={onChange} parse={parse} readOnly={readOnly} label={label} />
  return (
    <input
      type={htmlType}
      aria-label={`${label}: value`}
      className={cn(input, 'w-48')}
      value={v === null || v === undefined || Array.isArray(v) ? '' : String(v)}
      maxLength={200}
      onChange={(e) => onChange(parse(e.target.value))}
      disabled={readOnly}
    />
  )
}

/** Comma-separated list. Keeps the raw text locally so typing a trailing comma isn't fought. */
function ListInput({
  value,
  onChange,
  parse,
  readOnly,
  label,
}: {
  value: (string | number)[]
  onChange: (v: LeafValue) => void
  parse: (s: string) => string | number
  readOnly?: boolean
  label: string
}) {
  const hintId = useId()
  const joined = value.join(', ')
  const [text, setText] = useState(joined)
  useEffect(() => {
    // Sync when the value changes from outside (e.g. JSON view edits), not on our own keystrokes.
    setText((t) => (t.split(',').map((s) => s.trim()).filter(Boolean).join(', ') === joined ? t : joined))
  }, [joined])
  return (
    <span className="inline-flex items-center gap-1.5">
      <input
        aria-label={`${label}: values`}
        aria-describedby={hintId}
        className={cn(input, 'w-56')}
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          onChange(e.target.value.split(',').map((s) => s.trim()).filter(Boolean).map(parse))
        }}
        disabled={readOnly}
      />
      <span id={hintId} className="text-[12px] text-ink-subtle">
        comma-separated
      </span>
    </span>
  )
}
