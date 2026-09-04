# Evaluation methodology

## CTXBench paired study

Dataset compatibility follows the [CTXBench/AgentBench paper](https://arxiv.org/abs/2602.11988) and its [official harness](https://github.com/eth-sri/agentbench). CTXBench Desktop adds the paired frozen-context experiment around the same repository tasks; it does not rewrite their task prompts.

The primary estimand is the within-task, within-repeat effect of a frozen context package. A pair fixes repository commit, task text, hidden tests, coding-agent image/version, provider, model, thinking level, token budget, runtime resources, timeout, and network policy. Only repository context files differ.

Supported arms are:

- `none`: remove historical `AGENTS.md`, `CLAUDE.md`, Copilot instructions, and `.ctx/**` files.
- `skill-generated`: remove historical context, then overlay one context artifact generated from the exact base commit.
- `manual`: remove historical context, then overlay a human-supplied artifact for the same base commit.
- `developer-historical`: retain context present at that historical base commit.

Tree-only generation is the primary profile. History-aware generation may inspect only material at or before the declared cutoff. Task-informed artifacts are labeled and excluded from primary estimates.

Report pass rate per arm, paired difference, confidence interval, run-to-run variance, and pairwise win/loss/tie. Compare context effect sizes across model blocks; do not interpret model A/no-context versus model B/context as a context effect.

## SWE-Shield-compatible layer

CTXBench implements a versioned compatible profile of the methodology described in [Does Pass Rate Tell the Whole Story?](https://arxiv.org/abs/2604.05955). It does not claim bit-for-bit reproduction without the authors' complete replication package.

DesignHunter-compatible extraction:

1. Normalize review threads into non-overlapping windows of six comments; each window receives only its preceding window as conversational context.
2. Extract atomic design suggestions, rationale, applicability, code references, provenance, and adopted/non-adopted alternatives. Verify adoption against PR commit history and before/after code.
3. Represent candidates with problem text weighted `0.8` and suggestion text weighted `0.2`. Combine semantic similarity at `0.8` with structural/provenance similarity at `0.2`.
4. Cluster at threshold `0.6`, then synthesize a constraint while preserving every source reference. Automatic output is `silver`; human review may promote it to `gold`.
5. Associate constraints through explicit issue/PR traceability or semantic alignment between the hidden gold-patch intent and repository constraints.

Patch verification first judges applicability, then returns Satisfied, Violated, or Neutral with rationale and code/source references. Research mode uses three independently frozen judge configurations. Satisfied or Violated requires two votes; all other outcomes are Neutral. Fast mode may judge test-passing patches only and must be labeled.

Issue-level metrics are mutually exclusive:

- `DSR = satisfied issues / all judged issues`
- `DVR = violated issues / all judged issues`
- `DNR = neutral issues / all judged issues`
- `PPVR = test-passing violated issues / test-passing applicable issues`

Also report Pass & Satisfied, Pass & Violated, Fail & Satisfied, and Fail & Violated. Formal reports use Research mode, separate silver from gold constraints, and retain the frozen miner/judge model IDs, prompt hashes, and voting records.

The target PR, gold patch, hidden tests, and mined constraints are evaluator-only. Primary experiments do not expose constraints to the coding agent. A future constraint-guided refinement workflow must be a separately labeled experimental arm.
