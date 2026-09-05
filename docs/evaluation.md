# Evaluation methodology

## CTXBench paired study

Dataset compatibility follows the [CTXBench/AgentBench paper](https://arxiv.org/abs/2602.11988) and its [official harness](https://github.com/eth-sri/agentbench). CTXBench Desktop adds the paired frozen-context experiment around the same repository tasks; it does not rewrite their task prompts.

The primary estimand is the within-task, within-repeat effect of a frozen context package. A pair fixes repository commit, task text, hidden tests, coding-agent image/version, provider, model, thinking level, token budget, runtime resources, timeout, and network policy. Only repository context files differ.

Supported arms are:

- `none`: remove historical `AGENTS.md`, `CLAUDE.md`, Copilot instructions, and `.ctx/**` files.
- `skill-generated`: remove historical context, then overlay one context artifact generated from the exact base commit.
- `manual`: remove historical context, then overlay an explicitly selected frozen artifact for the same base commit. Its provenance distinguishes generated versus human-supplied content.
- `developer-historical`: retain context present at that historical base commit.

Only task-blind tree-only artifact generation/import is supported in the primary workflow. History-aware and task-informed generation are not enabled. Manual artifact authors must truthfully declare their baseline and avoid target-task information; the tool cannot prove authorship provenance from arbitrary text.

Report pass rate per arm, paired difference, confidence interval, run-to-run variance, and pairwise win/loss/tie. Compare context effect sizes across model blocks; do not interpret model A/no-context versus model B/context as a context effect.

## SWE-Shield-compatible layer

CTXBench implements a versioned compatible profile of the methodology described in [Does Pass Rate Tell the Whole Story?](https://arxiv.org/abs/2604.05955). It does not claim bit-for-bit reproduction without the authors' complete replication package.

Implemented extraction profile (`review-grounded-llm-v1`):

1. Derive the cutoff from the exact baseline commit timestamp. Scan at most 10 pages of repository PR-review comments, inspect up to 10 PRs, retain up to 50 comments from PRs already merged by the cutoff. This is a bounded sample, not exhaustive history. Comments edited after the cutoff are excluded; unavailable historical PR text revisions are not inferred.
2. A task-blind miner reads the frozen review archive, commit messages and final patches. It extracts atomic decisions, rationale, applicability, source references and adoption evidence. Schema validation requires provenance and at least one adopted option per constraint. Model-supported adoption is not equivalent to human confirmation.
3. Freeze the validated package as silver. The actual pipeline does **not** currently use the research helpers for six-comment windows, embeddings, 0.8/0.2 similarity or clustering; those helpers are tested primitives, not a completed paper-reproduction pipeline. No gold-promotion UI or gold-patch-based constraint association is claimed.
4. Judges independently assess applicability to the target task and produced patch. Empty/inapplicable packages may yield neutral outcomes, but their absence is not evidence that the patch is compliant.

Patch verification first judges applicability, then returns Satisfied, Violated, or Neutral with rationale and code/source references. Research mode uses three independently frozen judge configurations in separate sessions. Satisfied or Violated requires two votes; all other complete three-judge outcomes are Neutral. Failed or malformed judge output is an infrastructure failure and must be retried. Fast/single-judge mode is not exposed.

Issue-level metrics are mutually exclusive:

- `DSR = satisfied issues / all judged issues`
- `DVR = violated issues / all judged issues`
- `DNR = neutral issues / all judged issues`
- `PPVR = test-passing violated issues / test-passing applicable issues`

Also report Pass & Satisfied, Pass & Violated, Fail & Satisfied, and Fail & Violated. Formal reports use Research mode, separate silver from gold constraints, and retain the frozen miner/judge model IDs, prompt hashes, and voting records.

Functional grades are retained even if a later judge fails. Functional metrics require a boolean grader outcome; compliance metrics require a valid judgment. Missing data is never implicitly a failed test or neutral judgment. Mock Provider results are excluded from real aggregates. Lift and W/L/T require matched experiment, pair, input fingerprint and execution type. Per-experiment lift averages within-task repeat differences equally across tasks. Confidence intervals use task-cluster bootstrap (2,000 draws, seed 42); fewer than two independent tasks yields no interval. These diagnostics do not eliminate selection bias or justify a performance claim from smoke tests.

The target PR, gold patch, hidden tests, and mined constraints are evaluator-only. Primary experiments do not expose constraints to the coding agent. A future constraint-guided refinement workflow must be a separately labeled experimental arm.
