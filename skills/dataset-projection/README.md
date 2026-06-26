# dataset-projection — get many datasets *reasonable-over* in Prometheux

**The problem.** Prometheux/JarvisPy is a hosted Vadalog (Datalog⁺) **reasoning
engine**, not a data store. It reasons over *facts* — ground relational atoms
declared via `@bind`. It cannot ingest raw experimental matrices (expression,
sequencing) or documents (PDFs, papers): those aren't facts and aren't tractable
as facts at raw scale.

**The pattern.** Never upload the raw data. Upload its **conclusions, shaped as
facts**, and let the engine join and reason across all of them — the one thing it
does that a database doesn't: explainable cross-dataset deduction (`@explain`).

```
RAW (stays put)              PROJECT (this layer)            REASON (Prometheux)
matrices, PDFs, JSON   ──▶   one extractor per dataset  ──▶  @bind projected_facts.csv
object store / disk          → normalized fact CSV            + kg_csv (PrimeKG)
                               (facts.py contract)            → derive + @explain
```

## The contract (`facts.py`)

Every extractor emits rows in ONE schema, so "many datasets" = "many extractors,
one bind format":

| column | meaning |
|---|---|
| `subject` | node id, kg.py style (`gene:cd8a`, `celltype:b-cells`) |
| `relation` | edge type (`EXPRESSED_IN`, `GENETIC_LINK`, …) |
| `object` | the other node id |
| `value` | human-readable summary of the conclusion |
| `confidence` | float [0,1] — the engine gates on it (STRONG_CONF=0.8) |
| `source_dataset` | provenance/bind key |
| `provenance` | traceable pointer to the raw source (file#row, doi, …) |

`Fact` validates these; `node_id(kind, label)` builds ids; `write_facts()` writes
the canonical CSV.

## Adding a dataset

1. Write `extractors/<name>.py` that reads your raw data **where it lives** and
   `yield`s `Fact` rows (do any numeric/NLP work here, outside the engine).
2. Run it → a `*.facts.csv`. Concatenate all into `projected_facts.csv`.
3. It binds next to PrimeKG automatically — `bind.vada` already declares both.

| dataset kind | extractor does | emits |
|---|---|---|
| scRNA matrix (`.h5ad`) | per-cell-type prevalence/mean (see `pbmc3k_expression.py`) | `EXPRESSED_IN` |
| GWAS / association table | filter to significant rows | `GENETIC_LINK` |
| documents (PDF/paper) | offline lexicon match, or `--llm` Gemini extractor (DOI provenance) | varies |
| assay results | call/threshold outside, project the call | varies |

## Worked example (real data)

`extractors/pbmc3k_expression.py` projects the downloaded
`data/pbmc3k_processed.h5ad` (2638 cells × 1838 genes, louvain labels):

```bash
python3 extractors/pbmc3k_expression.py --genes CD8A,MS4A1,CD14,NKG7,CD3D,FCGR3A --min-frac 0.6
```

yields canonical markers — `CD3D→T cells`, `MS4A1→B cells`, `NKG7→NK cells`,
`CD14→monocytes` — as `EXPRESSED_IN` facts with confidence = expressing fraction.

### LLM document extraction (`--llm`, verified live)

`literature_claims.py --llm` uses **Gemini** via its OpenAI-compatible endpoint
(`GEMINI_API_KEY`, JSON mode — the same backend the CSO harness uses). Verified on
the sample abstracts: it out-performed the offline matcher — typed relations
correctly (B7-H3 *overexpressed*→`EXPRESSED_IN` vs EGFR *mutated*→`GENETIC_LINK`),
caught a claim the lexicon missed, and calibrated confidence (0.6 expression / 0.9
direct genetic / 0.7 association) once the schema asked it to.

**Known limitation:** the claim schema only offers `disease` as the object, so the
model forces cell types / processes into disease slots (`disease:b-cells`). Extend
`_CLAIM_SCHEMA` with an object-kind field (`disease` | `celltype` | `process`) when
you need those distinguished.

## Reasoning across datasets (`bind.vada`)

Binds `projected_facts.csv` alongside `kg_csv` (PrimeKG) and derives
`marker_disease_link(G, C, Disease)` — a strong single-cell marker that PrimeKG
also ties to a disease. **This conclusion exists from neither source alone**; it
only appears because both are bound in the same engine. Run it via the same
project → concept → run → fetch path as
[prometheux_reason.py](../virtual-biotech-cso/prometheux_reason.py).

## Running it live (`run_live.py`) — verified 2026-06-26

`python run_live.py` (with `.env` loaded) joins the projected facts against the
live PrimeKG `kg_csv` and derives `marker_disease_link`. **Verified: 7 strong
single-cell markers → 32 disease links**, all biologically coherent
(CD3D→severe combined immunodeficiency / MHC class II deficiency; FCGR3A→defective
NK-cell cytotoxicity; MS4A1→common variable immunodeficiency).

**Key constraint — the SDK has no file-upload endpoint.** Every JarvisPy client
method is projects/sources/concepts *metadata*; `connect_sources` only registers a
*database connection* and 500s on a local CSV. PrimeKG's `kg.csv` was placed on the
engine's `disk/` out-of-band via the **web app's file upload**. So:

- **Small projected sets** (the normal case — facts are meant to be few): `run_live.py`
  inlines them as `cell_marker(...)` ground atoms in the program. No upload needed.
- **Large projected sets**: upload the `*.facts.csv` in the web app (Local Files),
  then use the two-bind `bind.vada` form instead of inlining.

## Feeding projections into the CSO loop (`to_cso.py`) — verified

`python to_cso.py out/*.facts.csv` upserts one evidence edge per fact into the CSO
knowledge graph ([../virtual-biotech-cso/kg.py](../virtual-biotech-cso/kg.py)), so
the imported facts flow through the same reasoning as live-routed steps —
`prometheux_reason.py --decide / --gaps / --rank` all see them.

Mapping: `EXPRESSED_IN`→`specificity` axis, `GENETIC_LINK`→`genetics`; confidence→
`conf`+grade (≥0.8 strong, ≥0.5 supporting, >0 suggestive); `source_dataset`/
`provenance`→`source`/`ref`. **Verified** (15 facts from pbmc3k+literature into a
throwaway store): the decision layer scored specificity=strong + genetics=supporting
and correctly returned `NO_GO` via the safety hard-gate (no safety read).

**Markers vs targets.** A `gene:`-prefixed scRNA *marker* (CD3D, CD14) is not a
therapeutic target. The importer orients `EXPRESSED_IN` gene→celltype facts as
celltype→gene so the marker never becomes an evidence subject, and the CSO
gap-detector only treats nodes with *prioritization-axis* evidence (or declared
`Target` nodes) as targets — so markers and cell types are no longer flagged.
Verified: importing pbmc3k + literature leaves only the real `target:` candidates
(CD276, B7-H3, EGFR, KRAS, MET) as targets.

## Operational notes (from the verified live integration)

- Bound CSVs sit on the **compute machine's disk** (`disk/`); the machine
  idle-suspends and must be active to run (`NO_ACTIVE_COMPUTE` otherwise).
- `run_concept(..., persist_outputs=True)` is required; `fetch_results` rows are
  nested at `["results"]["facts"]`; `page_size` ∈ 1–1000.
- Keep raw data out of git and out of the engine; only the projected fact CSVs
  (small, joinable) get bound.
