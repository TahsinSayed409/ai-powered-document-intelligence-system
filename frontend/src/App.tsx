import { type ChangeEvent, useEffect, useMemo, useState } from 'react'
import './App.css'

type LineItem = {
  description?: string | null
  quantity?: number | null
  unit_price?: number | null
  line_total?: number | null
  evidence?: string | null
  confidence?: number | null
  source_page?: number | null
  source_sheet?: string | null
}

type FieldAssessment = {
  field: string
  status: 'found' | 'missing' | 'uncertain'
  confidence: number
  evidence?: string | null
  source_page?: number | null
  source_sheet?: string | null
}

type DocumentRecord = {
  id: number
  filename: string
  file_type: string
  status: string
  validation_status?: string | null
  invoice_number?: string | null
  invoice_date?: string | null
  supplier_name?: string | null
  customer_name?: string | null
  subtotal?: number | null
  tax?: number | null
  total?: number | null
  currency?: string | null
  extracted_data?: {
    invoice_number?: string | null
    invoice_date?: string | null
    supplier_name?: string | null
    customer_name?: string | null
    subtotal?: number | null
    tax?: number | null
    total?: number | null
    currency?: string | null
    confidence?: number | null
    line_items?: LineItem[]
    field_assessments?: FieldAssessment[]
  } | null
  validation_result?: {
    issues?: Array<{ message?: string; field?: string; severity?: string }>
    summary?: string
  } | null
  error_message?: string | null
}

type CorrectionField =
  | 'invoice_number'
  | 'invoice_date'
  | 'supplier_name'
  | 'customer_name'
  | 'subtotal'
  | 'tax'
  | 'total'
  | 'currency'

type SearchMode = 'keyword' | 'semantic'

type ComparisonValue = {
  field: string
  left?: unknown
  right?: unknown
  value?: unknown
}

type ComparisonResult = {
  left_file_type: string
  right_file_type: string
  comparison: {
    status: 'MATCH' | 'MISMATCH' | 'PARTIAL'
    matched: ComparisonValue[]
    mismatched: ComparisonValue[]
    missing: ComparisonValue[]
    warnings: ComparisonValue[]
  }
  duplicate: {
    classification: string
  }
}

const numericCorrectionFields: CorrectionField[] = ['subtotal', 'tax', 'total']

const API_BASE = '/api'

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const body = await response.json() as { detail?: string }
      if (body.detail) message = body.detail
    } catch {
      // Use the HTTP status when the server response is not JSON.
    }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

function documentValue<T>(document: DocumentRecord, field: keyof NonNullable<DocumentRecord['extracted_data']>): T | null {
  const topLevelValue = document[field as keyof DocumentRecord]
  return (topLevelValue ?? document.extracted_data?.[field] ?? null) as T | null
}

function displayValue(value: unknown): string {
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

function comparisonValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function App() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([])
  const [searchResults, setSearchResults] = useState<DocumentRecord[] | null>(null)
  const [searchTerm, setSearchTerm] = useState('')
  const [searchMode, setSearchMode] = useState<SearchMode>('keyword')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [selectedDocument, setSelectedDocument] = useState<DocumentRecord | null>(null)
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState('')
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchError, setSearchError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [actionMessage, setActionMessage] = useState('')
  const [correctionField, setCorrectionField] = useState<CorrectionField>('invoice_number')
  const [correctionValue, setCorrectionValue] = useState('')
  const [savingCorrection, setSavingCorrection] = useState(false)
  const [reprocessing, setReprocessing] = useState(false)
  const [comparisonLeftId, setComparisonLeftId] = useState<number | null>(null)
  const [comparisonRightId, setComparisonRightId] = useState<number | null>(null)
  const [comparisonResult, setComparisonResult] = useState<ComparisonResult | null>(null)
  const [comparisonLoading, setComparisonLoading] = useState(false)
  const [comparisonError, setComparisonError] = useState('')

  const visibleDocuments = searchResults ?? documents
  const selectedSummary = visibleDocuments.find((item) => item.id === selectedId)
    ?? documents.find((item) => item.id === selectedId)

  const stats = useMemo(() => [
    { label: 'Total documents', value: documents.length, accent: 'teal' },
    { label: 'Processed', value: documents.filter((item) => item.status === 'processed').length, accent: 'green' },
    { label: 'Review queue', value: documents.filter((item) => item.status === 'requires_review').length, accent: 'amber' },
    { label: 'Failed', value: documents.filter((item) => item.status === 'failed').length, accent: 'red' },
  ], [documents])
  const comparisonLeftDocuments = useMemo(
    () => documents.filter((item) =>
    item.file_type.toLowerCase() === 'pdf'
    && ['processed', 'requires_review'].includes(item.status),
    ),
    [documents],
  )
  const comparisonRightDocuments = useMemo(
    () => documents.filter((item) =>
    item.id !== comparisonLeftId
    && ['pdf', 'xlsx'].includes(item.file_type.toLowerCase())
    && ['processed', 'requires_review'].includes(item.status),
    ),
    [comparisonLeftId, documents],
  )

  const loadDocuments = async () => {
    setListLoading(true)
    setListError('')
    try {
      const response = await requestJson<{ items: DocumentRecord[] }>(`${API_BASE}/documents?skip=0&limit=100`)
      setDocuments(response.items)
      setSearchResults(null)
      setSelectedId((current) => current && response.items.some((item) => item.id === current)
        ? current
        : response.items[0]?.id ?? null)
    } catch (error) {
      setListError(error instanceof Error ? error.message : 'Unable to load documents.')
    } finally {
      setListLoading(false)
    }
  }

  useEffect(() => {
    queueMicrotask(() => { void loadDocuments() })
  }, [])

  useEffect(() => {
    const query = searchTerm.trim()
    if (!query) return

    let active = true
    const timer = window.setTimeout(async () => {
      setSearchLoading(true)
      setSearchError('')
      try {
        const response = await requestJson<{ results: DocumentRecord[] }>(
          `${API_BASE}/search?query=${encodeURIComponent(query)}&mode=${searchMode}`,
        )
        if (active) setSearchResults(response.results)
      } catch (error) {
        if (active) setSearchError(error instanceof Error ? error.message : 'Search failed.')
      } finally {
        if (active) setSearchLoading(false)
      }
    }, 250)

    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [searchMode, searchTerm])

  const refreshSearchResults = async () => {
    const query = searchTerm.trim()
    if (!query) return
    try {
      const response = await requestJson<{ results: DocumentRecord[] }>(
        `${API_BASE}/search?query=${encodeURIComponent(query)}&mode=${searchMode}`,
      )
      setSearchResults(response.results)
    } catch (error) {
      setSearchError(error instanceof Error ? error.message : 'Search failed.')
    }
  }

  const handleCompare = async () => {
    if (comparisonLeftId === null || comparisonRightId === null || comparisonLeftId === comparisonRightId) return
    setComparisonLoading(true)
    setComparisonError('')
    setComparisonResult(null)
    try {
      const result = await requestJson<ComparisonResult>(`${API_BASE}/compare`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          left_document_id: comparisonLeftId,
          right_document_id: comparisonRightId,
        }),
      })
      setComparisonResult(result)
    } catch (error) {
      setComparisonError(error instanceof Error ? error.message : 'Unable to compare documents.')
    } finally {
      setComparisonLoading(false)
    }
  }

  useEffect(() => {
    const activeDocuments = documents.filter((item) => ['queued', 'pending', 'processing'].includes(item.status))
    if (!activeDocuments.length) return

    const pollStatuses = async () => {
      await Promise.all(activeDocuments.map(async (item) => {
        try {
          const status = await requestJson<Pick<DocumentRecord, 'id' | 'status' | 'validation_status'>>(
            `${API_BASE}/documents/${item.id}/status`,
          )
          setDocuments((current) => current.map((document) => document.id === status.id
            ? { ...document, status: status.status, validation_status: status.validation_status }
            : document))
        } catch {
          // A transient polling error should not hide the document or stop future polls.
        }
      }))
    }

    const timer = window.setInterval(() => { void pollStatuses() }, 3000)
    return () => window.clearInterval(timer)
  }, [documents])

  const selectedStatus = documents.find((item) => item.id === selectedId)?.status
  useEffect(() => {
    if (selectedId === null) return

    let active = true
    queueMicrotask(() => {
      if (!active) return
      setDetailLoading(true)
      setDetailError('')
      void requestJson<DocumentRecord>(`${API_BASE}/documents/${selectedId}`)
        .then((detail) => {
          if (!active) return
          setSelectedDocument(detail)
          setDocuments((current) => current.map((item) => item.id === detail.id ? { ...item, ...detail } : item))
        })
        .catch((error: unknown) => {
          if (active) setDetailError(error instanceof Error ? error.message : 'Unable to load document details.')
        })
        .finally(() => {
          if (active) setDetailLoading(false)
        })
    })

    return () => { active = false }
  }, [selectedId, selectedStatus])

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? [])
    event.target.value = ''
    if (files.length === 0) return

    setUploading(true)
    setUploadError('')
    setActionMessage('')
    const formData = new FormData()
    files.forEach((file) => formData.append('files', file))
    try {
      const response = await requestJson<{
        documents: Array<{ id: number }>
        failures?: Array<{ filename: string; error: string }>
      }>(
        `${API_BASE}/documents/upload`,
        { method: 'POST', body: formData },
      )
      await loadDocuments()
      await refreshSearchResults()
      if (response.documents[0]) setSelectedId(response.documents[0].id)
      setActionMessage(`${response.documents.length} file${response.documents.length === 1 ? '' : 's'} uploaded.`)
      if (response.failures?.length) {
        setUploadError(response.failures.map((failure) => `${failure.filename}: ${failure.error}`).join(' '))
      }
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : 'Upload failed.')
    } finally {
      setUploading(false)
    }
  }

  const handleReprocess = async () => {
    if (!selectedId) return
    setReprocessing(true)
    setActionError('')
    setActionMessage('')
    try {
      await requestJson(`${API_BASE}/documents/${selectedId}/reprocess`, { method: 'POST' })
      await loadDocuments()
      await refreshSearchResults()
      setSelectedId(selectedId)
      setActionMessage('Document queued for reprocessing.')
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Unable to reprocess document.')
    } finally {
      setReprocessing(false)
    }
  }

  const handleCorrection = async (event: ChangeEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedId) return
    setSavingCorrection(true)
    setActionError('')
    setActionMessage('')
    const trimmedValue = correctionValue.trim()
    const isNumericField = numericCorrectionFields.includes(correctionField)
    const value = trimmedValue === ''
      ? null
      : isNumericField
        ? Number(trimmedValue)
        : trimmedValue
    if (isNumericField && value !== null && (typeof value !== 'number' || !Number.isFinite(value))) {
      setSavingCorrection(false)
      setActionError('Enter a valid finite number for this field.')
      return
    }
    try {
      await requestJson(`${API_BASE}/documents/${selectedId}/corrections`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ field_name: correctionField, value }),
      })
      setCorrectionValue('')
      setActionMessage('Correction saved.')
      const detail = await requestJson<DocumentRecord>(`${API_BASE}/documents/${selectedId}`)
      setSelectedDocument(detail)
      setDocuments((current) => current.map((item) => item.id === detail.id ? { ...item, ...detail } : item))
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Unable to save correction.')
    } finally {
      setSavingCorrection(false)
    }
  }

  const displayedDocument = selectedDocument?.id === selectedId ? selectedDocument : null
  const extracted = displayedDocument?.extracted_data
  const validationNotes = displayedDocument?.validation_result?.issues?.map((issue) => issue.message).filter(Boolean) ?? []
  const confidence = extracted?.confidence
  const lineItems = extracted?.line_items ?? []
  const fieldAssessments = extracted?.field_assessments ?? []

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Document intelligence</p>
          <h1>Invoice Processing Dashboard</h1>
        </div>
        <div className="topbar-actions">
          <label className="primary upload-button">
            <input type="file" multiple disabled={uploading} onChange={handleUpload} />
            {uploading ? 'Uploading…' : 'Upload files'}
          </label>
        </div>
      </header>

      <section className="stat-grid">
        {stats.map((stat) => (
          <div key={stat.label} className={`stat-card ${stat.accent}`}>
            <span>{stat.label}</span>
            <strong>{stat.value}</strong>
          </div>
        ))}
      </section>

      {uploadError && <p role="alert" className="empty-state">{uploadError}</p>}
      {actionError && <p role="alert" className="empty-state">{actionError}</p>}
      {actionMessage && <p role="status" className="empty-state">{actionMessage}</p>}

      <main className="content-grid">
        <section className="panel listing-panel">
          <div className="panel-header">
            <h2>Document queue</h2>
            <div className="search-controls">
              <select
                aria-label="Search mode"
                value={searchMode}
                onChange={(event) => setSearchMode(event.target.value as SearchMode)}
              >
                <option value="keyword">Keyword search</option>
                <option value="semantic">Semantic search</option>
              </select>
              <input
                type="search"
                value={searchTerm}
                onChange={(event) => {
                  const value = event.target.value
                  setSearchTerm(value)
                  if (!value.trim()) {
                    setSearchResults(null)
                    setSearchError('')
                    setSearchLoading(false)
                  }
                }}
                placeholder="Search invoice or supplier"
                aria-label="Search documents"
              />
            </div>
          </div>
          {listError && <p role="alert" className="empty-state">{listError}</p>}
          {searchError && <p role="alert" className="empty-state">{searchError}</p>}
          {searchLoading && <p className="empty-state">Searching documents…</p>}
          {listLoading ? <p className="empty-state">Loading documents…</p> : (
            <table>
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Supplier</th>
                  <th>Total</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {visibleDocuments.map((item) => (
                  <tr
                    key={item.id}
                    className={item.id === selectedId ? 'selected' : ''}
                    onClick={() => setSelectedId(item.id)}
                  >
                    <td>
                      <div className="doc-name">
                        <span className="doc-icon">📄</span>
                        <div>
                          <strong>{item.filename}</strong>
                          <small>{displayValue(item.invoice_number)}</small>
                        </div>
                      </div>
                    </td>
                    <td>{displayValue(item.supplier_name)}</td>
                    <td>{item.currency ?? ''} {item.total == null ? '—' : item.total.toFixed(2)}</td>
                    <td><span className={`pill ${item.status}`}>{item.status.replaceAll('_', ' ')}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {!listLoading && !listError && !searchLoading && visibleDocuments.length === 0 && (
            <p className="empty-state">{searchTerm ? 'No documents match your search.' : 'No documents uploaded yet.'}</p>
          )}
        </section>

        <section className="panel detail-panel">
          <div className="panel-header split-header">
            <div>
              <p className="eyebrow small">Invoice details</p>
              <h2>{displayedDocument?.filename ?? selectedSummary?.filename ?? 'Select a document'}</h2>
            </div>
            {displayedDocument && (
              <span className={`pill ${displayedDocument.validation_status ?? displayedDocument.status}`}>
                {displayedDocument.validation_status ?? displayedDocument.status.replaceAll('_', ' ')}
              </span>
            )}
          </div>
          {detailLoading && <p className="empty-state">Loading document details…</p>}
          {detailError && <p role="alert" className="empty-state">{detailError}</p>}
          {!displayedDocument && !detailLoading && !detailError && (
            <p className="empty-state">{documents.length ? 'Select a document to view its details.' : 'Document details will appear here after upload.'}</p>
          )}
          {displayedDocument && !detailLoading && (
            <>
              <div className="detail-grid">
                <div><label>Supplier</label><strong>{displayValue(documentValue(displayedDocument, 'supplier_name'))}</strong></div>
                <div><label>Customer</label><strong>{displayValue(documentValue(displayedDocument, 'customer_name'))}</strong></div>
                <div><label>Invoice number</label><strong>{displayValue(documentValue(displayedDocument, 'invoice_number'))}</strong></div>
                <div><label>Invoice date</label><strong>{displayValue(documentValue(displayedDocument, 'invoice_date'))}</strong></div>
                <div><label>Document type</label><strong>{displayValue(displayedDocument.file_type).toUpperCase()}</strong></div>
                <div><label>Subtotal</label><strong>{displayValue(documentValue(displayedDocument, 'subtotal'))}</strong></div>
                <div><label>Tax</label><strong>{displayValue(documentValue(displayedDocument, 'tax'))}</strong></div>
                <div><label>Total</label><strong>{displayValue(documentValue(displayedDocument, 'total'))}</strong></div>
                <div><label>Currency</label><strong>{displayValue(documentValue(displayedDocument, 'currency'))}</strong></div>
                <div><label>Confidence</label><strong>{confidence == null ? 'N/A' : `${(confidence * 100).toFixed(0)}%`}</strong></div>
              </div>

              <div className="line-items">
                <h3>Line items</h3>
                {lineItems.length ? (
                  <ul>
                    {lineItems.map((item, index) => (
                      <li key={`${item.description ?? 'item'}-${index}`}>
                        <span>{displayValue(item.description)}</span>
                        <span>{item.quantity ?? '—'} × {item.unit_price?.toFixed(2) ?? '—'}</span>
                        <strong>{item.line_total?.toFixed(2) ?? '—'}</strong>
                        {item.evidence && (
                          <small>
                            {item.source_sheet ? `${item.source_sheet}, ` : ''}
                            {item.source_page ? `page ${item.source_page}: ` : ''}
                            {item.evidence}
                          </small>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : <p className="empty-state">No line items extracted yet.</p>}
              </div>

              <div className="notes-panel">
                <h3>Field evidence and confidence</h3>
                <p className="empty-state">
                  Assessment status and evidence refer to the original source extraction. Manually corrected values appear above.
                </p>
                {fieldAssessments.length ? (
                  <ul>
                    {fieldAssessments.map((assessment) => (
                      <li key={assessment.field}>
                        <strong>{assessment.field.replaceAll('_', ' ')}</strong>
                        <span className={`pill ${assessment.status}`}>{assessment.status}</span>
                        <span>Model confidence: {(assessment.confidence * 100).toFixed(0)}%</span>
                        <span>
                          {assessment.source_sheet ? `${assessment.source_sheet}, ` : ''}
                          {assessment.source_page ? `page ${assessment.source_page}: ` : ''}
                          {assessment.evidence ?? 'No verified source quote; review required.'}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : <p className="empty-state">No field-level evidence available.</p>}
              </div>

              <div className="notes-panel">
                <h3>Validation notes</h3>
                {displayedDocument.error_message && <p>{displayedDocument.error_message}</p>}
                {validationNotes.length ? (
                  <ul>{validationNotes.map((note, index) => <li key={`${note}-${index}`}>{note}</li>)}</ul>
                ) : !displayedDocument.error_message ? (
                  <p className="empty-state">{displayedDocument.validation_result?.summary ?? 'No validation notes.'}</p>
                ) : null}
              </div>

              <div className="notes-panel">
                <h3>Document actions</h3>
                <button
                  className="secondary"
                  type="button"
                  disabled={reprocessing || displayedDocument.status !== 'failed'}
                  onClick={() => void handleReprocess()}
                  title="Only failed documents can be reprocessed."
                >
                  {reprocessing ? 'Reprocessing…' : 'Reprocess failed document'}
                </button>
                <form onSubmit={(event) => void handleCorrection(event)} style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12 }}>
                  <select
                    aria-label="Correction field"
                    value={correctionField}
                    onChange={(event) => setCorrectionField(event.target.value as CorrectionField)}
                  >
                    <option value="invoice_number">Invoice number</option>
                    <option value="invoice_date">Invoice date</option>
                    <option value="supplier_name">Supplier</option>
                    <option value="customer_name">Customer</option>
                    <option value="subtotal">Subtotal</option>
                    <option value="tax">Tax</option>
                    <option value="total">Total</option>
                    <option value="currency">Currency</option>
                  </select>
                  <input
                    aria-label="Correction value"
                    type={numericCorrectionFields.includes(correctionField) ? 'number' : 'text'}
                    step={numericCorrectionFields.includes(correctionField) ? 'any' : undefined}
                    value={correctionValue}
                    onChange={(event) => setCorrectionValue(event.target.value)}
                    placeholder={numericCorrectionFields.includes(correctionField) ? 'Correct value (blank clears)' : 'Correct value (blank clears)'}
                  />
                  <button className="secondary" type="submit" disabled={savingCorrection}>
                    {savingCorrection ? 'Saving…' : 'Save correction'}
                  </button>
                </form>
              </div>
            </>
          )}
        </section>
      </main>

      <section className="panel comparison-panel" aria-labelledby="comparison-heading">
        <div className="panel-header split-header">
          <div>
            <p className="eyebrow small">Document tools</p>
            <h2 id="comparison-heading">Compare invoices</h2>
          </div>
          <p className="comparison-help">Compare a processed PDF with another PDF or XLSX invoice.</p>
        </div>
        {comparisonLeftDocuments.length === 0 ? (
          <p className="empty-state">Process a PDF invoice before comparing documents.</p>
        ) : (
          <>
            <div className="comparison-controls">
              <label>
                First document (PDF)
                <select
                  aria-label="First comparison document"
                  value={comparisonLeftId ?? ''}
                  onChange={(event) => {
                    setComparisonLeftId(event.target.value ? Number(event.target.value) : null)
                    setComparisonResult(null)
                    setComparisonError('')
                  }}
                >
                  <option value="">Select a PDF</option>
                  {comparisonLeftDocuments.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.filename} — {item.invoice_number ?? 'No invoice number'}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Second document (PDF or XLSX)
                <select
                  aria-label="Second comparison document"
                  value={comparisonRightId ?? ''}
                  onChange={(event) => {
                    setComparisonRightId(event.target.value ? Number(event.target.value) : null)
                    setComparisonResult(null)
                    setComparisonError('')
                  }}
                >
                  <option value="">Select a PDF or XLSX</option>
                  {comparisonRightDocuments.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.filename} — {item.invoice_number ?? 'No invoice number'}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="primary"
                type="button"
                disabled={
                  comparisonLoading
                  || comparisonLeftId === null
                  || comparisonRightId === null
                  || comparisonLeftId === comparisonRightId
                }
                onClick={() => void handleCompare()}
              >
                {comparisonLoading ? 'Comparing…' : 'Compare documents'}
              </button>
            </div>
            {comparisonLeftId !== null && comparisonRightDocuments.length === 0 && (
              <p className="empty-state">Select a different processed PDF or XLSX document to compare.</p>
            )}
          </>
        )}
        {comparisonLoading && <p role="status" className="empty-state">Comparing selected documents…</p>}
        {comparisonError && <p role="alert" className="empty-state">{comparisonError}</p>}
        {comparisonResult && (
          <div className="comparison-result">
            <div className="comparison-result-heading">
              <h3>Comparison result</h3>
              <span className={`pill comparison-${comparisonResult.comparison.status.toLowerCase()}`}>
                {comparisonResult.comparison.status}
              </span>
            </div>
            <p>
              {comparisonResult.left_file_type.toUpperCase()} versus {comparisonResult.right_file_type.toUpperCase()}
              {' · '}Duplicate check: {comparisonResult.duplicate.classification.replaceAll('_', ' ')}
            </p>
            {comparisonResult.comparison.status === 'PARTIAL' && (
              <p role="status">Some fields or line items were missing from one document.</p>
            )}
            {comparisonResult.comparison.mismatched.length > 0 && (
              <div>
                <h4>Differences</h4>
                <ul>
                  {comparisonResult.comparison.mismatched.map((difference, index) => (
                    <li key={`${difference.field}-${index}`}>
                      <strong>{difference.field}</strong>
                      <span>First: {comparisonValue(difference.left)}</span>
                      <span>Second: {comparisonValue(difference.right)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {comparisonResult.comparison.missing.length > 0 && (
              <div>
                <h4>Missing comparisons</h4>
                <ul>
                  {comparisonResult.comparison.missing.map((difference, index) => (
                    <li key={`${difference.field}-${index}`}>
                      <strong>{difference.field}</strong>
                      <span>First: {comparisonValue(difference.left)}</span>
                      <span>Second: {comparisonValue(difference.right)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {comparisonResult.comparison.matched.length > 0 && (
              <details>
                <summary>{comparisonResult.comparison.matched.length} matching field(s)</summary>
                <ul>
                  {comparisonResult.comparison.matched.map((match, index) => (
                    <li key={`${match.field}-${index}`}>
                      <strong>{match.field}</strong>: {comparisonValue(match.value)}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {comparisonResult.comparison.warnings.length > 0 && (
              <ul>
                {comparisonResult.comparison.warnings.map((warning, index) => (
                  <li key={`${warning.field}-${index}`}>{warning.field}: {comparisonValue(warning.value)}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </section>
    </div>
  )
}

export default App
