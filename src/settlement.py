"""V8.17 Settlement Monte Carlo — quasi-MC over AI-generated scenarios.

Approach
────────
A real Monte Carlo would need a labelled dataset of comparable case
outcomes with money values. We don't have that. What we *can* do is
honestly:

1. Have the model — given the case facts, jurisdiction, and a small
   curated retrieval of comparable precedents — produce a *mixture of
   triangular distributions* over plausible settlement / judgment
   amounts. Each scenario carries a probability weight.

2. Sample 10,000 outcomes from that mixture (no numpy — stdlib only).

3. Compute percentiles + EV + std and compare to the current offer.
   Suggest counter / walk-away at percentile-anchored values that the
   lawyer can override.

The simulator is *local and deterministic* given a seed — only the
scenario elicitation uses the LLM. This keeps the heavy reasoning where
it belongs (synthesizing precedents into a forecast) and keeps the
quantitative part auditable + reproducible.
"""
from __future__ import annotations

import json
import random
import re
import statistics
from dataclasses import dataclass

SCENARIO_SCHEMA_HINT = """
Kthe vetëm JSON, pa preambël. Skema:
{
  "currency": "EUR",
  "scenarios": [
    {
      "name": "settle_normal" | "settle_high" | "trial_win" | "trial_loss" | "dismissed" | "withdraw" | "tjetër",
      "label": "Përshkrim i shkurtër (≤ 8 fjalë)",
      "probability": 0.0–1.0,
      "min_value_eur":  0,
      "mode_value_eur": 0,
      "max_value_eur":  0,
      "rationale": "1-2 fjali pse kjo shkallë vlerash"
    }
  ],
  "key_drivers": ["faktorë kyç (≤ 5 bullet)"],
  "key_risks":   ["rreziqe kryesore (≤ 5 bullet)"],
  "comparable_anchor": "1 fjali për cilët precedentë i janë afër"
}
Probabilitetet duhet të mblidhen ≈ 1.0 (toleruar 0.95–1.05).
3-5 skenarë janë optimal. Min ≤ mode ≤ max në secilin skenar.
""".strip()


@dataclass
class Scenario:
    name: str
    label: str
    probability: float
    min_eur: float
    mode_eur: float
    max_eur: float
    rationale: str = ""


def _coerce_scenarios(payload: dict) -> tuple[list[Scenario], dict]:
    """Validate + normalise an AI-elicited scenario block.

    Returns (scenarios, meta_dict). Raises ValueError on unrecoverable
    malformation. Probabilities are renormalised to sum to 1.0 if their
    sum sits in [0.85, 1.15]; outside that window we refuse.
    """
    scen_raw = payload.get("scenarios") or []
    if not isinstance(scen_raw, list) or not scen_raw:
        raise ValueError("scenarios_missing")
    out: list[Scenario] = []
    for s in scen_raw:
        try:
            sc = Scenario(
                name=str(s.get("name") or "tjetër"),
                label=str(s.get("label") or s.get("name") or ""),
                probability=float(s.get("probability") or 0),
                min_eur=float(s.get("min_value_eur") or 0),
                mode_eur=float(s.get("mode_value_eur") or 0),
                max_eur=float(s.get("max_value_eur") or 0),
                rationale=str(s.get("rationale") or ""),
            )
        except (TypeError, ValueError) as e:
            raise ValueError(f"scenario_field_invalid:{e}") from e
        if sc.probability < 0:
            raise ValueError("probability_negative")
        if not (sc.min_eur <= sc.mode_eur <= sc.max_eur):
            # tolerant: clamp mode into [min, max]
            sc.mode_eur = max(sc.min_eur, min(sc.mode_eur, sc.max_eur))
        out.append(sc)
    total = sum(s.probability for s in out)
    if total <= 0:
        raise ValueError("probability_sum_zero")
    if not (0.85 <= total <= 1.15):
        raise ValueError(f"probability_sum_out_of_range:{round(total, 3)}")
    for s in out:
        s.probability /= total
    return out, {
        "currency": str(payload.get("currency") or "EUR"),
        "key_drivers": payload.get("key_drivers") or [],
        "key_risks": payload.get("key_risks") or [],
        "comparable_anchor": payload.get("comparable_anchor") or "",
    }


def parse_scenarios_text(text: str) -> tuple[list[Scenario], dict]:
    """Extract the JSON object from a possibly-noisy LLM output."""
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("no_json_object")
    try:
        payload = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"bad_json:{e}") from e
    return _coerce_scenarios(payload)


def simulate(scenarios: list[Scenario], *,
             samples: int = 10000,
             seed: int | None = None) -> dict:
    """Monte Carlo over a mixture of triangular distributions.

    Returns: {
      "samples": int,
      "mean_eur": float, "std_eur": float,
      "p10_eur": float, "p25_eur": float, "p50_eur": float,
      "p75_eur": float, "p90_eur": float,
      "min_eur": float, "max_eur": float,
      "scenario_hits": {name: count},
    }
    """
    if not scenarios:
        raise ValueError("no_scenarios")
    rng = random.Random(seed)
    weights = [s.probability for s in scenarios]
    population = list(range(len(scenarios)))
    out: list[float] = []
    hits: dict[str, int] = {}
    for _ in range(samples):
        idx = rng.choices(population, weights=weights, k=1)[0]
        sc = scenarios[idx]
        # triangular distribution. random.triangular(low, high, mode)
        # If min == max, falls back to constant.
        if sc.min_eur == sc.max_eur:
            v = sc.min_eur
        else:
            v = rng.triangular(sc.min_eur, sc.max_eur, sc.mode_eur)
        out.append(v)
        hits[sc.name] = hits.get(sc.name, 0) + 1
    out_sorted = sorted(out)

    def _pct(p: float) -> float:
        i = max(0, min(samples - 1, int(p * samples) - 1))
        return out_sorted[i]

    return {
        "samples": samples,
        "mean_eur": round(statistics.mean(out), 2),
        "std_eur":  round(statistics.pstdev(out), 2),
        "p10_eur":  round(_pct(0.10), 2),
        "p25_eur":  round(_pct(0.25), 2),
        "p50_eur":  round(_pct(0.50), 2),
        "p75_eur":  round(_pct(0.75), 2),
        "p90_eur":  round(_pct(0.90), 2),
        "min_eur":  round(out_sorted[0], 2),
        "max_eur":  round(out_sorted[-1], 2),
        "scenario_hits": hits,
    }


def percentile_of(value_eur: float, scenarios: list[Scenario], *,
                  samples: int = 10000, seed: int | None = None) -> float:
    """What percentile (0.0-1.0) of the simulated distribution sits ≤ value."""
    rng = random.Random(seed)
    weights = [s.probability for s in scenarios]
    pop = list(range(len(scenarios)))
    below = 0
    for _ in range(samples):
        idx = rng.choices(pop, weights=weights, k=1)[0]
        sc = scenarios[idx]
        v = (sc.min_eur if sc.min_eur == sc.max_eur
             else rng.triangular(sc.min_eur, sc.max_eur, sc.mode_eur))
        if v <= value_eur:
            below += 1
    return round(below / samples, 3)


def recommendation(distribution: dict, *,
                   current_offer_eur: float | None,
                   plaintiff: bool = True) -> dict:
    """Translate distribution + current offer into actionable advice.

    `plaintiff=True` means we are the *receiving* side (we want HIGHER
    values). `plaintiff=False` means we're the defendant — we want
    LOWER values.

    Output: {
      "verdict": "accept"|"counter"|"reject"|"no_offer",
      "current_offer_percentile": float|None,
      "suggested_counter_eur": float,
      "walk_away_eur": float,
      "expected_value_eur": float,
      "delta_vs_ev_eur": float|None,
      "summary": "..."
    }
    """
    ev = distribution["mean_eur"]
    if plaintiff:
        suggested_counter = distribution["p65_eur"] if "p65_eur" in distribution else (
            (distribution["p50_eur"] + distribution["p75_eur"]) / 2
        )
        walk_away = distribution["p25_eur"]
    else:
        suggested_counter = (
            distribution["p50_eur"] + distribution["p25_eur"]
        ) / 2
        walk_away = distribution["p75_eur"]

    if current_offer_eur is None:
        return {
            "verdict": "no_offer",
            "current_offer_percentile": None,
            "suggested_counter_eur": round(suggested_counter, 2),
            "walk_away_eur": round(walk_away, 2),
            "expected_value_eur": ev,
            "delta_vs_ev_eur": None,
            "summary": (f"EV ≈ {ev:.0f} EUR. Pa ofertë konkrete, target i "
                        f"sugjeruar {suggested_counter:.0f} EUR, "
                        f"walk-away {walk_away:.0f} EUR."),
        }

    # estimate offer's percentile by interpolating from p10..p90
    bins = [(0.10, distribution["p10_eur"]), (0.25, distribution["p25_eur"]),
            (0.50, distribution["p50_eur"]), (0.75, distribution["p75_eur"]),
            (0.90, distribution["p90_eur"])]
    pct = None
    for i in range(len(bins) - 1):
        p1, v1 = bins[i]
        p2, v2 = bins[i + 1]
        if v1 <= current_offer_eur <= v2 and v2 > v1:
            pct = p1 + (p2 - p1) * ((current_offer_eur - v1) / (v2 - v1))
            break
    if pct is None:
        if current_offer_eur < bins[0][1]: pct = 0.05
        elif current_offer_eur > bins[-1][1]: pct = 0.95
        else: pct = 0.50

    delta = current_offer_eur - ev
    if plaintiff:
        if pct >= 0.65: verdict = "accept"
        elif pct >= 0.40: verdict = "counter"
        else: verdict = "reject"
    else:
        if pct <= 0.35: verdict = "accept"
        elif pct <= 0.60: verdict = "counter"
        else: verdict = "reject"

    summary = (
        f"Oferta {current_offer_eur:.0f} EUR është te percentile "
        f"~{pct*100:.0f}% të shpërndarjes. EV = {ev:.0f}, "
        f"target i sugjeruar = {suggested_counter:.0f}, "
        f"walk-away = {walk_away:.0f}. Verdikti: {verdict}."
    )
    return {
        "verdict": verdict,
        "current_offer_percentile": round(pct, 3),
        "suggested_counter_eur": round(suggested_counter, 2),
        "walk_away_eur": round(walk_away, 2),
        "expected_value_eur": ev,
        "delta_vs_ev_eur": round(delta, 2),
        "summary": summary,
    }
