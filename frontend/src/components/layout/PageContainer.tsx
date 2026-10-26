import { Children, useEffect, type ReactNode } from 'react'
import { Reveal } from '../fx/Reveal'
import { PageHeader } from '../ui/PageHeader'

/**
 * Standard page frame: sets the document title, renders the page header and
 * gives every module the same vertical rhythm.
 */
export function PageContainer({
  eyebrow,
  title,
  description,
  actions,
  documentTitle,
  children,
}: {
  eyebrow?: string
  title: string
  description?: ReactNode
  actions?: ReactNode
  /** Defaults to `title`. */
  documentTitle?: string
  children: ReactNode
}) {
  const docTitle = documentTitle ?? title
  useEffect(() => {
    document.title = `${docTitle} · VerifyFlow AI`
  }, [docTitle])
  return (
    <div className="pb-10">
      <PageHeader eyebrow={eyebrow} title={title} description={description} actions={actions} />
      {/* Each section rises into place in 3D, one after another, as it scrolls into view. */}
      <div className="space-y-5">
        {Children.toArray(children).map((child, i) => (
          <Reveal key={i} index={i}>
            {child}
          </Reveal>
        ))}
      </div>
    </div>
  )
}
