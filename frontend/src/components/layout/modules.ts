import {
  FolderKanban,
  Gauge,
  Landmark,
  Network,
  ScaleIcon,
  ShieldCheck,
  UserCheck,
  type LucideIcon,
} from 'lucide-react'
import type { Permission } from '../../lib/types'

export interface ModuleDef {
  path: string
  label: string
  short: string
  icon: LucideIcon
  permission: Permission
  /** Phase in which the module's functional workflows are delivered. 0 = available now. */
  status: 'available' | 'planned'
  summary: string
  capabilities: string[]
  /** Intentional initial empty state shown until the module's workflows ship. */
  empty?: { title: string; body: string }
}

/** The seven VerifyFlow modules. Order defines the navigation. */
export const MODULES: ModuleDef[] = [
  {
    path: '/',
    label: 'Command Center',
    short: 'Command',
    icon: Gauge,
    permission: 'system:read',
    status: 'available',
    summary: 'Live platform health, capability status and recent activity.',
    capabilities: [],
  },
  {
    path: '/applications',
    label: 'Application Workspace',
    short: 'Applications',
    icon: FolderKanban,
    permission: 'applications:read',
    status: 'available',
    summary: 'Create applications, upload documents securely and track their processing.',
    empty: {
      title: 'No applications yet',
      body: 'Applications and their uploaded documents will be listed here. Nothing has been created in this workspace.',
    },
    capabilities: [
      'Secure upload with content-based type detection and SHA-256 hashing',
      'PDF text extraction (PyMuPDF) and OCR for scanned pages (Tesseract)',
      'Field provenance: page, bounding box and extraction method for every value',
      'Human corrections that preserve the original extracted value',
    ],
  },
  {
    path: '/evidence',
    label: 'Evidence Intelligence Graph',
    short: 'Evidence',
    icon: Network,
    permission: 'documents:read',
    status: 'available',
    summary: 'Cross-document reasoning: see how values agree or contradict across documents.',
    empty: {
      title: 'No evidence to connect yet',
      body: 'The graph is built from extracted document fields. It will populate once applications contain processed documents.',
    },
    capabilities: [
      'Entity and field graph across every document in an application',
      'Contradiction detection with impact analysis on affected rules',
      'Click-through from any node to the highlighted source region',
    ],
  },
  {
    path: '/compliance',
    label: 'Compliance Studio',
    short: 'Compliance',
    icon: ScaleIcon,
    permission: 'rules:read',
    status: 'available',
    summary: 'Author modular, versioned, effective-dated rules and simulate changes before publishing.',
    empty: {
      title: 'No rule sets defined',
      body: 'Rule sets you author, version and publish will appear here. No rules exist yet, so nothing is being evaluated.',
    },
    capabilities: [
      'Declarative rules: allowlisted operators only, no user-supplied code or expressions',
      'Immutable versions with effective-date windows and four-eyes approval',
      'Rule test cases and read-only what-if simulation before publishing',
    ],
  },
  {
    path: '/review',
    label: 'Review & Resolution',
    short: 'Review',
    icon: UserCheck,
    permission: 'applications:read',
    status: 'available',
    summary: 'Human-in-the-loop queue for findings that need judgement, with rule-to-evidence traceability.',
    empty: {
      title: 'Review queue is empty',
      body: 'Findings that need human judgement, failed rules and missing evidence will be queued here. There is nothing to review.',
    },
    capabilities: [
      'Separate queues for failures, uncertain findings and missing evidence',
      'Sensitive decisions require a reason; history is append-only and audited',
      'Corrections revalidate automatically when they affect a rule in force',
    ],
  },
  {
    path: '/trust',
    label: 'Trust & Authentication',
    short: 'Trust',
    icon: ShieldCheck,
    permission: 'documents:read',
    status: 'available',
    summary: 'Supported technical authenticity checks with explicit limits on what can be established.',
    empty: {
      title: 'No authenticity checks yet',
      body: 'Technical verification results for uploaded documents will appear here, each with an explicit statement of what could not be established.',
    },
    capabilities: [
      'SHA-256 file integrity and PDF digital-signature validation (pyHanko)',
      'Certificate trust only against anchors you configure; revocation and registries where configured',
      'Inconclusive and unsupported are first-class outcomes, never shown as verified',
    ],
  },
  {
    path: '/governance',
    label: 'Governance & Insights',
    short: 'Governance',
    icon: Landmark,
    permission: 'audit:read',
    status: 'available',
    summary: 'Defined metrics from stored records, reviewer outcomes, rule history, the hash-chained audit trail and audited exports.',
    capabilities: [],
  },
]
