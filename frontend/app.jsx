
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
  confidence: "n/a",
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
    case "review":
      r.review = data.review;
      r.steps = r.steps.map(s => s.id === "review" ? { ...s, status: "done", review: data.review } : s);
      return r;
    case "synthesis":
      r.synthesis = data.synthesis;
      return r;
    case "done":
      r.steps = r.steps.map(s => s.status === "running" ? { ...s, status: "done" } : s);
      r.report_md = data.report_md;
      r.decision = data.decision || "REVIEW";
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

function LoopStep({step, idx, last, active, onClick}) {
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

function LoopTrace({run}) {
  const [active, setActive] = useState(null);
  return (
    <div>
      <div className="flex items-center gap-3 mb-5 text-xs text-slate-400 flex-wrap">
        {Object.entries(PROV).map(([k,p])=><span key={k}>{p.icon} {p.label}</span>)}
      </div>
      <div className="rounded-2xl border border-slate-800 bg-slate-900/30 p-5">
        {run.steps.map((s,i)=>(
          <LoopStep key={s.id+"_"+i} step={s} idx={i} last={i===run.steps.length-1}
            active={active===s.id} onClick={()=>setActive(active===s.id?null:s.id)}/>
        ))}
        {run.status==="running" && run.steps.length===0 && <div className="text-sm text-slate-500">starting the loop…</div>}
      </div>
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

function Report({run}) {
  const s = run.synthesis;
  if (run.status !== "done" || !s) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/40 p-10 text-center">
        <div className="text-sm text-slate-400">The report is constructed once the loop completes.</div>
        <div className="text-xs text-slate-600 mt-1">{run.status==="running" ? "synthesis pending — evidence still being gathered…" : "submit a query to begin."}</div>
      </div>
    );
  }
  const dec = DECISION[s.decision] || DECISION.REVIEW;
  return (
    <div className="space-y-5">
      <div className={`rounded-2xl border border-slate-700 bg-slate-900/60 p-6 ring-1 ${dec.ring}`}>
        <div className="text-xs uppercase tracking-widest text-slate-500 mb-2">Executive summary</div>
        <div className="flex items-center gap-3 flex-wrap">
          <span className={`px-4 py-1.5 rounded-lg font-extrabold text-sm ${dec.c}`}>{(s.decision||"REVIEW").replace("_"," ")}</span>
          <Chip cls="border-slate-600 text-slate-300 bg-slate-800">confidence: {s.confidence||run.confidence}</Chip>
        </div>
        <p className="mt-4 text-sm text-slate-200 leading-relaxed">{s.recommendation}</p>
        {s.target_overview && <p className="mt-3 text-xs text-slate-400 leading-relaxed border-t border-slate-800 pt-3">{s.target_overview}</p>}
      </div>
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

// ======================================================================================
//  Query screen + run shell
// ======================================================================================
function QueryScreen({onRun}) {
  const [q, setQ] = useState(EXAMPLES[0]);
  const [demo, setDemo] = useState(true);
  return (
    <div className="max-w-2xl mx-auto px-4 py-20 fade-up">
      <div className="text-xs text-sky-400 mono mb-2">virtual-biotech-cso · multi-agent harness</div>
      <h1 className="text-3xl sm:text-4xl font-extrabold text-white">Ask the Virtual CSO.</h1>
      <p className="text-slate-400 mt-3">Submit a target-assessment question. A Chief-of-Staff briefing, division scientists, a Scientific Reviewer audit (with one re-route), and a CSO synthesis run as live agents — the loop, the evidence graph, and the report build in real time.</p>
      <form className="mt-8" onSubmit={(e)=>{e.preventDefault(); if(q.trim()) onRun(q.trim(), demo);}}>
        <textarea value={q} onChange={(e)=>setQ(e.target.value)} rows={3}
          className="w-full rounded-xl bg-slate-900/70 border border-slate-700 focus:border-sky-500 outline-none p-4 text-slate-100 text-sm resize-none"
          placeholder="e.g. Assess B7-H3 potential as a therapeutic target in lung cancer"/>
        <div className="flex items-center justify-between gap-3 mt-3 flex-wrap">
          <label className="flex items-center gap-2 text-sm text-slate-400 cursor-pointer">
            <input type="checkbox" checked={demo} onChange={(e)=>setDemo(e.target.checked)} className="accent-sky-500"/>
            demo mode <span className="text-slate-600">(cached data, no LLM/network — reliable for a stage)</span>
          </label>
          <button type="submit" className="px-5 py-2 rounded-xl bg-sky-500 hover:bg-sky-400 text-white font-semibold text-sm">Run assessment →</button>
        </div>
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

function App() {
  const [run, setRun] = useState(emptyRun);
  const [tab, setTab] = useState("loop");
  const esRef = useRef(null);

  const start = useCallback((query, demo) => {
    if (esRef.current) esRef.current.close();
    setRun({ ...emptyRun(), status:"running", meta:{ query } });
    setTab("loop");
    const url = `/api/run?query=${encodeURIComponent(query)}&demo=${demo?1:0}`;
    const es = new EventSource(url);
    esRef.current = es;
    const on = (name) => es.addEventListener(name, (e)=>{
      const data = JSON.parse(e.data);
      setRun(prev => reduceEvent(prev, name, data));
      if (name === "done" || name === "error") es.close();
    });
    ["start","phase","briefing","plan","evidence","node","edge","review","synthesis","done","error"].forEach(on);
    es.onerror = () => { setRun(prev => prev.status==="done"?prev:reduceEvent(prev,"error",{message:"connection lost — is server.py running?"})); es.close(); };
  }, []);

  useEffect(()=>()=>{ if(esRef.current) esRef.current.close(); }, []);

  // shareable / auto-run links: /?q=...&demo=1 starts immediately
  useEffect(()=>{
    const p = new URLSearchParams(window.location.search);
    const q = p.get("q");
    if (q) start(q, p.get("demo") !== "0");
    if (p.get("tab")) setTab(p.get("tab"));
  }, [start]);

  if (run.status === "idle") return <QueryScreen onRun={start}/>;

  const stepsDone = run.steps.filter(s=>s.status==="done").length;
  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 py-8">
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
