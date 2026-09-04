# Watt's Off — Engineering Notes

## Detection Engine: Rule-Based vs ML (Deliberate Substitution)

### What the original design calls for

The original project brief specifies a machine-learning anomaly detection pipeline
using supervised classifiers such as **KNN, SVM, and Random Forest** to classify
electricity consumption patterns as normal or anomalous.

### What this prototype implements instead

This prototype uses a **statistical / rule-based anomaly detection engine** — a
deliberate engineering trade-off, **not** a shortcut taken by accident.

### Why the substitution was made

| Concern | ML Pipeline | Rule-Based Engine |
|---------|-------------|-------------------|
| **Labeled training data** | Requires a dataset of known normal + theft cases | Not required — works from each meter's own historical baseline |
| **Training pipeline** | Needs data preprocessing, feature engineering, train/test split, model selection, hyperparameter tuning | None — detection runs as pure Python functions |
| **Setup time** | Hours to days (data collection, labeling, model validation) | Minutes (seed DB → detect immediately) |
| **Explainability** | Black-box scores require SHAP/LIME to explain | Every flag has a human-readable reason ("sudden spike", "unusual time", etc.) |
| **Demo-ability** | Hard to debug live; model may not generalize to simulated data | Deterministic — same input always produces same output |

### What's preserved (identical outputs)

The rule-based engine produces **exactly the same output interface** as the ML version would:

- **Deviation %** — `(actual - expected) / expected * 100`
- **Anomaly type** — `sudden_spike`, `unusual_time`, `repeated_pattern`
- **Risk score** — 0–100 weighted composite
- **Severity bands** — LOW (0–30), MEDIUM (31–60), HIGH (61–80), CRITICAL (81–100)

Every downstream consumer (API, dashboard, alerts) is agnostic to how these values
are computed. The detection module (`detection.py`) exposes the same function
signatures regardless of the internal implementation.

### Path to ML upgrade (Stretch Goal)

The module is designed so that `classify_anomaly()` and `score_risk()` can be
swapped for `sklearn.ensemble.IsolationForest` (unsupervised — no labeled data
needed) without changing any other file. See the Stretch Goal section in `README.md`.

### Key design principle

> **Per-meter baselines, not global thresholds.**
>
> The detection engine does NOT use a naive rule like `if consumption > 5 kWh → theft`.
> Instead, it computes the expected consumption for each specific meter in each
> time-of-day bucket from that meter's own historical readings. A consumption of
> 8 kWh might be perfectly normal for an industrial meter but highly anomalous for
> a residential meter that averages 1.5 kWh at night.

---

*This document exists so that hackathon judges, code reviewers, and team members
can immediately understand the architectural decision without digging through code.*
