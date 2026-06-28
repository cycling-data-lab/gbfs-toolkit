# Validating an audit by hand

The A1–A7 audit compares *algorithms*; it cannot, on its own, establish that a
flag matches the physical world. A reviewer will ask for a construct-validity
check: a panel re-examines a stratified sample of stations against external
imagery, blind to the pipeline's output and to each other, and you report how well
the human verdicts agree and how the flags line up against them. This is
methodology, not a per-feed task, so the toolkit ships the coefficients rather than
a workflow.

## Inter-rater agreement

Agreement must be chance-corrected: two annotators who both call 95% of stations
"in perimeter" agree most of the time *by luck*.
[`krippendorff_alpha`][gbfs_toolkit.krippendorff_alpha] is the primary measure (it
handles missing ratings and more than two raters);
[`cohen_kappa`][gbfs_toolkit.cohen_kappa] is the familiar two-rater coefficient for
comparability against the "substantial agreement" benchmark.

```python
import gbfs_toolkit as gb

# Rows are raters, columns are units; nan where a rater did not label a unit.
ratings = [[1, 2, 3, 3, 2, 1, None],
           [1, 2, 3, 3, 2, 2, 5]]
gb.krippendorff_alpha(ratings)   # nominal alpha in [-1, 1]; 1 = perfect agreement
gb.cohen_kappa(ratings[0], ratings[1])
```

A high $\alpha$ on the judgements that carry the audit's verdicts (is this a
bike-share system? is there a physical dock?) supports the construct; a low one on
a judgement is itself a finding — for example, two domain experts diverging on what
`capacity` *means* is a human-side manifestation of the very field ambiguity the
taxonomy formalises.

## Per-rule performance with honest intervals

Derive each rule's true/false positives *a posteriori* by joining the adjudicated
factual answers with the flags (never ask an annotator to label "the pipeline is
wrong" — that bakes in the circularity). Then report precision and recall as
proportions with a [`wilson_interval`][gbfs_toolkit.wilson_interval], which stays
inside $[0, 1]$ and behaves at small samples where the normal approximation fails:

```python
tp, fp = 68, 2
precision = tp / (tp + fp)
lo, hi = gb.wilson_interval(tp, tp + fp)   # 95% interval on the precision
```

Read screening filters for what they are: a high-recall A4/A5 triage that compresses
the catalogue to a candidate set a human can inspect is *meant* to over-include, so
its standalone precision is not the decisive number — whether the flags it removes
are genuine false positives is.
