"""Reproducible experiment runs. Each writes JSON results and a Markdown report."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from moneyos.ml import categorizer as cat
from moneyos.ml.corpus import CATEGORIES, make_corpus

# Pre-registered selection rule (written down before the full run).
SIMPLICITY_ORDER = ("tfidf_logreg", "tfidf_random_forest", "tfidf_xgboost")
SELECTION_RULE = (
    "Highest mean macro-F1 on unseen merchants; if a simpler candidate (logistic regression < random "
    "forest < XGBoost) is within one standard deviation of the best, choose the simpler one. The choice must "
    "beat the app's current rules on unseen merchants."
)


def select(unseen: dict[str, cat.ModelResult]) -> str:
    best = max(SIMPLICITY_ORDER, key=lambda n: unseen[n].mean("macro_f1"))
    margin = unseen[best].std("macro_f1")
    for name in SIMPLICITY_ORDER:  # simplest first
        if unseen[name].mean("macro_f1") >= unseen[best].mean("macro_f1") - margin:
            return name
    return best  # pragma: no cover


def _merge(runs: list[dict[str, cat.ModelResult]]) -> dict[str, cat.ModelResult]:
    merged = {}
    for name in runs[0]:
        result = cat.ModelResult(name, runs[0][name].split)
        for run in runs:
            result.folds += run[name].folds
            result.y_true += run[name].y_true
            result.y_pred += run[name].y_pred
        merged[name] = result
    return merged


def _row(r: cat.ModelResult) -> dict:
    metrics = ("accuracy", "macro_precision", "macro_recall", "macro_f1", "coverage", "covered_accuracy", "fit_seconds")
    return {m: {"mean": round(r.mean(m), 4), "std": round(r.std(m), 4)} for m in metrics} | {"folds": len(r.folds)}


def _confusion_png(result: cat.ModelResult, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from moneyos.analytics.charts import INK, INK_SECONDARY, SURFACE

    labels = list(CATEGORIES)
    matrix = cat.confusion(result, labels + [cat.UNCATEGORIZED])[: len(labels), : len(labels)]
    shares = matrix / matrix.sum(axis=1, keepdims=True).clip(min=1)
    fig, ax = plt.subplots(figsize=(7.5, 6.5))
    fig.set_facecolor(SURFACE)
    # Sequential: one hue, light to dark (reference palette blue ramp).
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("blue", ["#f7fafe", "#86b6ef", "#256abf", "#0d366b"])
    ax.imshow(shares, cmap=cmap, vmin=0, vmax=1)
    for i in range(len(labels)):
        for j in range(len(labels)):
            if matrix[i, j]:
                ax.text(j, i, f"{shares[i, j]:.0%}", ha="center", va="center", fontsize=7,
                        color="#ffffff" if shares[i, j] > 0.55 else INK)
    ax.set_xticks(range(len(labels)), labels, rotation=45, ha="right", fontsize=8, color=INK_SECONDARY)
    ax.set_yticks(range(len(labels)), labels, fontsize=8, color=INK_SECONDARY)
    ax.set_xlabel("Predicted", color=INK_SECONDARY)
    ax.set_ylabel("Actual", color=INK_SECONDARY)
    ax.set_title(f"{result.name}: unseen merchants (share of each actual category)", loc="left", fontsize=11,
                 color=INK, fontweight="bold")
    for side in ax.spines.values():
        side.set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def run_categorization(out: Path, *, seeds=(1, 2, 3), seen_seeds=(1,), save_model_to: Path | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    unseen_runs, seen_runs, sizes = [], [], {}
    for seed in seeds:
        corpus = make_corpus(seed)
        sizes[seed] = len(corpus)
        texts, labels, groups = [c.text for c in corpus], [c.category for c in corpus], [c.merchant for c in corpus]
        unseen_runs.append(cat.evaluate(cat.MODEL_NAMES, texts, labels, groups, split="unseen", seed=seed))
        if seed in seen_seeds:
            seen_runs.append(cat.evaluate(cat.MODEL_NAMES, texts, labels, groups, split="seen", seed=seed))
    unseen, seen = _merge(unseen_runs), _merge(seen_runs)

    chosen = select(unseen)
    beats_rules = unseen[chosen].mean("macro_f1") > unseen["rules"].mean("macro_f1") + unseen[chosen].std("macro_f1")
    results = {
        "experiment": "E1 transaction categorisation (synthetic)",
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "corpus_seeds": list(seeds),
        "corpus_rows": sizes,
        "preregistered": {k: list(v) if isinstance(v, tuple) else v for k, v in cat.PREREGISTERED.items()},
        "selection_rule": SELECTION_RULE,
        "unseen_merchants": {n: _row(r) for n, r in unseen.items()},
        "seen_merchants": {n: _row(r) for n, r in seen.items()},
        "selected": chosen,
        "selected_beats_current_rules": bool(beats_rules),
    }
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    _confusion_png(unseen[chosen], out / f"confusion_{chosen}.png")

    if save_model_to is not None and beats_rules:
        texts, labels = [], []
        for seed in seeds:
            for c in make_corpus(seed):
                texts.append(c.text)
                labels.append(c.category)
        model = cat.make_model(chosen).fit(np.asarray(texts, dtype=object), np.asarray(labels, dtype=object))
        card = cat.save_model(
            model, save_model_to, name=chosen, texts=texts, labels=labels,
            metrics={"unseen_merchants": results["unseen_merchants"][chosen]},
            training_data=f"synthetic corpus seeds {list(seeds)} (moneyos.ml.corpus); no real transactions",
        )
        results["saved_model_card"] = str(card)
    _write_report(out / "report.md", results)
    return results


def _write_report(path: Path, r: dict) -> None:
    def table(section: str) -> list[str]:
        rows = ["| Model | Macro-F1 | Accuracy | Coverage* | Accuracy when shown* | Fit (s) |", "|---|---|---|---|---|---|"]
        for name, m in r[section].items():
            rows.append(
                f"| {name} | {m['macro_f1']['mean']:.3f} ± {m['macro_f1']['std']:.3f} | "
                f"{m['accuracy']['mean']:.3f} ± {m['accuracy']['std']:.3f} | {m['coverage']['mean']:.1%} | "
                f"{m['covered_accuracy']['mean']:.3f} | {m['fit_seconds']['mean']:.1f} |"
            )
        return rows

    lines = [
        f"# {r['experiment']}", "", f"Run {r['run_at']}. Corpus seeds {r['corpus_seeds']} "
        f"(rows: {r['corpus_rows']}). **Synthetic data only.**", "",
        "## Unseen merchants (grouped 5-fold; the realistic case)", "", *table("unseen_merchants"), "",
        "## Seen merchants (stratified 5-fold; optimistic)", "", *table("seen_merchants"), "",
        "\\* Coverage: share of predictions confident enough to show (probability ≥ "
        f"{r['preregistered']['confidence_threshold']}), or, for rules, share where a rule matched. "
        "Mean ± standard deviation over folds and seeds.", "",
        f"Selection rule: {r['selection_rule']}", "",
        f"**Selected: {r['selected']}.** Beats the app's current rules: {r['selected_beats_current_rules']}.", "",
        f"![Confusion matrix](confusion_{r['selected']}.png)",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------- forecasting

FORECAST_SELECTION_RULE = (
    "For each horizon, the method with the lowest MAE on the calibration period is chosen; test results are "
    "reported for every method, chosen or not."
)


def run_forecasting(out: Path, *, profile_seeds=tuple(range(1, 21)), days: int = 730) -> dict:
    from moneyos.ml import forecasting as fc
    from moneyos.ml.spending_sim import make_profile, simulate

    out.mkdir(parents=True, exist_ok=True)
    profiles = [simulate(make_profile(s), days=days) for s in profile_seeds]
    run = fc.run(profiles)
    scores = fc.evaluate(run["table"])
    results = {
        "experiment": "E2 spending forecasting, transactions only (synthetic)",
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "profiles": list(profile_seeds),
        "days_per_profile": days,
        "protocol": {"horizons": list(fc.HORIZONS), "first_origin": fc.FIRST_ORIGIN, "origin_step": fc.ORIGIN_STEP,
                     "calibration_start_day": fc.CAL_START, "test_start_day": fc.TEST_START,
                     "interval": list(fc.INTERVAL), "features": list(fc.FEATURES)},
        "selection_rule": FORECAST_SELECTION_RULE,
        "rows_per_period": {f"{h}/{p}": int(n) for (h, p), n in run["table"].groupby(["horizon", "period"]).size().items()},
        "statsmodels_convergence_warnings": run["convergence_warnings"],
        "seconds": round(run["seconds"], 1),
        "horizons": {str(h): r for h, r in scores.items()},
    }
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    run["table"].to_csv(out / "forecasts.csv", index=False)

    lines = [f"# {results['experiment']}", "",
             f"Run {results['run_at']}: {len(profile_seeds)} simulated profiles x {days} days. **Synthetic data only.**",
             "", f"Selection rule: {FORECAST_SELECTION_RULE}", ""]
    for h, r in scores.items():
        base = r["methods"][r["best_baseline_on_calibration"]]["test"]["mae"]
        lines += [f"## Next {h} days", "",
                  "| Method | Test MAE | Test RMSE | Test MAPE | MAE vs best baseline | 80% interval coverage | Calibration MAE |",
                  "|---|---|---|---|---|---|---|"]
        for m, s in sorted(r["methods"].items(), key=lambda kv: kv[1]["test"]["mae"]):
            t, c = s["test"], s["calibration"]
            lines.append(f"| {m} | {t['mae']:,.0f} | {t['rmse']:,.0f} | {t['mape']:.1%} | {t['mae'] / base - 1:+.1%} | "
                         f"{t['coverage']:.0%} | {c['mae']:,.0f} |")
        lines += ["", f"Best baseline (on calibration): **{r['best_baseline_on_calibration']}**. "
                      f"Chosen (on calibration): **{r['chosen_on_calibration']}**.", ""]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return results


# ------------------------------------------------------- anomaly detection

ANOMALY_SELECTION_RULE = (
    "Prefer the simplest, most explainable method (robust z-score < z-score < LOF < Isolation Forest) unless "
    "another method's F1 is higher with non-overlapping bootstrap 95% intervals."
)
ANOMALY_SIMPLICITY = ("robust_z_score", "z_score", "lof", "isolation_forest")


def run_anomaly(out: Path, *, stream_seeds=tuple(range(1, 41))) -> dict:
    from moneyos.ml import anomaly

    out.mkdir(parents=True, exist_ok=True)
    scores = anomaly.evaluate_with_intervals(stream_seeds)
    chosen = ANOMALY_SIMPLICITY[0]
    for candidate in ANOMALY_SIMPLICITY[1:]:
        if scores[candidate]["f1_95ci"][0] > scores[chosen]["f1_95ci"][1]:
            chosen = candidate
    results = {
        "experiment": "E3 unusual-spending detection (synthetic, injected anomalies)",
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "streams": len(stream_seeds),
        "protocol": {"days": 365, "train_days": 180, "min_history": anomaly.MIN_HISTORY,
                     "z_threshold": anomaly.Z_THRESHOLD, "model_contamination": 0.01},
        "selection_rule": ANOMALY_SELECTION_RULE,
        "methods": scores,
        "chosen": chosen,
    }
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    lines = [f"# {results['experiment']}", "", f"Run {results['run_at']}: {len(stream_seeds)} simulated people, "
             "evaluated on days 180-364. **Synthetic data with injected anomalies.**", "",
             "| Method | Precision | Recall | F1 (95% CI) | False alarms / month | Large-but-normal flagged | Spikes found | New categories found |",
             "|---|---|---|---|---|---|---|---|"]
    for m, s in scores.items():
        kinds = s["recall_by_kind"]
        lines.append(f"| {m} | {s['precision']:.3f} | {s['recall']:.3f} | {s['f1']:.3f} ({s['f1_95ci'][0]:.3f}-{s['f1_95ci'][1]:.3f}) | "
                     f"{s['false_alarms_per_month']:.2f} | {s['decoys_flagged']} | {kinds.get('amount_spike', '-')} | "
                     f"{kinds.get('unusual_category', '-')} |")
    lines += ["", f"Selection rule: {ANOMALY_SELECTION_RULE}", "", f"**Chosen: {chosen}.**"]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return results


# --------------------------------------------------------------- clustering


def run_clustering(out: Path) -> dict:
    from moneyos.ml import clustering

    out.mkdir(parents=True, exist_ok=True)
    scores = clustering.evaluate()
    results = {
        "experiment": "E4 spending-behaviour clustering (synthetic research check)",
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "features": list(clustering.FEATURES),
        **scores,
    }
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    a, c = scores["archetypes"], scores["continuous"]
    lines = [
        f"# {results['experiment']}", "", f"Run {results['run_at']}. 5 seeds, 200 simulated people each. **Synthetic.**", "",
        "| Method | Recovers 4 real types (ARI, mean / min) | k picked by silhouette | Best silhouette: real types | Best silhouette: no types |",
        "|---|---|---|---|---|",
    ]
    for m in a:
        lines.append(f"| {m} | {a[m]['adjusted_rand_index_mean']:.3f} / {a[m]['adjusted_rand_index_min']:.3f} | "
                     f"{a[m]['k_chosen_by_silhouette']} | {a[m]['best_silhouette_mean']:.3f} | {c[m]['best_silhouette_mean']:.3f} |")
    lines += ["", "Clustering always returns groups. Only the silhouette shows whether they are real: report it, "
              "and never present clusters as labels for people."]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return results
