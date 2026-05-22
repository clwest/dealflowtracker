import { useState, useEffect } from 'react'
import { TrendingUp, ArrowLeft, LogIn, LogOut, FileText, Sparkles, Star, ChevronRight, ExternalLink, MessageSquare, Download, BarChart3, Users, Plus, Search, Loader2, UserPlus, Link, CreditCard, Zap, Check, Building, Send } from 'lucide-react'
import { jsPDF } from 'jspdf'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8006/api'
const STAGES = ['new', 'review', 'diligence', 'term_sheet', 'closed_won', 'closed_lost'] as const
const STAGE_LABELS: Record<string, string> = { new: 'New', review: 'Review', diligence: 'Diligence', term_sheet: 'Term Sheet', closed_won: 'Won', closed_lost: 'Lost' }
const STAGE_COLORS: Record<string, string> = { new: 'border-gray-500', review: 'border-blue-500', diligence: 'border-amber-500', term_sheet: 'border-purple-500', closed_won: 'border-green-500', closed_lost: 'border-red-500' }

interface Deal { id: string; stage: string; company_name: string; one_liner: string; sector: string; raise_amount: string; deck_url: string; founder_name: string; scorecard: Record<string, number>; score_avg: number; memo: string | null; notes: string | null; activities?: Activity[]; contacts?: DealContactInfo[] }
interface Activity { id: string; action_type: string; content: string; created_at: string }
interface AuthUser { id: string; email: string; name: string; role: string }
interface ContactInfo { id: string; name: string; firm: string; role: string; email: string; phone: string; tags: string[]; notes: string }
interface DealContactInfo extends ContactInfo { role_in_deal: string }
interface Analytics { total_deals: number; by_stage: Record<string, number>; funnel: { stage: string; count: number; label: string }[]; top_sectors: { sector: string; count: number }[]; avg_score: number; win_rate: number; total_contacts: number; deals_with_memos: number }
type View = 'home' | 'pipeline' | 'deal-detail' | 'submit' | 'login' | 'register' | 'analytics' | 'contacts' | 'pricing' | 'brain'

function authHeaders(t: string) { return { 'Content-Type': 'application/json', Authorization: `Bearer ${t}` } }

export default function App() {
  const [view, setView] = useState<View>('home')
  const [token, setToken] = useState<string | null>(localStorage.getItem('df_token'))
  const [user, setUser] = useState<AuthUser | null>(null)
  const [deals, setDeals] = useState<Deal[]>([])
  const [activeDeal, setActiveDeal] = useState<Deal | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (token) fetch(`${API}/users/me`, { headers: authHeaders(token) }).then(r => r.ok ? r.json() : Promise.reject()).then(setUser).catch(() => { setToken(null); localStorage.removeItem('df_token') })
  }, [token])

  useEffect(() => {
    if (view === 'pipeline' && token) fetch(`${API}/deals`, { headers: authHeaders(token) }).then(r => r.json()).then(d => setDeals(d.deals)).catch(() => {})
  }, [view, token])

  async function handleLogin(email: string, password: string) {
    const r = await fetch(`${API}/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) })
    if (!r.ok) throw new Error(); const d = await r.json(); setToken(d.token); localStorage.setItem('df_token', d.token); setUser(d.user); setView('pipeline')
  }
  async function handleRegister(email: string, password: string, name: string) {
    const r = await fetch(`${API}/auth/register`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password, name }) })
    if (!r.ok) throw new Error(); const d = await r.json(); setToken(d.token); localStorage.setItem('df_token', d.token); setUser(d.user); setView('pipeline')
  }
  function logout() { setToken(null); setUser(null); localStorage.removeItem('df_token'); setView('home') }

  async function openDeal(id: string) {
    if (!token) return
    const r = await fetch(`${API}/deals/${id}`, { headers: authHeaders(token) })
    if (r.ok) { setActiveDeal(await r.json()); setView('deal-detail') }
  }

  async function moveStage(dealId: string, stage: string) {
    if (!token) return
    await fetch(`${API}/deals/${dealId}/stage`, { method: 'PATCH', headers: authHeaders(token), body: JSON.stringify({ stage }) })
    setView('pipeline') // triggers reload
  }

  async function updateScorecard(dealId: string, sc: Record<string, number>) {
    if (!token) return
    await fetch(`${API}/deals/${dealId}/scorecard`, { method: 'PATCH', headers: authHeaders(token), body: JSON.stringify(sc) })
    openDeal(dealId)
  }

  async function generateMemo(dealId: string) {
    if (!token) return; setLoading(true)
    await fetch(`${API}/deals/${dealId}/generate-memo`, { method: 'POST', headers: authHeaders(token) })
    await openDeal(dealId); setLoading(false)
  }

  async function addNote(dealId: string, content: string) {
    if (!token) return
    await fetch(`${API}/deals/${dealId}/notes`, { method: 'POST', headers: authHeaders(token), body: JSON.stringify({ content }) })
    openDeal(dealId)
  }

  async function submitDeal(data: Record<string, string>) {
    await fetch(`${API}/submissions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
    alert('Submission received!'); setView('pipeline')
  }

  async function fetchDealContacts(dealId: string): Promise<DealContactInfo[]> {
    if (!token) return []
    const r = await fetch(`${API}/deals/${dealId}/contacts`, { headers: authHeaders(token) })
    if (r.ok) { const d = await r.json(); return d.contacts || [] }
    return []
  }

  async function linkContactToDeal(dealId: string, contactId: string, roleInDeal: string = 'investor') {
    if (!token) return
    await fetch(`${API}/deals/${dealId}/contacts`, { method: 'POST', headers: authHeaders(token), body: JSON.stringify({ contact_id: contactId, role_in_deal: roleInDeal }) })
    openDeal(dealId)
  }

  async function importFromFounderProject(projectId: string) {
    if (!token) return
    setLoading(true)
    try {
      const r = await fetch(`${API}/founder-projects/import`, {
        method: 'POST', headers: authHeaders(token),
        body: JSON.stringify({ project_id: projectId }),
      })
      if (r.ok) {
        const data = await r.json()
        setView('pipeline') // triggers reload
        if (data.deal_id) await openDeal(data.deal_id)
      }
    } catch { /* ignore */ }
    setLoading(false)
  }

  return (
    <div className="min-h-screen bg-[#0a0a0f]">
      {/* Founder Toolkit cross-app nav with progress stepper */}
      <div className="bg-[#0f0f18] border-b border-gray-800/50 px-4 py-2">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <a href="https://founder-toolkit.vercel.app" className="flex items-center gap-1.5 hover:opacity-80 transition">
            <div className="w-5 h-5 rounded bg-gradient-to-br from-[#e94560] to-[#7c3aed] flex items-center justify-center text-[9px] font-bold text-white">FT</div>
            <span className="text-[11px] font-medium text-gray-400">Founder Toolkit</span>
          </a>
          <div className="flex items-center gap-1">
            <a href="https://mentorforge.vercel.app" className="flex items-center gap-1 text-[11px] text-gray-500 hover:text-indigo-400 transition px-1.5 py-0.5">
              <span className="w-4 h-4 rounded-full bg-gray-800 flex items-center justify-center text-[9px] text-gray-500">1</span>
              Mentor
            </a>
            <div className="w-3 h-[1px] bg-gray-700 mx-0.5" />
            <span className="flex items-center gap-1 text-[11px] text-gray-500 px-1.5 py-0.5">
              <span className="w-4 h-4 rounded-full bg-gray-800 flex items-center justify-center text-[9px] text-gray-500">2</span>
              Build
            </span>
            <div className="w-3 h-[1px] bg-gray-700 mx-0.5" />
            <a href="https://pitchdeckforge.vercel.app" className="flex items-center gap-1 text-[11px] text-gray-500 hover:text-orange-400 transition px-1.5 py-0.5">
              <span className="w-4 h-4 rounded-full bg-gray-800 flex items-center justify-center text-[9px] text-gray-500">3</span>
              Deck
            </a>
            <div className="w-3 h-[1px] bg-gray-700 mx-0.5" />
            <span className="flex items-center gap-1 text-[11px] font-semibold text-violet-400 bg-violet-500/10 px-2 py-0.5 rounded-full">
              <span className="w-4 h-4 rounded-full bg-violet-500 flex items-center justify-center text-[9px] font-bold text-white">4</span>
              Pipeline
            </span>
            <div className="w-3 h-[1px] bg-gray-700 mx-0.5" />
            <a href="https://contract-concierge-pi.vercel.app" className="flex items-center gap-1 text-[11px] text-gray-500 hover:text-emerald-400 transition px-1.5 py-0.5">
              <span className="w-4 h-4 rounded-full bg-gray-800 flex items-center justify-center text-[9px] text-gray-500">5</span>
              Contracts
            </a>
          </div>
        </div>
      </div>
      <nav className="border-b border-gray-800 bg-[#0a0a0f]/80 backdrop-blur-sm sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between">
          <button onClick={() => setView('home')} className="flex items-center gap-2 text-lg font-semibold text-white hover:text-violet-400 transition">
            <TrendingUp size={20} className="text-violet-500" /> DealFlowTracker
          </button>
          <div className="flex items-center gap-4">
            <button onClick={() => setView('submit')} className="text-sm text-gray-400 hover:text-white transition">Submit a Deal</button>
            <button onClick={() => setView('pricing')} className="text-sm text-gray-400 hover:text-white transition">Pricing</button>
            {token && user ? (
              <>
                <button onClick={() => setView('pipeline')} className="text-sm text-gray-400 hover:text-white transition">Pipeline</button>
                <button onClick={() => setView('contacts')} className="text-sm text-gray-400 hover:text-white transition">Contacts</button>
                <button onClick={() => setView('analytics')} className="text-sm text-gray-400 hover:text-white transition">Analytics</button>
                <button onClick={() => setView('brain')} className="text-sm text-gray-400 hover:text-white transition" title="Ask Rigby (u-d-b PA)">Brain</button>
                <span className="text-sm text-gray-500">{user.name}</span>
                <button onClick={logout} className="text-gray-500 hover:text-red-400"><LogOut size={16} /></button>
              </>
            ) : (
              <button onClick={() => setView('login')} className="text-sm bg-violet-600 hover:bg-violet-500 px-3 py-1.5 rounded-lg text-white transition flex items-center gap-1"><LogIn size={14} /> Sign In</button>
            )}
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-4 py-8">
        {view === 'home' && <HomePage onNavigate={setView} />}
        {view === 'pipeline' && <PipelinePage deals={deals} onOpen={openDeal} onImport={importFromFounderProject} token={token} loading={loading} />}
        {view === 'deal-detail' && activeDeal && <DealDetailPage deal={activeDeal} token={token!} onBack={() => setView('pipeline')} onMove={moveStage} onScore={updateScorecard} onMemo={generateMemo} onNote={addNote} loading={loading} onFetchContacts={fetchDealContacts} onLinkContact={linkContactToDeal} />}
        {view === 'submit' && <SubmitPage onSubmit={submitDeal} />}
        {view === 'analytics' && token && <AnalyticsPage token={token} />}
        {view === 'contacts' && token && <ContactsPage token={token} />}
        {view === 'pricing' && <PricingPage onNavigate={setView} />}
        {view === 'login' && <AuthPage mode="login" onLogin={handleLogin} onSwitch={() => setView('register')} />}
        {view === 'register' && <AuthPage mode="register" onRegister={handleRegister} onSwitch={() => setView('login')} />}
        {view === 'brain' && <BrainPage token={token} onLogin={() => setView('login')} />}
      </main>
    </div>
  )
}

function HomePage({ onNavigate }: { onNavigate: (v: View) => void }) {
  return (
    <div className="text-center py-16 space-y-6">
      <h1 className="text-5xl font-bold bg-gradient-to-r from-violet-400 via-purple-400 to-fuchsia-400 bg-clip-text text-transparent">Track Your Deal Flow</h1>
      <p className="text-xl text-gray-400 max-w-2xl mx-auto">Lightweight deal pipeline for angels and VCs. Intake, triage, score, and generate investment memos — all in one place.</p>
      <div className="flex gap-3 justify-center">
        <button onClick={() => onNavigate('pipeline')} className="bg-violet-600 hover:bg-violet-500 text-white px-6 py-3 rounded-xl transition flex items-center gap-2">View Pipeline <ChevronRight size={20} /></button>
        <button onClick={() => onNavigate('submit')} className="bg-gray-800 hover:bg-gray-700 text-white px-6 py-3 rounded-xl transition">Submit a Deal</button>
      </div>
    </div>
  )
}

// ── Kanban Pipeline ──────────────────────────────────────────────────────

function PipelinePage({ deals, onOpen, onImport, token, loading }: {
  deals: Deal[]; onOpen: (id: string) => void
  onImport: (projectId: string) => void; token: string | null; loading: boolean
}) {
  const [founderProjects, setFounderProjects] = useState<Array<{id: string; title: string; stage: string; deck_summary: Record<string, string> | null; mentor_notes: Record<string, string> | null}>>([])
  const [showImport, setShowImport] = useState(false)

  useEffect(() => {
    if (showImport && token) {
      fetch(`${API}/founder-projects`, { headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` } })
        .then(r => r.json()).then(d => setFounderProjects(d.projects || [])).catch(() => {})
    }
  }, [showImport, token])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Deal Pipeline</h1>
        <button onClick={() => setShowImport(!showImport)} className="text-sm bg-indigo-600 hover:bg-indigo-500 px-3 py-1.5 rounded-lg text-white transition flex items-center gap-1">
          <Download size={14} /> Import from Project
        </button>
      </div>
      {showImport && (
        <div className="bg-[#12121a] border border-indigo-500/30 rounded-xl p-4 space-y-3">
          <div className="text-sm font-medium text-indigo-400">Import from Founder Project</div>
          <p className="text-xs text-gray-500">Create a deal from a Founder Project with mentor notes and deck data.</p>
          {founderProjects.length === 0 ? (
            <p className="text-xs text-gray-500">No founder projects found. Create one in MentorForge first.</p>
          ) : (
            <div className="space-y-2">
              {founderProjects.filter(p => !p.deck_summary || p.stage !== 'deal_opened').map(fp => (
                <div key={fp.id} className="flex items-center justify-between bg-[#0a0a0f] border border-gray-800 rounded-lg p-3">
                  <div>
                    <div className="text-sm text-white font-medium">{fp.title}</div>
                    <div className="text-xs text-gray-500">
                      Stage: {fp.stage} {fp.deck_summary ? `| Deck: ${fp.deck_summary.slide_count} slides` : ''}
                    </div>
                  </div>
                  <button onClick={() => { onImport(fp.id); setShowImport(false) }}
                    disabled={loading}
                    className="text-xs bg-violet-600 hover:bg-violet-500 disabled:bg-gray-700 text-white px-3 py-1.5 rounded-lg transition">
                    {loading ? 'Importing...' : 'Create Deal'}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      <div className="grid grid-cols-6 gap-3 min-h-[500px]">
        {STAGES.map(stage => {
          const stageDeals = deals.filter(d => d.stage === stage)
          return (
            <div key={stage} className="space-y-2">
              <div className={`text-xs font-medium text-gray-400 uppercase tracking-wider pb-2 border-b-2 ${STAGE_COLORS[stage]}`}>
                {STAGE_LABELS[stage]} ({stageDeals.length})
              </div>
              {stageDeals.map(d => (
                <button key={d.id} onClick={() => onOpen(d.id)} className="w-full text-left bg-[#12121a] border border-gray-800 rounded-lg p-3 hover:border-violet-500/50 transition">
                  <div className="text-sm font-medium text-white truncate">{d.company_name}</div>
                  <div className="text-xs text-gray-500 mt-1 truncate">{d.one_liner}</div>
                  <div className="flex items-center justify-between mt-2">
                    <span className="text-xs text-gray-600">{d.sector}</span>
                    {d.score_avg > 0 && <span className="text-xs text-amber-400 flex items-center gap-0.5"><Star size={10} /> {d.score_avg}</span>}
                  </div>
                  {d.raise_amount && <div className="text-xs text-green-400 mt-1">{d.raise_amount}</div>}
                </button>
              ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Deal Detail ──────────────────────────────────────────────────────────

function DealDetailPage({ deal, token, onBack, onMove, onScore, onMemo, onNote, loading, onFetchContacts, onLinkContact }: {
  deal: Deal; token: string; onBack: () => void; onMove: (id: string, s: string) => void; onScore: (id: string, sc: Record<string, number>) => void
  onMemo: (id: string) => void; onNote: (id: string, c: string) => void; loading: boolean
  onFetchContacts: (dealId: string) => Promise<DealContactInfo[]>; onLinkContact: (dealId: string, contactId: string, role: string) => void
}) {
  const [sc, setSc] = useState(deal.scorecard || { team: 0, market: 0, traction: 0, defensibility: 0, fit: 0 })
  const [note, setNote] = useState('')
  const [exporting, setExporting] = useState(false)
  const [dealContacts, setDealContacts] = useState<DealContactInfo[]>([])
  const [allContacts, setAllContacts] = useState<ContactInfo[]>([])
  const [showLinkContact, setShowLinkContact] = useState(false)

  useEffect(() => {
    onFetchContacts(deal.id).then(setDealContacts)
    fetch(`${API}/contacts`, { headers: authHeaders(token) }).then(r => r.json()).then(d => setAllContacts(d.contacts || []))
  }, [deal.id])

  function exportMemoPDF() {
    if (!deal.memo) return
    setExporting(true)
    try {
      const pdf = new jsPDF({ unit: 'pt', format: 'a4' })
      pdf.setFillColor(18, 18, 26); pdf.rect(0, 0, 595, 842, 'F')
      pdf.setTextColor(139, 92, 246); pdf.setFontSize(22)
      pdf.text(`Investment Memo: ${deal.company_name}`, 40, 50)
      pdf.setTextColor(156, 163, 175); pdf.setFontSize(10)
      pdf.text(`${deal.sector} | ${deal.raise_amount} | Score: ${deal.score_avg || 'N/A'} | Stage: ${STAGE_LABELS[deal.stage]}`, 40, 72)
      pdf.setTextColor(209, 213, 219); pdf.setFontSize(11)
      const lines = pdf.splitTextToSize(deal.memo, 515)
      pdf.text(lines, 40, 100)
      if (dealContacts.length > 0) {
        const contactY = Math.min(100 + lines.length * 14 + 30, 750)
        pdf.setTextColor(139, 92, 246); pdf.setFontSize(14)
        pdf.text('Key Contacts', 40, contactY)
        pdf.setTextColor(209, 213, 219); pdf.setFontSize(10)
        dealContacts.forEach((c, i) => {
          pdf.text(`${c.name} — ${c.firm || 'N/A'} (${c.role_in_deal}) ${c.email || ''}`, 40, contactY + 20 + i * 16)
        })
      }
      pdf.save(`memo-${deal.company_name.toLowerCase().replace(/\s+/g, '-')}.pdf`)
    } finally { setExporting(false) }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <button onClick={onBack} className="text-sm text-gray-400 hover:text-white transition flex items-center gap-1"><ArrowLeft size={16} /> Pipeline</button>
        {deal.memo && (
          <button onClick={exportMemoPDF} disabled={exporting} className="text-xs px-3 py-1.5 rounded-lg bg-green-600/20 border border-green-500/30 text-green-400 hover:bg-green-600/30 transition flex items-center gap-1 disabled:opacity-50">
            {exporting ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />} Export Memo PDF
          </button>
        )}
      </div>
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">{deal.company_name}</h1>
          <p className="text-gray-400 mt-1">{deal.one_liner}</p>
          <div className="flex items-center gap-4 mt-2 text-sm text-gray-500">
            <span>{deal.sector}</span>
            {deal.raise_amount && <span className="text-green-400">{deal.raise_amount}</span>}
            {deal.founder_name && <span>Founder: {deal.founder_name}</span>}
            {deal.deck_url && <a href={deal.deck_url} target="_blank" rel="noreferrer" className="text-violet-400 flex items-center gap-1"><ExternalLink size={12} /> Deck</a>}
          </div>
        </div>
        <select value={deal.stage} onChange={e => onMove(deal.id, e.target.value)} className="px-3 py-1.5 bg-[#12121a] border border-gray-800 rounded-lg text-sm text-white">
          {STAGES.map(s => <option key={s} value={s}>{STAGE_LABELS[s]}</option>)}
        </select>
      </div>

      <div className="grid md:grid-cols-3 gap-6">
        <div className="md:col-span-2 space-y-4">
          {/* Scorecard */}
          <div className="bg-[#12121a] border border-gray-800 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-white mb-3">Scorecard</h2>
            <div className="grid grid-cols-5 gap-3">
              {(['team', 'market', 'traction', 'defensibility', 'fit'] as const).map(key => (
                <div key={key} className="text-center">
                  <div className="text-xs text-gray-500 capitalize mb-1">{key}</div>
                  <div className="flex justify-center gap-0.5">
                    {[1, 2, 3, 4, 5].map(v => (
                      <button key={v} onClick={() => setSc({ ...sc, [key]: v })} className={`w-5 h-5 rounded text-xs ${sc[key] >= v ? 'bg-amber-500 text-black' : 'bg-gray-800 text-gray-600'}`}>{v}</button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            <button onClick={() => onScore(deal.id, sc)} className="mt-3 text-xs bg-violet-600 hover:bg-violet-500 px-3 py-1 rounded text-white transition">Save Scorecard</button>
          </div>

          {/* Memo */}
          <div className="bg-[#12121a] border border-gray-800 rounded-xl p-5">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-white flex items-center gap-2"><FileText size={14} /> Investment Memo</h2>
              <button onClick={() => onMemo(deal.id)} disabled={loading} className="text-xs bg-violet-600/10 border border-violet-500/20 text-violet-400 px-3 py-1 rounded hover:bg-violet-600/20 transition disabled:opacity-50 flex items-center gap-1">
                <Sparkles size={12} /> {loading ? 'Generating...' : 'Generate Memo'}
              </button>
            </div>
            {deal.memo ? <div className="text-sm text-gray-300 whitespace-pre-wrap leading-relaxed">{deal.memo}</div> : <p className="text-sm text-gray-500">No memo yet. Click generate to create one.</p>}
          </div>

          {/* Contacts linked to deal */}
          <div className="bg-[#12121a] border border-gray-800 rounded-xl p-5">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-white flex items-center gap-2"><Users size={14} /> Contacts</h2>
              <button onClick={() => setShowLinkContact(!showLinkContact)} className="text-xs text-violet-400 hover:text-violet-300 flex items-center gap-1"><UserPlus size={12} /> Link Contact</button>
            </div>
            {showLinkContact && (
              <div className="mb-3 space-y-1 max-h-32 overflow-y-auto">
                {allContacts.filter(c => !dealContacts.some(dc => dc.id === c.id)).map(c => (
                  <button key={c.id} onClick={() => { onLinkContact(deal.id, c.id, 'investor'); setShowLinkContact(false) }}
                    className="w-full text-left text-xs px-2 py-1.5 bg-[#0a0a0f] rounded hover:bg-violet-600/10 text-gray-300 flex items-center gap-2">
                    <Link size={10} className="text-violet-400" /> {c.name} {c.firm && `(${c.firm})`}
                  </button>
                ))}
                {allContacts.filter(c => !dealContacts.some(dc => dc.id === c.id)).length === 0 && <p className="text-xs text-gray-600">No unlinked contacts</p>}
              </div>
            )}
            {dealContacts.length > 0 ? (
              <div className="space-y-2">
                {dealContacts.map(c => (
                  <div key={c.id} className="flex items-center justify-between bg-[#0a0a0f] rounded-lg p-2">
                    <div>
                      <span className="text-sm text-white">{c.name}</span>
                      {c.firm && <span className="text-xs text-gray-500 ml-2">{c.firm}</span>}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs px-2 py-0.5 bg-violet-600/20 text-violet-400 rounded">{c.role_in_deal}</span>
                      {c.email && <span className="text-xs text-gray-500">{c.email}</span>}
                    </div>
                  </div>
                ))}
              </div>
            ) : <p className="text-sm text-gray-500">No contacts linked yet</p>}
          </div>

          {/* Notes */}
          <div className="bg-[#12121a] border border-gray-800 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-2"><MessageSquare size={14} /> Notes</h2>
            {deal.notes && <div className="text-sm text-gray-400 whitespace-pre-wrap mb-3">{deal.notes}</div>}
            <form onSubmit={e => { e.preventDefault(); if (note.trim()) { onNote(deal.id, note); setNote('') } }} className="flex gap-2">
              <input type="text" value={note} onChange={e => setNote(e.target.value)} placeholder="Add a note..." className="flex-1 px-3 py-2 bg-[#0a0a0f] border border-gray-800 rounded-lg text-sm text-white focus:outline-none focus:border-violet-500" />
              <button type="submit" className="px-3 py-2 bg-violet-600 hover:bg-violet-500 text-white rounded-lg text-sm transition">Add</button>
            </form>
          </div>
        </div>

        {/* Activity */}
        <div className="bg-[#12121a] border border-gray-800 rounded-xl p-5 h-fit">
          <h2 className="text-sm font-semibold text-white mb-3">Activity</h2>
          {deal.activities && deal.activities.length > 0 ? (
            <div className="space-y-2">
              {deal.activities.map(a => (
                <div key={a.id} className="flex items-start gap-2">
                  <div className="w-1.5 h-1.5 rounded-full bg-violet-500 mt-1.5 shrink-0" />
                  <div>
                    <div className="text-xs text-white">{a.content}</div>
                    <div className="text-xs text-gray-600">{new Date(a.created_at).toLocaleString()}</div>
                  </div>
                </div>
              ))}
            </div>
          ) : <p className="text-sm text-gray-500">No activity yet</p>}
        </div>
      </div>
    </div>
  )
}

// ── Submit (public) ──────────────────────────────────────────────────────

function SubmitPage({ onSubmit }: { onSubmit: (d: Record<string, string>) => void }) {
  const [form, setForm] = useState({ company_name: '', one_liner: '', sector: '', raise_amount: '', traction: '', founder_name: '', founder_email: '', website: '', deck_url: '' })
  return (
    <div className="max-w-lg mx-auto space-y-6">
      <h1 className="text-2xl font-bold text-white text-center">Submit Your Startup</h1>
      <form onSubmit={e => { e.preventDefault(); if (form.company_name) onSubmit(form) }} className="bg-[#12121a] border border-gray-800 rounded-xl p-6 space-y-4">
        {[
          { key: 'company_name', label: 'Company Name *', ph: 'Acme Inc' },
          { key: 'one_liner', label: 'One-liner', ph: 'What do you do in one sentence?' },
          { key: 'sector', label: 'Sector', ph: 'e.g. FinTech, HealthTech, AI' },
          { key: 'raise_amount', label: 'Raise Amount', ph: 'e.g. $2M' },
          { key: 'traction', label: 'Traction', ph: 'Key metrics: users, revenue, growth' },
          { key: 'founder_name', label: 'Founder Name', ph: 'Your name' },
          { key: 'founder_email', label: 'Founder Email', ph: 'you@company.com' },
          { key: 'website', label: 'Website', ph: 'https://...' },
          { key: 'deck_url', label: 'Deck URL', ph: 'Link to your pitch deck' },
        ].map(f => (
          <div key={f.key}>
            <label className="text-sm text-gray-400 block mb-1">{f.label}</label>
            <input type="text" value={(form as Record<string, string>)[f.key]} onChange={e => setForm({ ...form, [f.key]: e.target.value })} placeholder={f.ph}
              required={f.key === 'company_name'} className="w-full px-3 py-2 bg-[#0a0a0f] border border-gray-800 rounded-lg text-sm text-white focus:outline-none focus:border-violet-500" />
          </div>
        ))}
        <button type="submit" className="w-full py-3 bg-violet-600 hover:bg-violet-500 text-white rounded-xl font-medium transition">Submit</button>
      </form>
    </div>
  )
}

// ── Analytics ────────────────────────────────────────────────────────────

function AnalyticsPage({ token }: { token: string }) {
  const [data, setData] = useState<Analytics | null>(null)
  useEffect(() => {
    fetch(`${API}/analytics`, { headers: authHeaders(token) }).then(r => r.json()).then(setData)
  }, [])

  if (!data) return <div className="text-center py-16 text-gray-500">Loading analytics...</div>

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white flex items-center gap-2"><BarChart3 size={22} className="text-violet-400" /> Analytics</h1>

      {/* KPI cards */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: 'Total Deals', value: data.total_deals, color: 'text-violet-400' },
          { label: 'Win Rate', value: `${data.win_rate}%`, color: 'text-green-400' },
          { label: 'Avg Score', value: data.avg_score || 'N/A', color: 'text-amber-400' },
          { label: 'Contacts', value: data.total_contacts, color: 'text-blue-400' },
        ].map(k => (
          <div key={k.label} className="bg-[#12121a] border border-gray-800 rounded-xl p-5 text-center">
            <div className={`text-3xl font-bold ${k.color}`}>{k.value}</div>
            <div className="text-xs text-gray-500 mt-1">{k.label}</div>
          </div>
        ))}
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        {/* Pipeline funnel */}
        <div className="bg-[#12121a] border border-gray-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-white mb-4">Pipeline Funnel</h2>
          <div className="space-y-2">
            {data.funnel.map((f, i) => {
              const maxCount = Math.max(...data.funnel.map(x => x.count), 1)
              const width = Math.max((f.count / maxCount) * 100, 8)
              return (
                <div key={f.stage} className="flex items-center gap-3">
                  <div className="w-20 text-xs text-gray-400 text-right">{f.label}</div>
                  <div className="flex-1 h-7 bg-[#0a0a0f] rounded overflow-hidden">
                    <div className="h-full rounded flex items-center px-2" style={{ width: `${width}%`, backgroundColor: ['#8b5cf6', '#6366f1', '#a78bfa', '#c084fc', '#22c55e'][i] || '#8b5cf6' }}>
                      <span className="text-xs text-white font-medium">{f.count}</span>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Stage breakdown */}
        <div className="bg-[#12121a] border border-gray-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-white mb-4">By Stage</h2>
          <div className="space-y-2">
            {Object.entries(data.by_stage).map(([stage, count]) => (
              <div key={stage} className="flex items-center justify-between">
                <span className="text-sm text-gray-300">{STAGE_LABELS[stage] || stage}</span>
                <span className="text-sm font-medium text-white">{count}</span>
              </div>
            ))}
          </div>
          <div className="mt-4 pt-3 border-t border-gray-800 flex justify-between">
            <span className="text-xs text-gray-500">Deals with memos</span>
            <span className="text-xs text-violet-400">{data.deals_with_memos}</span>
          </div>
        </div>

        {/* Top sectors */}
        <div className="bg-[#12121a] border border-gray-800 rounded-xl p-5 md:col-span-2">
          <h2 className="text-sm font-semibold text-white mb-4">Top Sectors</h2>
          <div className="flex flex-wrap gap-2">
            {data.top_sectors.map(s => (
              <div key={s.sector} className="px-3 py-2 bg-violet-600/10 border border-violet-500/20 rounded-lg">
                <span className="text-sm text-white">{s.sector}</span>
                <span className="text-xs text-violet-400 ml-2">{s.count} deals</span>
              </div>
            ))}
            {data.top_sectors.length === 0 && <p className="text-sm text-gray-500">No sector data yet</p>}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Contacts ────────────────────────────────────────────────────────────

function ContactsPage({ token }: { token: string }) {
  const [contacts, setContacts] = useState<ContactInfo[]>([])
  const [search, setSearch] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ name: '', firm: '', role: '', email: '', phone: '', notes: '' })

  useEffect(() => { loadContacts() }, [search])

  function loadContacts() {
    const params = search ? `?q=${encodeURIComponent(search)}` : ''
    fetch(`${API}/contacts${params}`, { headers: authHeaders(token) }).then(r => r.json()).then(d => setContacts(d.contacts || []))
  }

  async function createContact() {
    if (!form.name) return
    await fetch(`${API}/contacts`, { method: 'POST', headers: authHeaders(token), body: JSON.stringify(form) })
    setForm({ name: '', firm: '', role: '', email: '', phone: '', notes: '' })
    setShowForm(false)
    loadContacts()
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white flex items-center gap-2"><Users size={22} className="text-violet-400" /> Contacts</h1>
        <button onClick={() => setShowForm(!showForm)} className="text-sm bg-violet-600 hover:bg-violet-500 px-3 py-1.5 rounded-lg text-white transition flex items-center gap-1">
          <Plus size={14} /> Add Contact
        </button>
      </div>

      {/* Search */}
      <div className="relative">
        <Search size={16} className="absolute left-3 top-2.5 text-gray-500" />
        <input type="text" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search contacts..."
          className="w-full pl-9 pr-3 py-2 bg-[#12121a] border border-gray-800 rounded-lg text-sm text-white focus:outline-none focus:border-violet-500" />
      </div>

      {/* Create form */}
      {showForm && (
        <div className="bg-[#12121a] border border-gray-800 rounded-xl p-5 space-y-3">
          <h2 className="text-sm font-semibold text-white">New Contact</h2>
          <div className="grid grid-cols-2 gap-3">
            {[
              { key: 'name', ph: 'Name *' }, { key: 'firm', ph: 'Firm' }, { key: 'role', ph: 'Role (e.g. Partner)' },
              { key: 'email', ph: 'Email' }, { key: 'phone', ph: 'Phone' },
            ].map(f => (
              <input key={f.key} type="text" value={(form as Record<string, string>)[f.key]} onChange={e => setForm({ ...form, [f.key]: e.target.value })}
                placeholder={f.ph} className="px-3 py-2 bg-[#0a0a0f] border border-gray-800 rounded-lg text-sm text-white focus:outline-none focus:border-violet-500" />
            ))}
          </div>
          <textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} placeholder="Notes..."
            className="w-full px-3 py-2 bg-[#0a0a0f] border border-gray-800 rounded-lg text-sm text-white focus:outline-none focus:border-violet-500 resize-y" rows={2} />
          <button onClick={createContact} className="px-4 py-2 bg-violet-600 hover:bg-violet-500 text-white rounded-lg text-sm transition">Save Contact</button>
        </div>
      )}

      {/* Contact list */}
      {contacts.length === 0 ? (
        <div className="text-center py-16"><Users size={48} className="text-gray-600 mx-auto mb-4" /><p className="text-gray-400">No contacts yet</p></div>
      ) : (
        <div className="space-y-2">
          {contacts.map(c => (
            <div key={c.id} className="bg-[#12121a] border border-gray-800 rounded-lg p-4 flex items-center justify-between hover:border-violet-500/30 transition">
              <div>
                <div className="text-sm font-medium text-white">{c.name}</div>
                <div className="text-xs text-gray-500 mt-0.5">
                  {c.firm && <span>{c.firm}</span>}
                  {c.role && <span className="ml-2">({c.role})</span>}
                </div>
              </div>
              <div className="flex items-center gap-4 text-xs text-gray-500">
                {c.email && <span>{c.email}</span>}
                {c.phone && <span>{c.phone}</span>}
                {c.tags?.length > 0 && c.tags.map(t => <span key={t} className="px-2 py-0.5 bg-violet-600/10 text-violet-400 rounded">{t}</span>)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Pricing ──────────────────────────────────────────────────────────────

function PricingPage({ onNavigate }: { onNavigate: (v: View) => void }) {
  const plans = [
    {
      name: 'Starter',
      price: 'Free',
      period: '',
      desc: 'For angels tracking a few deals',
      features: ['Up to 10 active deals', 'Kanban pipeline', '5-dimension scorecards', 'AI investment memos', 'Activity timeline', 'Public submission form'],
      cta: 'Get Started',
      action: () => onNavigate('pipeline'),
      color: 'gray',
      popular: false,
    },
    {
      name: 'Pro',
      price: '$39',
      period: '/mo',
      desc: 'For active investors and small funds',
      features: ['Unlimited deals', 'Investor contact management', 'Analytics dashboard', 'Conversion funnel tracking', 'PDF memo export', 'Deal-contact linking', 'Priority AI generation', 'PitchDeckForge integration'],
      cta: 'Subscribe — $39/mo',
      plan: 'pro_monthly',
      action: () => {},
      color: 'violet',
      popular: true,
    },
    {
      name: 'Fund',
      price: '$99',
      period: '/mo',
      desc: 'For VC funds and syndicates',
      features: ['Everything in Pro', 'Up to 10 team members', 'Shared pipeline & scorecards', 'LP reporting exports', 'Custom submission branding', 'API access', 'Bulk import/export', 'Dedicated support'],
      cta: 'Subscribe — $99/mo',
      plan: 'team_monthly',
      action: () => {},
      color: 'purple',
      popular: false,
    },
  ]

  return (
    <div className="space-y-12 py-8">
      <div className="text-center space-y-4">
        <h1 className="text-4xl font-bold text-white">Simple Deal Tracking</h1>
        <p className="text-lg text-gray-400 max-w-xl mx-auto">From angel checks to fund operations — scale your deal flow.</p>
      </div>

      <div className="grid md:grid-cols-3 gap-6 max-w-4xl mx-auto">
        {plans.map(plan => (
          <div key={plan.name} className={`relative bg-[#12121a] rounded-xl p-6 flex flex-col ${
            plan.popular ? 'border-2 border-violet-500 ring-1 ring-violet-500/20' : 'border border-gray-800'
          }`}>
            {plan.popular && (
              <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-violet-600 text-white text-xs px-3 py-1 rounded-full flex items-center gap-1">
                <Star size={10} /> Most Popular
              </div>
            )}
            <div className="mb-6">
              <h3 className="text-lg font-semibold text-white flex items-center gap-2">
                {plan.color === 'gray' && <Zap size={16} className="text-gray-400" />}
                {plan.color === 'violet' && <CreditCard size={16} className="text-violet-400" />}
                {plan.color === 'purple' && <Building size={16} className="text-purple-400" />}
                {plan.name}
              </h3>
              <div className="mt-2">
                <span className="text-3xl font-bold text-white">{plan.price}</span>
                {plan.period && <span className="text-gray-500 text-sm">{plan.period}</span>}
              </div>
              <p className="text-sm text-gray-400 mt-2">{plan.desc}</p>
            </div>

            <ul className="space-y-2 mb-6 flex-1">
              {plan.features.map(f => (
                <li key={f} className="text-sm text-gray-300 flex items-start gap-2">
                  <Check size={14} className={`mt-0.5 shrink-0 ${
                    plan.color === 'violet' ? 'text-violet-400' : plan.color === 'purple' ? 'text-purple-400' : 'text-gray-500'
                  }`} />
                  {f}
                </li>
              ))}
            </ul>

            <button onClick={async () => {
                if (plan.name === 'Starter') { plan.action(); return }
                const token = localStorage.getItem('df_token')
                if (!token) { onNavigate('login'); return }
                try {
                  const r = await fetch(`${API.replace('/api', '')}/api/stripe/checkout`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                    body: JSON.stringify({ plan: (plan as any).plan }),
                  })
                  const data = await r.json()
                  if (data.url) window.location.href = data.url
                  else alert(data.detail || 'Failed to start checkout')
                } catch { alert('Checkout unavailable — please try again') }
              }}
              className={`w-full py-2.5 rounded-lg font-medium transition text-sm ${
                plan.name === 'Starter'
                  ? 'bg-gray-800 hover:bg-gray-700 text-white'
                  : plan.popular
                    ? 'bg-violet-600 hover:bg-violet-500 text-white'
                    : 'bg-purple-600 hover:bg-purple-500 text-white'
              }`}>
              {plan.cta}
            </button>
          </div>
        ))}
      </div>

      <div className="text-center text-sm text-gray-500">
        Payment integration coming soon. All features available during beta.
      </div>
    </div>
  )
}

// ── Auth ──────────────────────────────────────────────────────────────────

function AuthPage({ mode, onLogin, onRegister, onSwitch }: {
  mode: 'login' | 'register'; onLogin?: (e: string, p: string) => Promise<void>; onRegister?: (e: string, p: string, n: string) => Promise<void>; onSwitch: () => void
}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState(''); const [error, setError] = useState(''); const [ld, setLd] = useState(false)
  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault(); setError(''); setLd(true)
    try { if (mode === 'login' && onLogin) await onLogin(email, password); else if (onRegister) await onRegister(email, password, name) }
    catch { setError('Failed') }; setLd(false)
  }
  return (
    <div className="max-w-sm mx-auto py-16">
      <div className="bg-[#12121a] border border-gray-800 rounded-xl p-6">
        <h1 className="text-xl font-bold text-white mb-6 text-center">{mode === 'login' ? 'Sign In' : 'Create Account'}</h1>
        <form onSubmit={handleSubmit} className="space-y-4">
          {mode === 'register' && <input type="text" placeholder="Name" value={name} onChange={e => setName(e.target.value)} required className="w-full px-3 py-2 bg-[#0a0a0f] border border-gray-800 rounded-lg text-white text-sm focus:outline-none focus:border-violet-500" />}
          <input type="email" placeholder="Email" value={email} onChange={e => setEmail(e.target.value)} required className="w-full px-3 py-2 bg-[#0a0a0f] border border-gray-800 rounded-lg text-white text-sm focus:outline-none focus:border-violet-500" />
          <input type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} required className="w-full px-3 py-2 bg-[#0a0a0f] border border-gray-800 rounded-lg text-white text-sm focus:outline-none focus:border-violet-500" />
          {error && <p className="text-sm text-red-400">{error}</p>}
          {/* Demo hint removed for production */}
          <button type="submit" disabled={ld} className="w-full py-2.5 bg-violet-600 hover:bg-violet-500 text-white rounded-lg font-medium transition disabled:opacity-50">{ld ? '...' : mode === 'login' ? 'Sign In' : 'Create Account'}</button>
        </form>
        <p className="text-sm text-gray-500 text-center mt-4">{mode === 'login' ? "No account? " : 'Have one? '}<button onClick={onSwitch} className="text-violet-400 hover:text-violet-300">{mode === 'login' ? 'Sign Up' : 'Sign In'}</button></p>
      </div>
    </div>
  )
}

// ── Brain bridge page ─────────────────────────────────────────────────────
function BrainPage({ token, onLogin }: { token: string | null; onLogin: () => void }) {
  const [message, setMessage] = useState('')
  const [answer, setAnswer] = useState<string | null>(null)
  const [traceId, setTraceId] = useState<string | null>(null)
  const [latency, setLatency] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function ask() {
    if (!token) { onLogin(); return }
    if (!message.trim()) return
    setLoading(true); setAnswer(null); setError(null); setTraceId(null); setLatency(null)
    try {
      const r = await fetch(`${API}/brain/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ message }),
      })
      const d = await r.json()
      if (!r.ok) setError(typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail || d))
      else { setAnswer(d.answer || '(no answer field returned)'); setTraceId(d.trace_id || null); setLatency(d.latency_ms ?? null) }
    } catch (e: any) { setError(e.message || 'request failed') }
    finally { setLoading(false) }
  }

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-3xl font-bold text-white mb-2">Brain</h1>
      <p className="text-gray-400 mb-6">
        Ask Rigby (the u-d-b Personal Assistant) anything. DealFlowTracker proxies your question through the fleet brain bridge and returns her deliberated response.
      </p>
      {!token && <div className="mb-4 p-3 rounded-lg bg-yellow-900/30 border border-yellow-700/50 text-yellow-200 text-sm">Sign in first — the bridge requires an authenticated session.</div>}
      <textarea value={message} onChange={e => setMessage(e.target.value)}
        placeholder="Ask anything — Rigby has u-d-b's full agent network behind her."
        className="w-full h-32 px-4 py-3 bg-gray-900 border border-gray-700 rounded-lg text-white placeholder-gray-500 resize-none focus:border-violet-500 focus:outline-none" />
      <button onClick={ask} disabled={loading || !message.trim()}
        className="mt-3 px-5 py-2 bg-violet-600 hover:bg-violet-500 disabled:bg-gray-700 disabled:text-gray-500 rounded-lg text-white font-medium transition flex items-center gap-2">
        <Send size={16} />{loading ? 'Thinking...' : 'Ask Rigby'}
      </button>
      {error && <div className="mt-6 p-4 rounded-lg bg-red-900/30 border border-red-700/50 text-red-200 text-sm whitespace-pre-wrap"><div className="font-medium text-red-300 mb-1">Brain unreachable</div>{error}</div>}
      {answer && (
        <div className="mt-6">
          <div className="p-4 rounded-lg bg-gray-900 border border-gray-800 text-gray-100 whitespace-pre-wrap">{answer}</div>
          {(traceId || latency !== null) && (
            <div className="mt-2 text-xs text-gray-500 flex gap-4">
              {traceId && <span>trace: {traceId}</span>}
              {latency !== null && <span>latency: {latency}ms</span>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
