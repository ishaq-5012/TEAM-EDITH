import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../../lib/api'

/** The catalog changes only with server configuration; fetch it once per session. */
export function useRuleCatalog() {
  return useQuery({ queryKey: ['rule-catalog'], queryFn: api.ruleCatalog, staleTime: Infinity })
}

/** Debounced, server-side schema validation. The server is the only authority on validity. */
export function useDefinitionCheck(definition: unknown, enabled = true) {
  const json = JSON.stringify(definition)
  const [debounced, setDebounced] = useState(json)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(json), 350)
    return () => clearTimeout(t)
  }, [json])
  return useQuery({
    queryKey: ['rule-check', debounced],
    queryFn: () => api.validateDefinition(JSON.parse(debounced)),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    retry: false,
  })
}
