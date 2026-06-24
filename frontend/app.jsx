
const { useState, useMemo } = React;
const D = window.CSO_DEMO;

// ---- provenance + confidence helpers (mirror docs/kg-pareto-provenance-design.md §5) ----
const PROV = {
  retrieved: { icon: "🗄️", label: "retrieved — public API" },
  computed:  { icon: "🔧", label: "computed — ClawBio skill" },
  web:       { icon: "🌐", label: "agent web / literature" },
  gap:       { icon: "⚪", label: "gap — not available" },
};
const gradeStyle = (g) => ({
  strong:       "text-emerald-300 border-emerald-500/40 bg-emerald-500/10",
  supported:    "text-sky-300 border-sky-500/40 bg-sky-500/10",
  suggestive:   "text-amber-300 border-amber-500/40 bg-amber-500/10",
  insufficient: "text-slate-400 border-slate-600/40 bg-slate-700/20",
}[g] || "text-slate-400 border-slate-600/40");

const DECISION = {
  GO:             { c: "bg-emerald-500 text-emerald-950", ring:"ring-emerald-400/40" },
  CONDITIONAL_GO: { c: "bg-amber-400 text-amber-950",     ring:"ring-amber-300/40" },
  REVIEW:         { c: "bg-sky-400 text-sky-950",         ring:"ring-sky-300/40" },
  NO_GO:          { c: "bg-rose-500 text-rose-950",       ring:"ring-rose-400/40" },
};

// ---- the loop, modeled as ordered steps from the fixtures ----
const buildLoop = () => {
  const b = D.briefing, r = D.review, s = D.synthesis;
  return [
    { id:"briefing", role:"Chief of Staff", division:"Office of CSO", kind:"agent",
      title:"Field briefing", prov:"web", grade:"supported",
      summary:b.context,
      detail:{ "Priority questions":b.priority_questions, "Feasibility flags":b.feasibility_flags, "Data available":b.data_availability } },
    { id:"step_01", role:"gwas-lookup", division:"Target ID", kind:"skill",
      title:"Germline genetic support?", prov:"retrieved", grade:"insufficient",
      summary:D.step_01_gwas.summary, detail:{ Interpretation:[D.step_01_gwas.interpretation] } },
    { id:"step_02", role:"scrna-embedding", division:"Target ID", kind:"skill",
      title:"Which cell types express it?", prov:"computed", grade:"supported",
      summary:D.step_02_celltype_expression.summary,
      table:D.step_02_celltype_expression.top_cell_types },
    { id:"step_03", role:"celltype-specificity-profiler", division:"Target ID", kind:"skill",
      title:"How cell-type-specific?", prov:"computed", grade:"strong",
      metric:{ "τ (tau)":D.step_03_celltype_specificity.tau, "bimodality":D.step_03_celltype_specificity.bimodality_coefficient },
      summary:D.step_03_celltype_specificity.summary,
      detail:{ Interpretation:[D.step_03_celltype_specificity.interpretation] } },
    { id:"step_04", role:"celltype-specificity-profiler", division:"Target Safety", kind:"skill",
      title:"Off-target tissue risk?", prov:"computed", grade:"supported",
      summary:D.step_04_offtarget_safety.summary,
      detail:{ "Broad-tissue risk":[D.step_04_offtarget_safety.broad_tissue_risk] } },
    { id:"step_05", role:"clinical-trial-finder", division:"Clinical", kind:"skill",
      title:"Prior trials / outcomes", prov:"retrieved", grade:"supported",
      summary:D.step_05_clinical_trials.summary,
      detail:{ "Example programs":D.step_05_clinical_trials.example_programs } },
    { id:"review", role:"Scientific Reviewer", division:"Audit loop", kind:"agent",
      title:`Audit → ${r.verdict.toUpperCase()}`, prov:"web", grade:"supported",
      verdict:r.verdict, scores:r.scores,
      summary:`Reviewer scored relevance ${r.scores.relevance}/5, evidence ${r.scores.evidence}/5, thoroughness ${r.scores.thoroughness}/5 and returned “${r.verdict}”.`,
      detail:{ "Gap flagged":r.gaps.map(g=>`${g.missing} → re-route to ${g.route_to}`) },
      gaps:r.gaps },
    { id:"step_06", role:"scrna-orchestrator", division:"Target ID (re-route)", kind:"skill",
      title:"Spatial immune exclusion?", prov:"computed", grade:"strong", reroute:true,
      summary:D.step_06_reroute.summary,
      detail:{ Interpretation:[D.step_06_reroute.interpretation] } },
    { id:"synth", role:"CSO Orchestrator", division:"Synthesis", kind:"agent",
      title:`Synthesize → ${s.decision}`, prov:"web", grade:"strong", terminal:true,
      summary:s.recommendation },
  ];
};

function Chip({children, cls=""}) {
  return <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium border ${cls}`}>{children}</span>;
}

function ProvBadge({prov}) {
  const p = PROV[prov];
  return <Chip cls="border-slate-600/50 text-slate-300 bg-slate-800/50" >{p.icon}<span className="hidden sm:inline">{p.label.split(" — ")[0]}</span></Chip>;
}

function StepCard({step, idx, active, onClick}) {
  const kindCls = step.kind === "agent" ? "border-violet-500/40 bg-violet-500/5" : "border-slate-700 bg-slate-900/60";
  return (
    <div className="flex gap-4 fade-up" style={{animationDelay:`${idx*60}ms`}}>
      {/* rail */}
      <div className="flex flex-col items-center">
        <div className={`w-9 h-9 rounded-full grid place-items-center text-sm font-bold border-2 cursor-pointer transition
          ${active ? "border-sky-400 bg-sky-400/20 text-sky-200 pulse-ring" : step.terminal ? "border-emerald-400 bg-emerald-400/20 text-emerald-200"
          : step.reroute ? "border-amber-400 bg-amber-400/20 text-amber-200" : "border-slate-600 bg-slate-800 text-slate-300"}`}
          onClick={onClick}>
          {step.terminal ? "✓" : idx+1}
        </div>
        {idx < 8 && <div className={`w-0.5 flex-1 my-1 ${step.reroute ? "bg-amber-500/40" : "bg-slate-700"}`} style={{minHeight:"1rem"}} />}
      </div>
      {/* card */}
      <div className={`flex-1 mb-3 rounded-xl border p-4 cursor-pointer transition hover:border-sky-500/50 ${kindCls} ${active?"ring-1 ring-sky-400/50":""}`}
        onClick={onClick}>
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <Chip cls={step.kind==="agent" ? "border-violet-500/40 text-violet-300 bg-violet-500/10" : "border-slate-600 text-slate-300 bg-slate-800"}>
              {step.kind==="agent" ? "AGENT" : "SKILL"}
            </Chip>
            <span className="mono text-xs text-slate-400">{step.role}</span>
          </div>
          <div className="flex items-center gap-2">
            <ProvBadge prov={step.prov} />
            <Chip cls={gradeStyle(step.grade)}>{step.grade}</Chip>
          </div>
        </div>
        <div className="mt-2 text-sm font-semibold text-slate-100">{step.title}</div>
        <div className="text-xs text-slate-400">{step.division}</div>
        {step.metric && (
          <div className="flex gap-4 mt-2">
            {Object.entries(step.metric).map(([k,v])=>(
              <div key={k} className="bg-slate-950/60 rounded-lg px-3 py-1.5 border border-slate-700">
                <div className="mono text-lg font-bold text-emerald-300">{v}</div>
                <div className="text-[10px] uppercase tracking-wide text-slate-500">{k}</div>
              </div>
            ))}
          </div>
        )}
        <p className="mt-2 text-sm text-slate-300 leading-relaxed">{step.summary}</p>
        {active && step.table && (
          <table className="mt-3 w-full text-xs">
            <thead><tr className="text-slate-500 text-left"><th className="py-1">cell type</th><th>mean expr</th><th>% expressing</th></tr></thead>
            <tbody>{step.table.map((r,i)=>(
              <tr key={i} className="border-t border-slate-800"><td className="py-1 text-slate-300">{r.cell_type}</td><td className="mono text-slate-400">{r.mean_expr}</td><td className="mono text-slate-400">{(r.pct_expressing*100).toFixed(0)}%</td></tr>
            ))}</tbody>
          </table>
        )}
        {active && step.detail && (
          <div className="mt-3 space-y-2">
            {Object.entries(step.detail).map(([k,vals])=>(
              <div key={k}>
                <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">{k}</div>
                <ul className="space-y-1">{vals.map((v,i)=><li key={i} className="text-xs text-slate-300 flex gap-2"><span className="text-slate-600">›</span>{v}</li>)}</ul>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Report() {
  const s = D.synthesis;
  const dec = DECISION[s.decision] || DECISION.REVIEW;
  return (
    <div className="space-y-5">
      <div className={`rounded-2xl border border-slate-700 bg-slate-900/60 p-6 ring-1 ${dec.ring}`}>
        <div className="text-xs uppercase tracking-widest text-slate-500 mb-2">Executive summary</div>
        <div className="flex items-center gap-3 flex-wrap">
          <span className={`px-4 py-1.5 rounded-lg font-extrabold text-sm ${dec.c}`}>{s.decision.replace("_"," ")}</span>
          <Chip cls="border-slate-600 text-slate-300 bg-slate-800">confidence: {s.confidence}</Chip>
        </div>
        <p className="mt-4 text-sm text-slate-200 leading-relaxed">{s.recommendation}</p>
        <p className="mt-3 text-xs text-slate-400 leading-relaxed border-t border-slate-800 pt-3">{s.target_overview}</p>
      </div>

      <div className="grid md:grid-cols-2 gap-5">
        <Panel title="Liabilities & risks" accent="rose">
          {s.liabilities.map((l,i)=>(
            <div key={i} className="mb-3 last:mb-0">
              <div className="text-sm text-slate-200">{l.risk}</div>
              <div className="text-xs text-emerald-300/80 mt-0.5">↳ mitigation: {l.mitigation}</div>
            </div>
          ))}
        </Panel>
        <Panel title="Evidence gaps" accent="amber">
          <ul className="space-y-2">{s.evidence_gaps.map((g,i)=><li key={i} className="text-sm text-slate-300 flex gap-2">⚪ {g}</li>)}</ul>
        </Panel>
      </div>

      <Panel title="Proposed experiments" accent="sky">
        <div className="grid sm:grid-cols-2 gap-3">
          {s.proposed_experiments.map((e,i)=>(
            <div key={i} className="rounded-lg border border-slate-700 bg-slate-950/40 p-3">
              <div className="text-sm font-semibold text-slate-100">{e.experiment}</div>
              <div className="text-xs text-sky-300/80 mt-1">readout: {e.expected_readout}</div>
              <div className="text-xs text-slate-400 mt-1">{e.rationale}</div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function Panel({title, accent, children}) {
  const a = {rose:"text-rose-300", amber:"text-amber-300", sky:"text-sky-300"}[accent] || "text-slate-300";
  return (
    <div className="rounded-2xl border border-slate-700 bg-slate-900/60 p-5">
      <div className={`text-xs uppercase tracking-widest mb-3 ${a}`}>{title}</div>
      {children}
    </div>
  );
}

function App() {
  const loop = useMemo(buildLoop, []);
  const [tab, setTab] = useState("report");
  const [active, setActive] = useState(null);

  const liveSteps = loop.filter(s=>s.kind==="skill").length;
  const strong = loop.filter(s=>s.grade==="strong").length;

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 py-8">
      {/* header */}
      <div className="flex items-start justify-between gap-4 flex-wrap mb-6">
        <div>
          <div className="flex items-center gap-2 text-xs text-sky-400 mono mb-1">virtual-biotech-cso · multi-agent harness</div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-white">Target Assessment — B7-H3 / CD276</h1>
          <p className="text-sm text-slate-400 mt-1 italic">“Assess B7-H3 potential as a therapeutic target in lung cancer.”</p>
        </div>
        <div className="flex gap-2 text-center">
          <Stat n={loop.length} l="loop steps" />
          <Stat n={liveSteps} l="skills routed" />
          <Stat n={strong} l="strong-grade" />
        </div>
      </div>

      {/* tabs */}
      <div className="flex gap-1 p-1 rounded-xl bg-slate-900/60 border border-slate-800 w-fit mb-6">
        {[["report","Report"],["loop","Loop trace"]].map(([k,l])=>(
          <button key={k} onClick={()=>setTab(k)}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition ${tab===k?"bg-sky-500 text-white":"text-slate-400 hover:text-slate-200"}`}>{l}</button>
        ))}
      </div>

      {tab==="report" ? <Report/> : (
        <div>
          <div className="flex items-center gap-3 mb-5 text-xs text-slate-400 flex-wrap">
            {Object.entries(PROV).map(([k,p])=><span key={k}>{p.icon} {p.label}</span>)}
          </div>
          <div className="rounded-2xl border border-slate-800 bg-slate-900/30 p-5">
            {loop.map((step,i)=>(
              <StepCard key={step.id} step={step} idx={i} active={active===step.id}
                onClick={()=>setActive(active===step.id?null:step.id)} />
            ))}
          </div>
          <p className="text-xs text-slate-600 mt-3">Click any step to expand its inputs, metrics, and provenance. The amber step is the Reviewer's one-pass re-route; the loop terminates at synthesis.</p>
        </div>
      )}

      <div className="mt-8 pt-4 border-t border-slate-800 text-xs text-slate-600">
        Rendered from <span className="mono">demo_data/b7h3/</span> — illustrative cached fixtures, labelled as such. Live runs generate this via <span className="mono">prompts/orchestrator.md</span>.
      </div>
    </div>
  );
}
function Stat({n,l}){return <div className="px-3 py-2 rounded-xl bg-slate-900/60 border border-slate-800"><div className="text-xl font-bold text-white">{n}</div><div className="text-[10px] uppercase tracking-wide text-slate-500">{l}</div></div>;}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
  