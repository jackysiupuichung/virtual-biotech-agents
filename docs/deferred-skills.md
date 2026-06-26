# Deferred skills — TODO

Skills referenced in `routing.yaml` that do **not** execute live yet. The planner and
the deterministic plan only expose `FUNCTIONAL_SKILLS` (see `cso.py`); these are tracked
here. Promote one into `FUNCTIONAL_SKILLS` once it runs end-to-end.

| Skill | Why deferred | To make functional |
|---|---|---|
| `scrna-embedding` | ClawBio skill exists but needs an `.h5ad` atlas input we don't fetch live | wire `cellxgene-fetch` → pass its h5ad to `clawbio run scrna-embedding` |
| `cellxgene-fetch` | in-repo script, but the live CELLxGENE Census query needs a resolved gene+tissue and returns large data | pass resolved `--gene/--disease`; cache the fetched h5ad |
| `opentargets-association-evidence` | in-repo; live Open Targets API returned no rows for B7-H3 (needs Ensembl id, not symbol) | resolve symbol→Ensembl via the alias resolver before the call |
| `pathway-enricher` | ClawBio skill exists but needs a gene-list input | feed it the gene set from an upstream step |
| `gwas-catalog-region-fetch` | ClawBio `gwas-region` needs a genomic window (chr:start-end) | derive the region from the lead variant |
| `fine-mapping` | no ClawBio counterpart | add upstream or drop from routing |
| `struct-predictor` | no ClawBio counterpart | add upstream or drop from routing |
| `omics-target-evidence-mapper` | no ClawBio counterpart | add upstream or drop from routing |
| `claw-ancestry-pca` | no ClawBio counterpart (only `compare`/`equity` exist) | map or drop |
| `turingdb-graph` | no ClawBio counterpart | add upstream or drop |

Verified-functional today (in `FUNCTIONAL_SKILLS`): celltype-specificity-profiler,
clinical-trial-finder, clinpgx, crispr-screen-triage, equity-scorer, gwas-lookup,
lit-synthesizer, malignant-expression-profiler, openfda-safety,
opentargets-target-factors, tcga-somatic-profiler.
