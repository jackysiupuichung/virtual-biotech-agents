
const { useState, useMemo, useRef, useEffect, useCallback } = React;

// ---------- provenance + confidence vocabulary (docs/kg-pareto-provenance-design.md §5) ----------
const PROV = {
  retrieved: { icon: "🗄️", label: "retrieved — public API" },
  computed:  { icon: "🔧", label: "computed — ClawBio skill" },
  web:       { icon: "🌐", label: "agent web / literature" },
  gap:       { icon: "⚪", label: "gap — not available" },
};
// map cso.py provenance icons (🧪 demo, 🔧 clawbio, 🌐 web, ⚪ absent) to a prov key
const ICON_TO_PROV = { "🧪": "computed", "🔧": "computed", "🗄️": "retrieved", "🌐": "web", "⚪": "gap" };
const provOf = (icon) => ICON_TO_PROV[icon] || "computed";

const gradeStyle = (g) => ({
  strong:       "text-emerald-300 border-emerald-500/40 bg-emerald-500/10",
  illustrative: "text-sky-300 border-sky-500/40 bg-sky-500/10",
  supported:    "text-sky-300 border-sky-500/40 bg-sky-500/10",
  suggestive:   "text-amber-300 border-amber-500/40 bg-amber-500/10",
  supporting:   "text-amber-300 border-amber-500/40 bg-amber-500/10",
  absent:       "text-slate-400 border-slate-600/40 bg-slate-700/20",
  insufficient: "text-slate-400 border-slate-600/40 bg-slate-700/20",
}[g] || "text-slate-400 border-slate-600/40 bg-slate-700/20");

const DECISION = {
  GO:             { c: "bg-emerald-500 text-emerald-950", ring:"ring-emerald-400/40" },
  CONDITIONAL_GO: { c: "bg-amber-400 text-amber-950",     ring:"ring-amber-300/40" },
  REVIEW:         { c: "bg-sky-400 text-sky-950",         ring:"ring-sky-300/40" },
  NO_GO:          { c: "bg-rose-500 text-rose-950",       ring:"ring-rose-400/40" },
  PENDING:        { c: "bg-slate-600 text-slate-100",     ring:"ring-slate-500/40" },
};

const EXAMPLES = [
  "Assess B7-H3 potential as a therapeutic target in lung cancer",
  "Evaluate MET as a target in lung adenocarcinoma",
  "Is CEACAM5 a viable ADC target in NSCLC?",
];

// ======================================================================================
//  Live run state — reduced from the SSE event stream
// ======================================================================================
const emptyRun = () => ({
  status: "idle",            // idle | running | done | error
  meta: null,                // {query, backend, model, calls_llm, mode, run_id, entities}
  steps: [],                 // ordered loop steps (each: {id, role, kind, division, title, status, ...})
  evidence: {},              // step id -> normalized evidence event
  gnodes: {},                // canonical graph nodes streamed from the server, by id
  gedges: {},                // canonical graph edges streamed from the server, by id
  briefing: null,
  review: null,
  synthesis: null,
  report_md: null,
  decision: "PENDING",
  decisionSource: null,       // "prometheux" | "agent"
  decisionEngine: null,       // {tier, score, max_score, axes, explanation, facts}
  agentDecision: null,        // the synthesis agent's proposed tier (for divergence)
  diverges: false,            // engine tier != agent tier
  engineGaps: [],             // Prometheux structural gaps (the non-silenceable voice)
  engineForced: false,        // a structural gap forced the re-route
  panel: null,                // latest 4-lens reviewer-panel vote {lenses, reroute_votes, n_lenses}
  divisionFindings: {},       // division name -> division_finding event
  confidence: "n/a",
  checkpoint: null,           // HITL: {run_id, iteration, verdict, panel, gaps, proposed_reroute} while awaiting a human
  error: null,
});

function reduceEvent(run, ev, data) {
  const r = { ...run, steps: [...run.steps], evidence: { ...run.evidence },
              gnodes: { ...run.gnodes }, gedges: { ...run.gedges } };
  switch (ev) {
    case "start":
      return { ...emptyRun(), status: "running", meta: data };
    case "node":
      r.gnodes[data.id] = data;
      return r;
    case "edge":
      r.gedges[data.id] = data;
      return r;
    case "phase": {
      // mark any previously-running step complete, then append this one as running
      r.steps = r.steps.map(s => s.status === "running" ? { ...s, status: "done" } : s);
      r.steps.push({ ...data });
      return r;
    }
    case "briefing":
      r.briefing = data.briefing;
      return r;
    case "evidence": {
      r.evidence[data.step] = data;
      r.steps = r.steps.map(s => s.id === data.step ? { ...s, status: "done", evidence: data } : s);
      return r;
    }
    case "engine_gaps":
      r.engineGaps = data.gaps || [];
      r.engineForced = !!data.forced;
      return r;
    case "panel":
      r.panel = data;
      return r;
    case "division_finding":
      r.divisionFindings = { ...(run.divisionFindings||{}), [data.division]: data };
      return r;
    case "review":
      r.review = data.review;
      r.steps = r.steps.map(s => s.id === "review" ? { ...s, status: "done", review: data.review } : s);
      return r;
    case "checkpoint_wait":
      // HITL: the review loop is paused awaiting a human decision on this pass.
      r.checkpoint = data;
      return r;
    case "checkpoint_resolved":
      // the decision was delivered (by this human or by timeout) — clear the pause.
      r.checkpoint = null;
      return r;
    case "synthesis":
      r.synthesis = data.synthesis;
      return r;
    case "decision":
      r.decision = data.decision || "REVIEW";
      r.decisionSource = data.decision_source || null;
      r.decisionEngine = data.engine || null;
      r.agentDecision = data.agent_decision || null;
      r.diverges = !!data.diverges;
      r.confidence = data.confidence || r.confidence;
      return r;
    case "done":
      r.steps = r.steps.map(s => s.status === "running" ? { ...s, status: "done" } : s);
      r.report_md = data.report_md;
      r.decision = data.decision || r.decision || "REVIEW";
      r.decisionSource = data.decision_source || r.decisionSource;
      r.confidence = data.confidence || "n/a";
      r.status = "done";
      return r;
    case "error":
      r.status = "error"; r.error = data.message;
      return r;
    default:
      return r;
  }
}

// ======================================================================================
//  Incremental evidence graph — built from whatever evidence has arrived so far
// ======================================================================================
const norm = (v, max) => Math.max(0, Math.min(1, (Number(v) || 0) / max));

// size hint per node kind (the server sends canonical entities; we only size them for layout)
const KIND_VAL = { Target:0.95, Disease:0.8, Modality:0.55, CellType:0.55, Tissue:0.5, Trial:0.5 };
function nodeVal(n) {
  return KIND_VAL[n.kind] ?? 0.5;
}

// the graph is now the CANONICAL property graph streamed from the server (kg.py).
// Nodes are deduped entities (target:CD276, celltype:fibroblast, source:cellxgene…);
// `shared_runs` marks an entity that also appears in OTHER hypotheses (cross-run link).
function graphFromRun(run) {
  const nodes = Object.values(run.gnodes).map(n => ({
    ...n,
    val: nodeVal(n),
    shared: (n.shared_runs || []).length > 0,
    sub: n.sub || subForNode(n),
  }));
  // only keep edges whose endpoints exist yet (deltas may arrive slightly out of order)
  const ids = new Set(nodes.map(n => n.id));
  const edges = Object.values(run.gedges).filter(e => ids.has(e.s) && ids.has(e.t));
  return { nodes, edges };
}
function subForNode(n) {
  return n.kind;
}
const srcUrl = (ref) => { const m = (ref||"").match(/https?:\/\/[^\s)]+/); return m ? m[0] : null; };

// biomedical entity kinds only — nodes are entities, edges are the evidence
const NODE_STYLE = {
  Target:    { fill:"#8b5cf6", stroke:"#c4b5fd" },
  Disease:   { fill:"#0ea5e9", stroke:"#7dd3fc" },
  Modality:  { fill:"#64748b", stroke:"#94a3b8" },
  CellType:  { fill:"#d97706", stroke:"#fcd34d" },
  Tissue:    { fill:"#be123c", stroke:"#fda4af" },
  Trial:     { fill:"#0d9488", stroke:"#5eead4" },
  Drug:      { fill:"#7c3aed", stroke:"#c4b5fd" },
  Pathway:   { fill:"#ca8a04", stroke:"#fde68a" },
};
const PROV_EDGE = { retrieved:"#38bdf8", computed:"#34d399", web:"#a78bfa", gap:"#64748b" };

// radial layout centred on the Target (the biological hub); entities ring outward
const layout = (g, W, H) => {
  const cx = W/2, cy = H/2, pos = {};
  const hub = g.nodes.find(n=>n.kind==="Target") || g.nodes.find(n=>n.kind==="Disease");
  if (hub) pos[hub.id] = { x:cx, y:cy };
  const byKind = (...ks) => g.nodes.filter(n=>ks.includes(n.kind) && n!==hub).map(n=>n.id);
  const ring = (ids, r, a0) => ids.forEach((id,i)=>{
    const a = a0 + (i/Math.max(1,ids.length))*Math.PI*2;
    pos[id] = { x: cx + r*Math.cos(a), y: cy + r*Math.sin(a) };
  });
  ring(byKind("Disease","Modality"), Math.min(W,H)*0.16, -Math.PI/2);
  ring(byKind("CellType","Tissue"),  Math.min(W,H)*0.34, -Math.PI/2 + 0.4);
  ring(byKind("Trial","Drug","Pathway"), Math.min(W,H)*0.46, Math.PI/2);
  // any stragglers without a position
  g.nodes.forEach((n,i)=>{ if(!pos[n.id]) pos[n.id]={ x: cx + 0.4*W*Math.cos(i), y: cy + 0.4*H*Math.sin(i) }; });
  return pos;
};

function EvidenceGraphSVG({ g, selNode, selEdge, onNode, onEdge, complete }) {
  const W = 720, H = 520;
  const pos = useMemo(()=>layout(g, W, H), [g]);
  const focus = selNode;
  const isDim = (id) => focus && id !== focus && !g.edges.some(e =>
    (e.s===focus && e.t===id) || (e.t===focus && e.s===id));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto select-none" style={{maxHeight:"560px"}}>
      {g.edges.map((e,i)=>{
        const a = pos[e.s], b = pos[e.t]; if(!a||!b) return null;
        const sel = selEdge===i;
        const dim = focus && e.s!==focus && e.t!==focus;
        const col = PROV_EDGE[e.prov] || "#64748b";
        const op = (e.conf>=0.8?0.85:e.conf>=0.5?0.55:0.3) * (dim?0.15:1);
        return (
          <g key={"e"+i} className="cursor-pointer fade-up" onClick={(x)=>{x.stopPropagation();onEdge(i);}}>
            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="transparent" strokeWidth="14"/>
            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={col} strokeWidth={sel?3.5:1.6}
              strokeOpacity={sel?1:op} strokeDasharray={e.conf<0.2?"4 3":"none"}/>
            {sel && <text x={(a.x+b.x)/2} y={(a.y+b.y)/2-4} fill="#e2e8f0" fontSize="9" textAnchor="middle" className="mono">{e.type}</text>}
          </g>
        );
      })}
      {g.nodes.map(n=>{
        const p = pos[n.id]; if(!p) return null;
        const st = NODE_STYLE[n.kind] || NODE_STYLE.Target;
        const r = 9 + (n.val||0.4)*16;
        const sel = selNode===n.id, dim = isDim(n.id);
        return (
          <g key={n.id} className="cursor-pointer fade-up" opacity={dim?0.28:1}
             onClick={(x)=>{x.stopPropagation();onNode(n.id);}}>
            {n.shared && <circle cx={p.x} cy={p.y} r={r+4} fill="none" stroke="#fbbf24" strokeWidth={1.5} strokeDasharray="3 2" opacity={0.9}/>}
            <circle cx={p.x} cy={p.y} r={r} fill={st.fill} stroke={sel?"#fff":st.stroke} strokeWidth={sel?3:1.5}/>
            <text x={p.x} y={p.y+r+11} fill={sel?"#fff":"#cbd5e1"} fontSize="10" textAnchor="middle" style={{pointerEvents:"none"}}>
              {n.label.length>22?n.label.slice(0,21)+"…":n.label}</text>
          </g>
        );
      })}
    </svg>
  );
}

function GraphInspector({ g, selNode, selEdge, stepsById }) {
  if (selEdge != null && g.edges[selEdge]) {
    const e = g.edges[selEdge], p = PROV[e.prov] || PROV.computed;
    const sn = g.nodes.find(n=>n.id===e.s), tn = g.nodes.find(n=>n.id===e.t);
    const conf = e.conf != null ? e.conf : null;
    return (
      <div className="space-y-3">
        <div className="text-[11px] uppercase tracking-widest text-sky-300">Evidence · the edge IS the claim</div>
        <div className="mono text-xs text-slate-300">{sn?.label} <span className="text-sky-400">—{e.type}→</span> {tn?.label}</div>
        {e.value && <div className="text-base font-semibold text-white">{e.value}</div>}
        <div className="flex items-center gap-2 flex-wrap">
          {e.axis && <Chip cls="border-sky-600/40 text-sky-300 bg-sky-500/10">{e.axis}</Chip>}
          {e.grade && <Chip cls={gradeStyle(e.grade)}>{e.grade}</Chip>}
          <Chip cls="border-slate-600 text-slate-300 bg-slate-800/60">{p.icon} {p.label.split(" — ")[0]}</Chip>
          {conf!=null && <Chip cls={gradeStyle(conf>=0.8?"strong":conf>=0.5?"supported":"suggestive")}>confidence {conf.toFixed(2)}</Chip>}
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-950/50 p-3 text-sm text-slate-200 leading-relaxed">{e.ref || "—"}</div>
        <div className="text-xs text-slate-400">
          source: {e.url
            ? <a href={e.url} target="_blank" rel="noreferrer" className="text-sky-400 hover:text-sky-300 underline mono">{e.source || e.url} ↗</a>
            : <span className="mono text-slate-300">{e.source || "—"}</span>}
        </div>
        {e.step && stepsById[e.step] && (
          <div className="text-xs text-slate-400 border-t border-slate-800 pt-2">↳ from loop step <span className="mono text-slate-300">{stepsById[e.step].role}</span> — {stepsById[e.step].title}</div>
        )}
      </div>
    );
  }
  if (selNode) {
    const n = g.nodes.find(x=>x.id===selNode); if(!n) return null;
    const st = NODE_STYLE[n.kind]; const inc = g.edges.filter(e=>e.s===n.id||e.t===n.id);
    const step = n.step && stepsById[n.step];
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full" style={{background:st.fill}}></span>
          <span className="text-[11px] uppercase tracking-widest text-slate-300">{n.kind}</span></div>
        <div className="text-base font-semibold text-white">{n.label}</div>
        {n.sub && <div className="text-xs text-slate-400">{n.sub}</div>}
        {n.shared && (
          <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
            🔗 shared entity — also appears in {n.shared_runs.length} other hypothesis{n.shared_runs.length>1?"es":""}
            <div className="mono text-amber-300/70 mt-1">{n.shared_runs.join(", ")}</div>
          </div>
        )}
        {n.val!=null && (
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">normalized value</div>
            <div className="h-2 rounded-full bg-slate-800 overflow-hidden"><div className="h-full" style={{width:`${n.val*100}%`, background:st.fill}}></div></div>
            <div className="mono text-xs text-slate-400 mt-1">{n.val.toFixed(2)}</div>
          </div>
        )}
        {n.url && <a href={n.url} target="_blank" rel="noreferrer" className="inline-block text-xs text-sky-400 hover:text-sky-300 underline mono">{n.url} ↗</a>}
        <div className="border-t border-slate-800 pt-2">
          <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">{inc.length} connection{inc.length!==1?"s":""}</div>
          <ul className="space-y-1">{inc.map((e,i)=>{ const o=e.s===n.id?e.t:e.s; const on=g.nodes.find(x=>x.id===o);
            return <li key={i} className="text-xs text-slate-300 mono">{e.type} · {on?.label}</li>; })}</ul>
        </div>
        {step && <div className="text-xs text-slate-400 border-t border-slate-800 pt-2">↳ traces to <span className="mono text-slate-300">{step.role}</span> — {step.title}</div>}
      </div>
    );
  }
  return <div className="text-sm text-slate-500">Click a <span className="text-slate-300">node</span> for its normalized properties, or an <span className="text-slate-300">edge</span> to open its reference & source.</div>;
}

// The accumulated-evidence ledger: an auditable trail of every evidence item
// the graph has ever ingested, joined to its source (with a working link) and
// confidence — read from /api/ledger, which spans ALL runs, not just this one.
function LedgerView({ run }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const load = useCallback(() => {
    fetch("/api/ledger").then(r=>r.json()).then(setData).catch(e=>setErr(String(e)));
  }, []);
  // refetch on mount and whenever this run finishes (new evidence just landed)
  useEffect(()=>{ load(); }, [load, run.status==="done"]);

  if (err) return <div className="text-sm text-rose-300">Could not load the ledger: {err}</div>;
  if (!data) return <div className="text-sm text-slate-500">Loading accumulated evidence…</div>;

  const rows = data.rows || [];
  // group by subject entity so the trail reads like a per-entity dossier
  const byHyp = {};
  rows.forEach(r=>{ (byHyp[r.subject] ||= []).push(r); });

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex gap-2">
          <Stat n={data.n_evidence} l="evidence items"/>
          <Stat n={data.n_runs} l="runs"/>
          <Stat n={(data.sources||[]).length} l="sources" small/>
        </div>
        <button onClick={load} className="px-3 py-1.5 rounded-lg text-xs font-medium text-slate-300 border border-slate-700 hover:bg-slate-800">↻ refresh</button>
      </div>

      <div className="text-xs text-slate-500">
        Accumulated across <span className="text-slate-300">every</span> query, persisted in <span className="mono">kg.json</span>. Each row traces to its source.
      </div>

      {(data.sources||[]).length>0 && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-2">sources on record</div>
          <div className="flex flex-wrap gap-2">
            {data.sources.map((s,i)=> s.url
              ? <a key={i} href={s.url} target="_blank" rel="noreferrer" className="text-xs text-sky-400 hover:text-sky-300 underline mono px-2 py-1 rounded border border-slate-700 bg-slate-800/40">{s.label} ↗</a>
              : <span key={i} className="text-xs text-slate-400 mono px-2 py-1 rounded border border-slate-700 bg-slate-800/40">{s.label}</span>)}
          </div>
        </div>
      )}

      {Object.entries(byHyp).map(([hyp, items])=>(
        <div key={hyp} className="rounded-2xl border border-slate-800 bg-slate-900/30 overflow-hidden">
          <div className="px-4 py-2 bg-slate-900/60 border-b border-slate-800 text-sm font-semibold text-white mono">{hyp || "—"}</div>
          <table className="w-full text-xs">
            <thead><tr className="text-slate-500 text-left">
              <th className="px-4 py-2 font-medium">evidence (relation → entity)</th>
              <th className="px-2 py-2 font-medium">value</th>
              <th className="px-2 py-2 font-medium">axis</th>
              <th className="px-2 py-2 font-medium">grade</th>
              <th className="px-2 py-2 font-medium">conf</th>
              <th className="px-2 py-2 font-medium">source</th>
            </tr></thead>
            <tbody>
              {items.map((r,i)=>{
                const p = PROV[r.prov] || PROV.computed;
                return (
                  <tr key={i} className="border-t border-slate-800/60 align-top">
                    <td className="px-4 py-2 text-slate-200">
                      <span className="text-sky-400 mono">{r.relation}</span> → <span className="text-slate-100">{r.object}</span>
                      <span className="ml-1 text-[10px] text-slate-500">{r.object_kind}</span>
                    </td>
                    <td className="px-2 py-2 text-slate-300">{r.value || "—"}</td>
                    <td className="px-2 py-2 text-slate-400">{r.axis || "—"}</td>
                    <td className="px-2 py-2"><Chip cls={gradeStyle(r.grade)}>{r.grade || "—"}</Chip></td>
                    <td className="px-2 py-2 mono text-slate-300">{r.conf!=null?Number(r.conf).toFixed(2):"—"}</td>
                    <td className="px-2 py-2">
                      <span className="mr-1">{p.icon}</span>
                      {r.url
                        ? <a href={r.url} target="_blank" rel="noreferrer" className="text-sky-400 hover:text-sky-300 underline">{r.source} ↗</a>
                        : <span className="text-slate-300">{r.source}</span>}
                      {r.observations>1 && <span className="ml-1 text-slate-500">×{r.observations}</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}
      {rows.length===0 && <div className="text-sm text-slate-500">No evidence accumulated yet — run a query.</div>}
    </div>
  );
}

function GraphView({ run }) {
  const g = useMemo(()=>graphFromRun(run), [run]);
  const stepsById = useMemo(()=>Object.fromEntries(run.steps.map(s=>[s.id,s])), [run.steps]);
  const [selNode, setSelNode] = useState(null);
  const [selEdge, setSelEdge] = useState(null);
  const complete = run.status === "done";
  const kinds = [...new Set(g.nodes.map(n=>n.kind))];
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 text-xs text-slate-400 flex-wrap">
          {kinds.map(k=><span key={k} className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full" style={{background:(NODE_STYLE[k]||NODE_STYLE.Target).fill}}></span>{k}</span>)}
          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full border border-dashed border-amber-400"></span>shared across runs</span>
          <span className="text-slate-600">·</span>
          {Object.entries(PROV_EDGE).map(([k,c])=><span key={k} className="flex items-center gap-1"><span className="w-4 h-0.5" style={{background:c}}></span>{k}</span>)}
        </div>
        <Chip cls={complete?"border-emerald-500/40 text-emerald-300 bg-emerald-500/10":"border-sky-500/40 text-sky-300 bg-sky-500/10"}>
          {complete ? `graph complete · ${g.nodes.length} nodes` : `building… ${g.nodes.length} nodes`}
        </Chip>
      </div>
      <div className="grid lg:grid-cols-[1fr_300px] gap-4">
        <div className="rounded-2xl border border-slate-800 bg-slate-900/30 p-2" onClick={()=>{setSelNode(null);setSelEdge(null);}}>
          <EvidenceGraphSVG g={g} selNode={selNode} selEdge={selEdge} complete={complete}
            onNode={(id)=>{setSelNode(id===selNode?null:id);setSelEdge(null);}}
            onEdge={(i)=>{setSelEdge(i===selEdge?null:i);setSelNode(null);}}/>
        </div>
        <div className="rounded-2xl border border-slate-700 bg-slate-900/60 p-4 self-start">
          <GraphInspector g={g} selNode={selNode} selEdge={selEdge} stepsById={stepsById}/>
        </div>
      </div>
      {!complete && <p className="text-xs text-slate-600">The graph grows as each division returns evidence; it's complete when the report is constructed.</p>}
    </div>
  );
}

// ======================================================================================
//  Loop trace (live)
// ======================================================================================
function Chip({children, cls=""}) {
  return <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium border ${cls}`}>{children}</span>;
}

function LoopStep({step, idx, last, active, onClick, engineGaps, engineForced, panel}) {
  const ev = step.evidence;
  const running = step.status === "running";
  const kindCls = step.kind === "agent" ? "border-violet-500/40 bg-violet-500/5" : "border-slate-700 bg-slate-900/60";
  const res = ev?.result || {};
  const metrics = res.tau != null ? { "τ (tau)": res.tau, "bimodality": res.bimodality_coefficient } : null;
  return (
    <div className="flex gap-4 fade-up">
      <div className="flex flex-col items-center">
        <div className={`w-9 h-9 rounded-full grid place-items-center text-sm font-bold border-2 transition
          ${running ? "border-sky-400 bg-sky-400/20 text-sky-200 pulse-ring"
          : step.terminal ? "border-emerald-400 bg-emerald-400/20 text-emerald-200"
          : step.reroute ? "border-amber-400 bg-amber-400/20 text-amber-200"
          : "border-slate-600 bg-slate-800 text-slate-300"}`}>
          {running ? "•" : step.terminal ? "✓" : idx+1}
        </div>
        {!last && <div className={`w-0.5 flex-1 my-1 ${step.reroute?"bg-amber-500/40":"bg-slate-700"}`} style={{minHeight:"1rem"}}/>}
      </div>
      <div className={`flex-1 mb-3 rounded-xl border p-4 transition ${kindCls} ${active?"ring-1 ring-sky-400/50":""} ${ev?"cursor-pointer hover:border-sky-500/50":""}`} onClick={ev?onClick:undefined}>
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <Chip cls={step.kind==="agent"?"border-violet-500/40 text-violet-300 bg-violet-500/10":"border-slate-600 text-slate-300 bg-slate-800"}>{step.kind==="agent"?"AGENT":"SKILL"}</Chip>
            <span className="mono text-xs text-slate-400">{step.role}</span>
          </div>
          <div className="flex items-center gap-2">
            {running && <span className="text-xs text-sky-300">running…</span>}
            {ev && <Chip cls="border-slate-600/50 text-slate-300 bg-slate-800/50">{ev.provenance}</Chip>}
            {ev && <Chip cls={gradeStyle(ev.grade)}>{ev.grade}</Chip>}
            {step.review && <Chip cls={gradeStyle(step.review.verdict==="re-route"?"suggestive":"supported")}>{step.review.verdict}</Chip>}
          </div>
        </div>
        <div className="mt-2 text-sm font-semibold text-slate-100">{step.title}</div>
        <div className="text-xs text-slate-400">{step.division}</div>
        {metrics && (
          <div className="flex gap-4 mt-2">
            {Object.entries(metrics).map(([k,v])=> v!=null && (
              <div key={k} className="bg-slate-950/60 rounded-lg px-3 py-1.5 border border-slate-700">
                <div className="mono text-lg font-bold text-emerald-300">{v}</div>
                <div className="text-[10px] uppercase tracking-wide text-slate-500">{k}</div>
              </div>
            ))}
          </div>
        )}
        {ev && <p className="mt-2 text-sm text-slate-300 leading-relaxed">{res.summary || ev.digest}</p>}
        {step.review && (
          <div className="mt-2 text-sm text-slate-300">
            <div>relevance {step.review.scores?.relevance}/5 · evidence {step.review.scores?.evidence}/5 · thoroughness {step.review.scores?.thoroughness}/5</div>
            {(step.review.gaps||[]).map((gp,i)=><div key={i} className="text-xs text-amber-300/80 mt-1">↳ gap: {gp.missing} → re-route to {gp.route_to}</div>)}
          </div>
        )}
        {step.id==="review" && engineGaps && engineGaps.length>0 && (
          <div className="mt-3 rounded-lg border border-fuchsia-500/40 bg-fuchsia-500/5 p-3">
            <div className="flex items-center gap-2 text-xs">
              <span className="px-2 py-0.5 rounded-md font-bold bg-fuchsia-500/20 text-fuchsia-200 border border-fuchsia-500/40">◆ PROMETHEUX</span>
              <span className="text-fuchsia-200/90">deductive gap-detector · {engineForced ? "forced re-route" : "advisory"}</span>
            </div>
            {engineGaps.map((g,i)=>(
              <div key={i} className="mt-2 text-xs text-fuchsia-100/80">
                {g.forces_reroute ? "⛔" : "○"} {g.explanation} <span className="text-slate-500">→ {g.route_to}</span>
              </div>
            ))}
            <div className="mt-2 text-[10px] text-slate-500">A proven missing axis is a fact, not a judgement — so the engine re-routes even if the LLM panel said synthesize.</div>
          </div>
        )}
        {step.id==="review" && panel && panel.lenses && panel.lenses.length>0 && (
          <div className="mt-3 rounded-lg border border-slate-700 bg-slate-950/40 p-3">
            <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-2">4-lens reviewer panel</div>
            <div className="flex flex-wrap gap-1.5">
              {panel.lenses.map((l,i)=>(
                <span key={i} className={`px-2 py-0.5 rounded-md text-xs border ${l.verdict==="re-route"?"text-rose-300 border-rose-500/40 bg-rose-500/10":"text-emerald-300 border-emerald-500/40 bg-emerald-500/10"}`}>
                  {l.key} {l.verdict==="re-route"?"✗ re-route":"✓"}
                </span>
              ))}
            </div>
            {panel.n_lenses!=null && (
              <div className="mt-2 text-xs text-slate-400">{panel.reroute_votes}/{panel.n_lenses} lenses flag re-route</div>
            )}
          </div>
        )}
        {active && ev && (res.top_cell_types) && (
          <table className="mt-3 w-full text-xs">
            <thead><tr className="text-slate-500 text-left"><th className="py-1">cell type</th><th>mean expr</th><th>% expr</th></tr></thead>
            <tbody>{res.top_cell_types.map((r,i)=><tr key={i} className="border-t border-slate-800"><td className="py-1 text-slate-300">{r.cell_type}</td><td className="mono text-slate-400">{r.mean_expr}</td><td className="mono text-slate-400">{(r.pct_expressing*100).toFixed(0)}%</td></tr>)}</tbody>
          </table>
        )}
        {active && ev && <div className="mt-3 text-xs text-slate-400"><span className="text-slate-500">reference: </span>{ev.reference}</div>}
      </div>
    </div>
  );
}

// ======================================================================================
//  Loop graph (live) — the execution rendered as a horizontal process flow, in the
//  same visual language as the static system schematic (frontend/site/schematic.html),
//  but built dynamically from run.steps as they stream in. Nodes light up by status.
// ======================================================================================

// Status → node colour. Mirrors the timeline's node states so the two views agree.
const GSTATE = {
  running:  { stroke:"#38bdf8", glow:"#38bdf8", fill:"#0c2030" },
  reroute:  { stroke:"#fbbf24", glow:"#fbbf24", fill:"#1c1607" },
  terminal: { stroke:"#34d399", glow:"#34d399", fill:"#06231a" },
  done:     { stroke:"#475569", glow:"#1e293b", fill:"#0f1729" },
  pending:  { stroke:"#243049", glow:"#1e293b", fill:"#0b1120" },
};
function gstate(step) {
  if (!step) return GSTATE.pending;
  if (step.status === "running") return GSTATE.running;
  if (step.terminal) return GSTATE.terminal;
  if (step.reroute) return GSTATE.reroute;
  if (step.status === "done") return GSTATE.done;
  return GSTATE.pending;
}

// Classify each streamed step into a schematic column. Division steps fan out in the
// middle; the reviewer, synthesis and re-route steps get their own lanes.
// routing keys → short, human labels for the division pills
const DIV_LABEL = {
  target_id_and_prioritization: "Target ID",
  target_safety: "Target Safety",
  modality_and_tractability: "Modality & Tractability",
  clinical_officers: "Clinical",
  literature_and_landscape: "Literature",
};
const prettyDiv = (d="") => DIV_LABEL[d.replace(" (re-route)","")] || d.replace(/_/g," ").replace(" (re-route)","");

function stageOf(step) {
  const id = step.id || "";
  if (id === "brief" || id === "briefing" || step.role === "Chief of Staff") return "brief";
  if (id === "plan" || id === "planner") return "plan";
  if (id === "review") return "review";
  if (id === "synthesize" || id === "synthesis" || id === "report") return "synth";
  if (step.reroute) return "reroute";
  return "division";
}

// Build the flow model: ordered columns, each holding the steps that landed in it,
// plus whether the re-route loop ever fired (so we draw the feedback arc live).
function flowFromRun(run) {
  const cols = { brief:[], plan:[], division:[], reroute:[], review:[], synth:[] };
  run.steps.forEach((s, i) => { (cols[stageOf(s)] || cols.division).push({ ...s, _i:i }); });
  const rerouted = cols.reroute.length > 0;
  return { cols, rerouted };
}

function FlowNode({ x, y, w, h, step, label, sub, active, onClick }) {
  const st = gstate(step);
  const clickable = step && step.evidence;
  return (
    <g onClick={clickable ? onClick : undefined} style={{ cursor: clickable ? "pointer" : "default" }}>
      {step && step.status === "running" && (
        <rect x={x-3} y={y-3} width={w+6} height={h+6} rx={13} fill="none"
              stroke={st.glow} strokeWidth="1.2" opacity="0.5" className="pulse-ring"/>
      )}
      <rect x={x} y={y} width={w} height={h} rx={11} fill={st.fill}
            stroke={st.stroke} strokeWidth={active ? 2 : 1.3}
            opacity={step ? 1 : 0.45}/>
      {active && <rect x={x} y={y} width={w} height={h} rx={11} fill="none" stroke="#38bdf8" strokeWidth="1.5" opacity="0.7"/>}
      <text x={x+w/2} y={y+h/2-2} textAnchor="middle" fontSize="11"
            fontFamily="'Space Grotesk',sans-serif" fontWeight="600"
            fill={step ? "#e2e8f0" : "#475569"}>{label}</text>
      {sub && <text x={x+w/2} y={y+h/2+13} textAnchor="middle" fontSize="8"
            fontFamily="'JetBrains Mono',monospace" fill="#64748b">{sub}</text>}
    </g>
  );
}

function LoopGraph({ run, active, setActive }) {
  const { cols, rerouted } = useMemo(() => flowFromRun(run), [run]);
  const W = 1180, H = 360;
  // column x-anchors across the canvas
  const X = { input:30, cso:170, brief:330, plan:330, div:560, review:840, synth:990, out:1100 };
  const flow = (d, key, color="#475569", dash) =>
    <path key={key} d={d} fill="none" stroke={color} strokeWidth="1.5"
          strokeDasharray={dash} markerEnd={`url(#${color===GSTATE.reroute.stroke?"flowArrLoop":"flowArr"})`}/>;

  // division pills, vertically distributed
  const divs = cols.division.concat(cols.reroute);
  const dN = Math.max(divs.length, 1);
  const dTop = 60, dGap = Math.min(64, (H-120) / dN), dH = 40, dW = 220;
  const divY = (i) => dTop + i * dGap;

  const csoY = H/2 - 32, csoH = 64, csoW = 96;
  const revStep = cols.review[cols.review.length-1];
  const synthStep = cols.synth[cols.synth.length-1];
  const briefStep = cols.brief[0], planStep = cols.plan[0];

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/40 overflow-hidden"
         style={{ background:"radial-gradient(120% 90% at 80% -10%, rgba(56,189,248,0.06), transparent 55%), #0c1322" }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ display:"block", width:"100%", height:"auto" }}>
        <defs>
          <marker id="flowArr" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 1 L9 5 L0 9" fill="none" stroke="#64748b" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
          </marker>
          <marker id="flowArrLoop" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
            <path d="M0 1 L9 5 L0 9" fill="none" stroke="#fbbf24" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/>
          </marker>
        </defs>

        {/* input → CSO */}
        <FlowNode x={X.input} y={H/2-26} w={110} h={52} step={run.meta?{status:"done"}:null}
                  label="QUERY" sub="target question"/>
        {flow(`M${X.input+110} ${H/2} H${X.cso-4}`, "in-cso")}

        {/* CSO orchestrator */}
        <FlowNode x={X.cso} y={csoY} w={csoW} h={csoH} step={{status:run.status==="running"&&run.steps.length<2?"running":"done"}}
                  label="CSO" sub="route"/>

        {/* CSO → brief / plan side roles */}
        {flow(`M${X.cso+csoW} ${H/2-14} C${X.brief-40} ${H/2-14} ${X.brief-40} ${divY(0)-60} ${X.brief-4} ${divY(0)-60}`,"cso-brief")}
        <FlowNode x={X.brief} y={divY(0)-78} w={170} h={36} step={briefStep}
                  label="Chief of Staff" sub="brief · decompose"
                  active={!!briefStep&&active===briefStep.id}
                  onClick={()=>briefStep&&setActive(active===briefStep.id?null:briefStep.id)}/>

        {/* CSO → division fan-out */}
        {divs.map((s,i)=>(
          <React.Fragment key={"e"+i}>
            {flow(`M${X.cso+csoW} ${H/2} C${X.div-60} ${H/2} ${X.div-60} ${divY(i)+dH/2} ${X.div-4} ${divY(i)+dH/2}`,
                  "cso-div"+i, s.reroute?GSTATE.reroute.stroke:"#475569", s.reroute?"5 4":undefined)}
            <FlowNode x={X.div} y={divY(i)} w={dW} h={dH} step={s}
                      label={prettyDiv(s.division) + (s.reroute?" ↺":"")}
                      sub={s.role}
                      active={active===s.id} onClick={()=>setActive(active===s.id?null:s.id)}/>
          </React.Fragment>
        ))}
        {divs.length===0 && (
          <FlowNode x={X.div} y={divY(0)} w={dW} h={dH} step={null} label="divisions" sub="awaiting routing…"/>
        )}

        {/* divisions merge → reviewer */}
        {flow(`M${X.div+dW} ${divY(Math.floor((dN-1)/2))+dH/2} C${X.review-50} ${H/2} ${X.review-50} ${H/2} ${X.review-4} ${H/2}`,"div-rev")}
        <FlowNode x={X.review} y={H/2-30} w={120} h={60} step={revStep}
                  label="Reviewer" sub="gap-gate · panel"
                  active={active==="review"} onClick={()=>revStep&&setActive(active==="review"?null:"review")}/>

        {/* reviewer → synthesis */}
        {flow(`M${X.review+120} ${H/2} H${X.synth-4}`,"rev-synth")}
        <FlowNode x={X.synth} y={H/2-26} w={90} h={52} step={synthStep||(run.synthesis?{status:"done"}:null)}
                  label="CSO" sub="synthesis"/>

        {/* synthesis → GO/NO-GO */}
        {flow(`M${X.synth+90} ${H/2} H${X.out-4}`,"synth-out")}
        <FlowNode x={X.out} y={H/2-26} w={70} h={52}
                  step={run.decision&&run.decision!=="PENDING"?{status:"done",terminal:run.decision==="GO"}:null}
                  label={(run.decision||"PENDING").replace("_"," ").split(" ")[0]||"PENDING"}
                  sub={run.decision==="PENDING"?"awaiting":"verdict"}/>

        {/* the re-route feedback arc — drawn live once any reroute step fires */}
        {rerouted && (
          <>
            <path d={`M${X.review} ${H/2+30} C${X.review} ${H-24} ${X.div} ${H-24} ${X.cso+csoW/2} ${H-24} L${X.cso+csoW/2} ${csoY+csoH+2}`}
                  fill="none" stroke={GSTATE.reroute.stroke} strokeWidth="1.7" strokeDasharray="6 5"
                  markerEnd="url(#flowArrLoop)"/>
            <rect x={X.div-10} y={H-36} width="240" height="22" rx="11" fill="#0c1322" stroke={GSTATE.reroute.stroke} strokeOpacity="0.35"/>
            <text x={X.div+110} y={H-21} textAnchor="middle" fontSize="10"
                  fontFamily="'JetBrains Mono',monospace" fill={GSTATE.reroute.stroke}>
              re-route to fill missing gaps · {cols.reroute.length}
            </text>
          </>
        )}
      </svg>
      {/* selected-step detail, reusing the timeline card so clicks stay informative */}
      {active && run.steps.find(s=>s.id===active) && (
        <div className="border-t border-slate-800 p-4">
          <LoopStep step={run.steps.find(s=>s.id===active)}
                    idx={run.steps.findIndex(s=>s.id===active)} last
                    active onClick={()=>setActive(null)}
                    engineGaps={run.engineGaps} engineForced={run.engineForced} panel={run.panel}/>
        </div>
      )}
    </div>
  );
}

function LoopTrace({run}) {
  const [active, setActive] = useState(null);
  const [view, setView] = useState("graph");  // "graph" (process flow) | "timeline"
  return (
    <div>
      <div className="flex items-center gap-3 mb-5 text-xs text-slate-400 flex-wrap">
        {Object.entries(PROV).map(([k,p])=><span key={k}>{p.icon} {p.label}</span>)}
        <div className="ml-auto inline-flex rounded-lg border border-slate-700 overflow-hidden">
          {[["graph","⬡ Process flow"],["timeline","☰ Timeline"]].map(([k,l])=>(
            <button key={k} onClick={()=>setView(k)}
              className={`px-3 py-1 text-xs ${view===k?"bg-slate-700 text-slate-100":"text-slate-400 hover:text-slate-200"}`}>{l}</button>
          ))}
        </div>
      </div>
      {run.decisionEngine && <PrometheuxDecision run={run} className="mb-5"/>}
      {view==="graph" && <LoopGraph run={run} active={active} setActive={setActive}/>}
      {view==="timeline" && (
      <div className="rounded-2xl border border-slate-800 bg-slate-900/30 p-5">
        {run.steps.map((s,i)=>(
          <LoopStep key={s.id+"_"+i} step={s} idx={i} last={i===run.steps.length-1}
            active={active===s.id} onClick={()=>setActive(active===s.id?null:s.id)}
            engineGaps={run.engineGaps} engineForced={run.engineForced} panel={run.panel}/>
        ))}
        {run.status==="running" && run.steps.length===0 && <div className="text-sm text-slate-500">starting the loop…</div>}
        {Object.keys(run.divisionFindings||{}).length>0 && (
          <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/40 p-4">
            <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-2">division findings</div>
            <div className="space-y-1.5">
              {Object.values(run.divisionFindings).map((df,i)=>{
                const f = df.finding || {};
                return (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <span className="text-slate-300 font-semibold whitespace-nowrap">{df.division}</span>
                    {f.evidence_grade && <Chip cls={gradeStyle(f.evidence_grade)}>{f.evidence_grade}</Chip>}
                    {f.interpretation && <span className="text-slate-400 truncate">{f.interpretation}</span>}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
      )}
    </div>
  );
}

// Prometheux deductive decision: the GO/NO-GO tier derived from per-axis coverage,
// with the safety hard-gate and a replayable per-axis basis. Authoritative over the
// agent's free-text; a divergence is surfaced, never silently overridden.
function PrometheuxDecision({run, className}) {
  const e = run.decisionEngine;
  if (!e) return null;
  const dec = DECISION[e.tier] || DECISION.REVIEW;
  const axes = e.axes || {};
  return (
    <div className={`rounded-2xl border border-fuchsia-500/40 bg-fuchsia-500/5 p-5 ${className||""}`}>
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <span className="px-2 py-0.5 rounded-md font-bold text-xs bg-fuchsia-500/20 text-fuchsia-200 border border-fuchsia-500/40">◆ PROMETHEUX</span>
        <span className="text-xs uppercase tracking-widest text-fuchsia-200/80">deductive decision</span>
        <span className={`ml-auto px-3 py-1 rounded-lg font-extrabold text-sm ${dec.c}`}>{(e.tier||"REVIEW").replace("_"," ")}</span>
      </div>
      <div className="text-sm text-slate-200">
        coverage score <span className="mono font-bold text-fuchsia-200">{e.score}</span>
        <span className="text-slate-500"> / {e.max_score}</span>
      </div>
      <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2">
        {Object.entries(axes).map(([ax,a])=>{
          const absent = a.grade==="absent";
          return (
          <div key={ax} className={`rounded-lg border px-3 py-2 ${absent?"border-rose-500/30 bg-rose-500/5 border-dashed":"border-slate-700 bg-slate-950/50"}`}>
            <div className="text-[10px] uppercase tracking-wide text-slate-500">{ax}</div>
            <div className={`text-sm font-semibold ${a.weight>=1?"text-emerald-300":a.weight>=0.5?"text-sky-300":a.weight>0?"text-amber-300":"text-rose-300/90"}`}>{absent?"no information":a.grade}</div>
            <div className="mono text-[10px] text-slate-500">w {a.weight}</div>
          </div>
        );})}
      </div>
      {(e.absent_axes||[]).length>0 && (
        <div className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/5 p-3 text-xs text-rose-200/90">
          ⚪ <b>No information</b> on: {e.absent_axes.join(", ")} — these axes were never assessed (or returned empty). The score reflects absence, not weak evidence.
        </div>
      )}
      {e.explanation && <p className="mt-3 text-xs text-fuchsia-100/70 leading-relaxed border-t border-fuchsia-500/20 pt-3">{e.explanation}</p>}
      {run.diverges && (
        <div className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-200">
          ⚠️ <b>Divergence:</b> the synthesis agent proposed <b>{(run.agentDecision||"").replace("_"," ")}</b>, but the deductive layer derives <b>{(e.tier||"").replace("_"," ")}</b> from the evidence coverage. The derived tier is the decision of record.
        </div>
      )}
    </div>
  );
}

// ======================================================================================
//  Report (from live synthesis)
// ======================================================================================
function Panel({title, accent, children}) {
  const a = {rose:"text-rose-300", amber:"text-amber-300", sky:"text-sky-300"}[accent] || "text-slate-300";
  return <div className="rounded-2xl border border-slate-700 bg-slate-900/60 p-5"><div className={`text-xs uppercase tracking-widest mb-3 ${a}`}>{title}</div>{children}</div>;
}

// Collect the per-run evidence edges, grouped by validity axis (druggability,
// modality, linkage, safety, clinical precedence…). The decision engine supplies
// the axis grade + weight; the streamed edges supply the supporting datasource rows.
function axisEvidenceFromRun(run) {
  const axesMeta = run.decisionEngine?.axes || {};
  const nodes = run.gnodes || {};
  const byAxis = {};
  // seed every axis the decision engine evaluated, so empty axes still surface
  Object.entries(axesMeta).forEach(([ax, a]) => { byAxis[ax] = { meta: a, rows: [] }; });
  Object.values(run.gedges || {}).forEach(e => {
    if (!e.axis) return;
    (byAxis[e.axis] ||= { meta: null, rows: [] }).rows.push({
      ...e,
      subjectLabel: nodes[e.s]?.label || e.s,
      objectLabel: nodes[e.t]?.label || e.t,
    });
  });
  return byAxis;
}

function AxisEvidence({ ax, entry }) {
  const a = entry.meta;
  const absent = a?.grade === "absent" || entry.rows.length === 0;
  return (
    <div className="space-y-4">
      <div className={`rounded-2xl border p-5 ${absent ? "border-rose-500/30 bg-rose-500/5" : "border-slate-700 bg-slate-900/60"}`}>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs uppercase tracking-widest text-slate-400">{ax}</span>
          {a && <Chip cls={gradeStyle(absent ? "absent" : a.grade)}>{absent ? "no information" : a.grade}</Chip>}
          {a && <Chip cls="border-slate-600 text-slate-300 bg-slate-800/60">weight {a.weight}</Chip>}
          <span className="ml-auto text-xs text-slate-500">{entry.rows.length} evidence item{entry.rows.length!==1?"s":""}</span>
        </div>
        {absent && <p className="mt-2 text-xs text-rose-200/80">No information on this axis was gathered — the score reflects absence, not weak evidence.</p>}
      </div>
      {entry.rows.length > 0 && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/30 overflow-hidden">
          <table className="w-full text-xs">
            <thead><tr className="text-slate-500 text-left">
              <th className="px-4 py-2 font-medium">evidence (relation → entity)</th>
              <th className="px-2 py-2 font-medium">value</th>
              <th className="px-2 py-2 font-medium">grade</th>
              <th className="px-2 py-2 font-medium">conf</th>
              <th className="px-2 py-2 font-medium">source</th>
            </tr></thead>
            <tbody>
              {entry.rows.map((r,i)=>{
                const p = PROV[provOf(r.prov)] || PROV.computed;
                return (
                  <tr key={i} className="border-t border-slate-800/60 align-top">
                    <td className="px-4 py-2 text-slate-200">
                      <span className="text-sky-400 mono">{r.type}</span> → <span className="text-slate-100">{r.objectLabel}</span>
                      {r.ref && <div className="text-[11px] text-slate-500 mt-0.5 leading-snug">{r.ref}</div>}
                    </td>
                    <td className="px-2 py-2 text-slate-300">{r.value || "—"}</td>
                    <td className="px-2 py-2"><Chip cls={gradeStyle(r.grade)}>{r.grade || "—"}</Chip></td>
                    <td className="px-2 py-2 mono text-slate-300">{r.conf!=null?Number(r.conf).toFixed(2):"—"}</td>
                    <td className="px-2 py-2">
                      <span className="mr-1">{p.icon}</span>
                      {r.url
                        ? <a href={r.url} target="_blank" rel="noreferrer" className="text-sky-400 hover:text-sky-300 underline">{r.source} ↗</a>
                        : <span className="text-slate-300">{r.source || "—"}</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ReportOverview({run, s}) {
  const decTier = run.decisionEngine?.tier || s.decision || "REVIEW";
  const dec = DECISION[decTier] || DECISION.REVIEW;
  return (
    <div className="space-y-5">
      <div className={`rounded-2xl border border-slate-700 bg-slate-900/60 p-6 ring-1 ${dec.ring}`}>
        <div className="text-xs uppercase tracking-widest text-slate-500 mb-2">Executive summary</div>
        <div className="flex items-center gap-3 flex-wrap">
          <span className={`px-4 py-1.5 rounded-lg font-extrabold text-sm ${dec.c}`}>{decTier.replace("_"," ")}</span>
          {run.decisionSource==="prometheux" && <Chip cls="border-fuchsia-500/40 text-fuchsia-200 bg-fuchsia-500/10">◆ derived</Chip>}
          <Chip cls="border-slate-600 text-slate-300 bg-slate-800">confidence: {s.confidence||run.confidence}</Chip>
        </div>
        <p className="mt-4 text-sm text-slate-200 leading-relaxed">{s.recommendation}</p>
        {s.target_overview && <p className="mt-3 text-xs text-slate-400 leading-relaxed border-t border-slate-800 pt-3">{s.target_overview}</p>}
      </div>
      {run.decisionEngine && <PrometheuxDecision run={run}/>}
      <div className="grid md:grid-cols-2 gap-5">
        <Panel title="Liabilities & risks" accent="rose">
          {(s.liabilities||[]).map((l,i)=><div key={i} className="mb-3 last:mb-0"><div className="text-sm text-slate-200">{l.risk}</div>{l.mitigation && <div className="text-xs text-emerald-300/80 mt-0.5">↳ mitigation: {l.mitigation}</div>}</div>)}
        </Panel>
        <Panel title="Evidence gaps" accent="amber">
          <ul className="space-y-2">{(s.evidence_gaps||[]).map((g,i)=><li key={i} className="text-sm text-slate-300 flex gap-2">⚪ {g}</li>)}</ul>
        </Panel>
      </div>
      {(s.proposed_experiments||[]).length>0 && (
        <Panel title="Proposed experiments" accent="sky">
          <div className="grid sm:grid-cols-2 gap-3">
            {s.proposed_experiments.map((e,i)=><div key={i} className="rounded-lg border border-slate-700 bg-slate-950/40 p-3">
              <div className="text-sm font-semibold text-slate-100">{e.experiment}</div>
              {e.expected_readout && <div className="text-xs text-sky-300/80 mt-1">readout: {e.expected_readout}</div>}
              {e.rationale && <div className="text-xs text-slate-400 mt-1">{e.rationale}</div>}
            </div>)}
          </div>
        </Panel>
      )}
    </div>
  );
}

function Report({run}) {
  const s = run.synthesis;
  const byAxis = useMemo(()=>axisEvidenceFromRun(run), [run.gedges, run.decisionEngine]);
  const axisKeys = Object.keys(byAxis);
  const [sub, setSub] = useState("overview");
  if (run.status !== "done" || !s) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/40 p-10 text-center">
        <div className="text-sm text-slate-400">The report is constructed once the loop completes.</div>
        <div className="text-xs text-slate-600 mt-1">{run.status==="running" ? "synthesis pending — evidence still being gathered…" : "submit a query to begin."}</div>
      </div>
    );
  }
  const active = sub !== "overview" && byAxis[sub] ? sub : "overview";
  return (
    <div className="space-y-5">
      {/* axis nav — the report is read either as the synthesis (overview) or per validity axis */}
      <div className="flex flex-wrap gap-1.5 p-1 rounded-xl bg-slate-900/60 border border-slate-800">
        <button onClick={()=>setSub("overview")}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition ${active==="overview"?"bg-sky-500 text-white":"text-slate-400 hover:text-slate-200"}`}>
          Report
        </button>
        {axisKeys.map(ax=>{
          const entry = byAxis[ax];
          const absent = entry.meta?.grade==="absent" || entry.rows.length===0;
          return (
            <button key={ax} onClick={()=>setSub(ax)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition flex items-center gap-1.5 ${active===ax?"bg-sky-500 text-white":"text-slate-400 hover:text-slate-200"}`}>
              <span className="capitalize">{ax}</span>
              <span className={`text-[10px] ${active===ax?"opacity-80":absent?"text-rose-400/80":"text-slate-500"}`}>
                {absent?"⚪":entry.rows.length}
              </span>
            </button>
          );
        })}
      </div>
      {active==="overview"
        ? <ReportOverview run={run} s={s}/>
        : <AxisEvidence ax={active} entry={byAxis[active]}/>}
    </div>
  );
}

// ======================================================================================
//  Query screen + run shell
// ======================================================================================
// Reasoning-budget presets for the review→reroute loop. Higher budget lets the loop
// chase more of the broader "desired" evidence axes (somatic / malignancy / landscape)
// before converging; lower keeps it on the core four. Token spend is the bound — the
// same meter Langfuse traces. Mirrors a "thinking effort" selector.
const BUDGETS = [
  {key:"focused",  label:"Focused",  tokens:0,      hint:"core axes only — fastest"},
  {key:"balanced", label:"Balanced", tokens:30000,  hint:"core + a couple broader axes"},
  {key:"thorough", label:"Thorough", tokens:60000,  hint:"chase all broader axes (default)"},
];

function QueryScreen({onRun}) {
  const [q, setQ] = useState(EXAMPLES[0]);
  const [demo, setDemo] = useState(true);
  const [agents, setAgents] = useState(false);
  const [partial, setPartial] = useState(false);
  const [hitl, setHitl] = useState(false);
  const [budget, setBudget] = useState("thorough");
  return (
    <div className="max-w-2xl mx-auto px-4 py-20 fade-up">
      <div className="text-xs text-sky-400 mono mb-2">virtual-biotech-cso · multi-agent harness</div>
      <h1 className="text-3xl sm:text-4xl font-extrabold text-white">Ask the Virtual CSO.</h1>
      <p className="text-slate-400 mt-3">Submit a target-assessment question. A Chief-of-Staff briefing, division scientists, a four-lens Scientific Reviewer panel (with a bounded re-route loop), and a CSO synthesis run as agents — the loop, the evidence graph, and the report build in real time.</p>
      <form className="mt-8" onSubmit={(e)=>{e.preventDefault(); if(q.trim()) onRun(q.trim(), demo, partial, agents, BUDGETS.find(b=>b.key===budget).tokens, hitl);}}>
        <textarea value={q} onChange={(e)=>setQ(e.target.value)} rows={3}
          className="w-full rounded-xl bg-slate-900/70 border border-slate-700 focus:border-sky-500 outline-none p-4 text-slate-100 text-sm resize-none"
          placeholder="e.g. Assess B7-H3 potential as a therapeutic target in lung cancer"/>
        <div className="flex items-center justify-between gap-3 mt-3 flex-wrap">
          <label className="flex items-center gap-2 text-sm text-slate-400 cursor-pointer">
            <input type="checkbox" checked={demo} onChange={(e)=>setDemo(e.target.checked)} className="accent-sky-500"/>
            demo mode <span className="text-slate-600">(cached data for the routed skills — reliable for a stage)</span>
          </label>
          <button type="submit" className="px-5 py-2 rounded-xl bg-sky-500 hover:bg-sky-400 text-white font-semibold text-sm">Run assessment →</button>
        </div>
        <label className="flex items-center gap-2 text-sm text-emerald-300/90 cursor-pointer mt-3">
          <input type="checkbox" checked={agents} onChange={(e)=>setAgents(e.target.checked)} className="accent-emerald-500"/>
          ⚡ live agents <span className="text-slate-600">(reasoning roles call a real LLM — the genuine multi-agent loop; ~3-4 min. Off = instant, deterministic stubs.)</span>
        </label>
        <label className="flex items-center gap-2 text-sm text-fuchsia-300/90 cursor-pointer mt-3">
          <input type="checkbox" checked={partial} onChange={(e)=>setPartial(e.target.checked)} className="accent-fuchsia-500"/>
          ◆ skip the safety step <span className="text-slate-600">(demonstrate the Prometheux gap-detector forcing a re-route to fill the missing axis)</span>
        </label>
        <label className="flex items-center gap-2 text-sm text-amber-300/90 cursor-pointer mt-3">
          <input type="checkbox" checked={hitl} onChange={(e)=>setHitl(e.target.checked)} className="accent-amber-500"/>
          🧑‍⚖️ human in the loop <span className="text-slate-600">(pause at each reviewer pass to approve, override, redirect, or add a gap — the human joins the panel)</span>
        </label>
      </form>
      <div className="mt-8">
        <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-2">try an example</div>
        <div className="flex flex-col gap-2">
          {EXAMPLES.map((ex,i)=><button key={i} onClick={()=>setQ(ex)} className="text-left text-sm text-slate-300 rounded-lg border border-slate-800 hover:border-slate-600 bg-slate-900/40 px-3 py-2">{ex}</button>)}
        </div>
      </div>
    </div>
  );
}

// HITL: the reviewer-panel checkpoint. The loop is paused; the human joins the panel
// — approve the autonomous verdict, override it, redirect the re-route, or add a gap.
function CheckpointModal({ cp, onDecide }) {
  const [skill, setSkill] = useState(cp.proposed_reroute?.skill || "");
  const [missing, setMissing] = useState("");
  const pr = cp.proposed_reroute;
  const verdict = cp.verdict;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm fade-up">
      <div className="max-w-lg w-full mx-4 rounded-2xl border border-amber-500/40 bg-slate-900 p-6 shadow-2xl">
        <div className="text-xs text-amber-300 mono mb-1">🧑‍⚖️ human in the loop · reviewer pass {(cp.iteration ?? 0) + 1}</div>
        <h3 className="text-lg font-bold text-white">The panel voted <span className={verdict==="re-route"?"text-amber-300":"text-emerald-300"}>{verdict}</span>.</h3>
        <p className="text-sm text-slate-400 mt-1">
          {cp.panel ? `${cp.panel.reroute_votes}/${cp.panel.n_lenses} lenses flagged a re-route. ` : ""}
          {pr ? <>Proposed next step: <span className="text-slate-200 mono">{pr.skill}</span>{pr.missing?` — to fill "${pr.missing}"`:""}.</> : "No follow-up proposed."}
        </p>
        {(cp.gaps && cp.gaps.length>0) && (
          <ul className="mt-3 text-xs text-slate-400 list-disc pl-5 space-y-0.5">
            {cp.gaps.slice(0,4).map((g,i)=><li key={i}><span className="text-slate-300">{g.missing}</span>{g.route_to?` → ${g.route_to}`:""}</li>)}
          </ul>
        )}
        <div className="mt-5 grid grid-cols-2 gap-2">
          <button onClick={()=>onDecide({action:"approve"})}
            className="px-3 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-white text-sm font-semibold">✓ Approve verdict</button>
          {verdict==="re-route"
            ? <button onClick={()=>onDecide({action:"override_verdict",verdict:"synthesize"})}
                className="px-3 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-white text-sm font-semibold">■ Stop &amp; synthesize</button>
            : <button onClick={()=>onDecide({action:"override_verdict",verdict:"re-route",route_to:skill||undefined,missing:missing||"human-directed re-route"})}
                className="px-3 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 text-white text-sm font-semibold">↻ Force a re-route</button>}
        </div>
        <div className="mt-4 border-t border-slate-800 pt-4">
          <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-2">…or steer the next step</div>
          <div className="flex gap-2">
            <input value={skill} onChange={e=>setSkill(e.target.value)} placeholder="skill (e.g. struct-predictor)"
              className="flex-1 rounded-lg bg-slate-800 border border-slate-700 focus:border-amber-500 outline-none px-2 py-1.5 text-xs text-slate-100 mono"/>
            <input value={missing} onChange={e=>setMissing(e.target.value)} placeholder="gap / question"
              className="flex-1 rounded-lg bg-slate-800 border border-slate-700 focus:border-amber-500 outline-none px-2 py-1.5 text-xs text-slate-100"/>
          </div>
          <div className="flex gap-2 mt-2">
            <button disabled={!skill} onClick={()=>onDecide({action:"redirect",route_to:skill,missing:missing||undefined})}
              className="flex-1 px-3 py-1.5 rounded-lg border border-amber-500/40 text-amber-200 hover:bg-amber-500/10 disabled:opacity-40 text-xs font-semibold">→ Redirect re-route</button>
            <button disabled={!skill&&!missing} onClick={()=>onDecide({action:"add_gap",route_to:skill||undefined,missing:missing||undefined})}
              className="flex-1 px-3 py-1.5 rounded-lg border border-sky-500/40 text-sky-200 hover:bg-sky-500/10 disabled:opacity-40 text-xs font-semibold">+ Add gap to chase</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function App() {
  const [run, setRun] = useState(emptyRun);
  const [tab, setTab] = useState("loop");
  const esRef = useRef(null);
  const runRef = useRef(run);
  runRef.current = run;

  const start = useCallback((query, demo, partial, agents, budget, hitl) => {
    if (esRef.current) esRef.current.close();
    setRun({ ...emptyRun(), status:"running", meta:{ query, partial: !!partial, hitl: !!hitl } });
    setTab("loop");
    const url = `/api/run?query=${encodeURIComponent(query)}&demo=${demo?1:0}&agents=${agents?1:0}${partial?"&partial=1":""}${hitl?"&hitl=1":""}`;
    const es = new EventSource(url);
    esRef.current = es;
    const on = (name) => es.addEventListener(name, (e)=>{
      const data = JSON.parse(e.data);
      setRun(prev => reduceEvent(prev, name, data));
      if (name === "done" || name === "error") es.close();
    });
    ["start","phase","briefing","plan","evidence","node","edge","engine_gaps","panel","division_finding","review","checkpoint_wait","checkpoint_resolved","synthesis","decision","done","error"].forEach(on);
    es.onerror = () => { setRun(prev => prev.status==="done"?prev:reduceEvent(prev,"error",{message:"connection lost — is server.py running?"})); es.close(); };
  }, []);

  // HITL: deliver the human's decision to the paused review loop, then clear the modal
  // optimistically (the server also emits checkpoint_resolved to confirm).
  const decide = useCallback((decision) => {
    const cp = runRef.current?.checkpoint;
    if (!cp) return;
    setRun(prev => ({ ...prev, checkpoint: null }));
    fetch(`/api/decision?run_id=${encodeURIComponent(cp.run_id)}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(decision),
    }).catch(()=>{});
  }, []);

  useEffect(()=>()=>{ if(esRef.current) esRef.current.close(); }, []);

  // shareable / auto-run links: /?q=...&demo=1 starts immediately
  useEffect(()=>{
    const p = new URLSearchParams(window.location.search);
    const q = p.get("q");
    if (q) start(q, p.get("demo") !== "0", p.get("partial") === "1", p.get("agents") === "1", undefined, p.get("hitl") === "1");
    if (p.get("tab")) setTab(p.get("tab"));
  }, [start]);

  if (run.status === "idle") return <QueryScreen onRun={start}/>;

  const stepsDone = run.steps.filter(s=>s.status==="done").length;
  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 py-8">
      {run.checkpoint && <CheckpointModal cp={run.checkpoint} onDecide={decide}/>}
      <div className="flex items-start justify-between gap-4 flex-wrap mb-6">
        <div>
          <button onClick={()=>{ if(esRef.current) esRef.current.close(); setRun(emptyRun()); }} className="text-xs text-sky-400 mono mb-1 hover:text-sky-300">← new question</button>
          <h1 className="text-xl sm:text-2xl font-extrabold text-white">{run.meta?.query}</h1>
          <div className="flex items-center gap-2 mt-1 text-xs">
            <Chip cls={run.status==="done"?"border-emerald-500/40 text-emerald-300 bg-emerald-500/10":run.status==="error"?"border-rose-500/40 text-rose-300 bg-rose-500/10":"border-sky-500/40 text-sky-300 bg-sky-500/10"}>
              {run.status==="running"?"running":run.status==="done"?"complete":"error"}
            </Chip>
            {run.meta?.calls_llm
              ? <span className="text-slate-500 mono">{run.meta.backend} · {run.meta.model}</span>
              : <span className="text-slate-500">demo / stub — no LLM</span>}
            {run.meta?.partial && <Chip cls="border-fuchsia-500/40 text-fuchsia-200 bg-fuchsia-500/10">◆ safety step skipped</Chip>}
          </div>
        </div>
        <div className="flex gap-2 text-center">
          <Stat n={stepsDone} l="steps done"/>
          <Stat n={Object.keys(run.evidence).length} l="evidence"/>
          <Stat n={(run.decision||"—").replace("_"," ")} l="decision" small/>
        </div>
      </div>

      {run.status==="error" && <div className="mb-5 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">⚠️ {run.error}</div>}

      <div className="flex gap-1 p-1 rounded-xl bg-slate-900/60 border border-slate-800 w-fit mb-6">
        {[["loop","Loop trace"],["graph","Evidence graph"],["ledger","Evidence ledger"],["report","Report"]].map(([k,l])=>(
          <button key={k} onClick={()=>setTab(k)} className={`px-4 py-1.5 rounded-lg text-sm font-medium transition ${tab===k?"bg-sky-500 text-white":"text-slate-400 hover:text-slate-200"}`}>
            {l}{k==="report" && run.status!=="done" && <span className="ml-1 text-[10px] opacity-60">pending</span>}
          </button>
        ))}
      </div>

      {tab==="loop" && <LoopTrace run={run}/>}
      {tab==="graph" && <GraphView run={run}/>}
      {tab==="ledger" && <LedgerView run={run}/>}
      {tab==="report" && <Report run={run}/>}

      <div className="mt-8 pt-4 border-t border-slate-800 text-xs text-slate-600">
        Live multi-agent loop via <span className="mono">server.py</span> → <span className="mono">harness.py</span> / <span className="mono">cso.py</span>. {run.meta?.calls_llm ? "Reasoning roles ran as live agents." : "Demo mode: cached, illustrative fixtures — labelled as such, never fabricated."}
      </div>
    </div>
  );
}

function Stat({n,l,small}){return <div className="px-3 py-2 rounded-xl bg-slate-900/60 border border-slate-800"><div className={`font-bold text-white ${small?"text-sm":"text-xl"}`}>{n}</div><div className="text-[10px] uppercase tracking-wide text-slate-500">{l}</div></div>;}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
