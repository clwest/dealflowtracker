import { useState, useEffect } from 'react'
import { TrendingUp, ArrowLeft, LogIn, LogOut, FileText, Sparkles, Star, ChevronRight, ExternalLink, MessageSquare } from 'lucide-react'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8006/api'
const STAGES = ['new', 'review', 'diligence', 'term_sheet', 'closed_won', 'closed_lost'] as const
const STAGE_LABELS: Record<string, string> = { new: 'New', review: 'Review', diligence: 'Diligence', term_sheet: 'Term Sheet', closed_won: 'Won', closed_lost: 'Lost' }
const STAGE_COLORS: Record<string, string> = { new: 'border-gray-500', review: 'border-blue-500', diligence: 'border-amber-500', term_sheet: 'border-purple-500', closed_won: 'border-green-500', closed_lost: 'border-red-500' }

interface Deal { id: string; stage: string; company_name: string; one_liner: string; sector: string; raise_amount: string; deck_url: string; founder_name: string; scorecard: Record<string, number>; score_avg: number; memo: string | null; notes: string | null; activities?: Activity[] }
interface Activity { id: string; action_type: string; content: string; created_at: string }
interface AuthUser { id: string; email: string; name: string; role: string }
type View = 'home' | 'pipeline' | 'deal-detail' | 'submit' | 'login' | 'register'

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

  return (
    <div className="min-h-screen bg-[#0a0a0f]">
      <nav className="border-b border-gray-800 bg-[#0a0a0f]/80 backdrop-blur-sm sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between">
          <button onClick={() => setView('home')} className="flex items-center gap-2 text-lg font-semibold text-white hover:text-violet-400 transition">
            <TrendingUp size={20} className="text-violet-500" /> DealFlowTracker
          </button>
          <div className="flex items-center gap-4">
            <button onClick={() => setView('submit')} className="text-sm text-gray-400 hover:text-white transition">Submit a Deal</button>
            {token && user ? (
              <>
                <button onClick={() => setView('pipeline')} className="text-sm text-gray-400 hover:text-white transition">Pipeline</button>
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
        {view === 'pipeline' && <PipelinePage deals={deals} onOpen={openDeal} />}
        {view === 'deal-detail' && activeDeal && <DealDetailPage deal={activeDeal} onBack={() => setView('pipeline')} onMove={moveStage} onScore={updateScorecard} onMemo={generateMemo} onNote={addNote} loading={loading} />}
        {view === 'submit' && <SubmitPage onSubmit={submitDeal} />}
        {view === 'login' && <AuthPage mode="login" onLogin={handleLogin} onSwitch={() => setView('register')} />}
        {view === 'register' && <AuthPage mode="register" onRegister={handleRegister} onSwitch={() => setView('login')} />}
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

function PipelinePage({ deals, onOpen }: { deals: Deal[]; onOpen: (id: string) => void }) {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-white">Deal Pipeline</h1>
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

function DealDetailPage({ deal, onBack, onMove, onScore, onMemo, onNote, loading }: {
  deal: Deal; onBack: () => void; onMove: (id: string, s: string) => void; onScore: (id: string, sc: Record<string, number>) => void
  onMemo: (id: string) => void; onNote: (id: string, c: string) => void; loading: boolean
}) {
  const [sc, setSc] = useState(deal.scorecard || { team: 0, market: 0, traction: 0, defensibility: 0, fit: 0 })
  const [note, setNote] = useState('')

  return (
    <div className="space-y-6">
      <button onClick={onBack} className="text-sm text-gray-400 hover:text-white transition flex items-center gap-1"><ArrowLeft size={16} /> Pipeline</button>
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

// ── Auth ──────────────────────────────────────────────────────────────────

function AuthPage({ mode, onLogin, onRegister, onSwitch }: {
  mode: 'login' | 'register'; onLogin?: (e: string, p: string) => Promise<void>; onRegister?: (e: string, p: string, n: string) => Promise<void>; onSwitch: () => void
}) {
  const [email, setEmail] = useState(mode === 'login' ? 'demo@dealflow.dev' : '')
  const [password, setPassword] = useState(mode === 'login' ? 'demo123' : '')
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
          {mode === 'login' && <p className="text-xs text-gray-500">Demo: demo@dealflow.dev / demo123</p>}
          <button type="submit" disabled={ld} className="w-full py-2.5 bg-violet-600 hover:bg-violet-500 text-white rounded-lg font-medium transition disabled:opacity-50">{ld ? '...' : mode === 'login' ? 'Sign In' : 'Create Account'}</button>
        </form>
        <p className="text-sm text-gray-500 text-center mt-4">{mode === 'login' ? "No account? " : 'Have one? '}<button onClick={onSwitch} className="text-violet-400 hover:text-violet-300">{mode === 'login' ? 'Sign Up' : 'Sign In'}</button></p>
      </div>
    </div>
  )
}
