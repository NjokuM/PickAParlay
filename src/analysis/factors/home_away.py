"""
Factor 3: Home/Away (12%)
Performance split matched to tonight's game location.
Only uses games from the same location type.
"""
from __future__ import annotations

import pandas as pd

import config
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
from src.models import FactorResult
from src.analysis.context_filter import compute_confidence, effective_sample_size


def compute(
    df: pd.DataFrame,
    stat_col: str,
    line: float,
    tonight_is_home: bool,
    side: str = "over",
) -> FactorResult:
    weight = config.FACTOR_WEIGHTS["home_away"]
    location_label = "Home" if tonight_is_home else "Away"

    if df.empty or stat_col not in df.columns or "MATCHUP" not in df.columns:
        return FactorResult(
            name=f"{location_label} Performance",
            score=50.0,
            weight=weight,
            evidence=["No location data available."],
            data={},
            confidence=0.0,
        )

    # Filter to matching location
    if tonight_is_home:
        location_mask = df["MATCHUP"].str.contains(r"\bvs\.", case=False, na=False)
    else:
        location_mask = df["MATCHUP"].str.contains(r"\s@\s", case=False, na=False)

    filtered = df[location_mask].copy()

    # Also apply CTX_WEIGHT filter
    if "CTX_WEIGHT" in filtered.columns:
        filtered = filtered[filtered["CTX_WEIGHT"] > 0]

    if filtered.empty or stat_col not in filtered.columns:
        return FactorResult(
            name=f"{location_label} Performance",
            score=50.0,
            weight=weight,
            evidence=[f"No {location_label.lower()} game data available."],
            data={},
            confidence=0.0,
        )

    values = filtered[stat_col].tolist()
    hits = [v < line for v in values] if side == "under" else [v > line for v in values]
    hit_rate = sum(hits) / len(hits)
    avg_val = sum(values) / len(values)

    if side == "under":
        avg_diff = max(0.0, (line - avg_val) / line) if line > 0 else 0.0
    else:
        avg_diff = max(0.0, (avg_val - line) / line) if line > 0 else 0.0
    avg_score = min(1.0, 0.5 + avg_diff)
    score = round((0.6 * hit_rate + 0.4 * avg_score) * 100, 1)

    eff_sample = effective_sample_size(filtered)
    confidence = compute_confidence(eff_sample, config.MIN_SAMPLE["home_away"])

    vals_str = ", ".join(str(round(v, 1)) for v in values[:10])
    hit_count = sum(hits)
    direction_verb = "stayed below" if side == "under" else "hit"
    evidence = [
        f"{location_label} games this season: {hit_count}/{len(values)} {direction_verb} (line: {line})",
        f"{location_label} avg: {avg_val:.1f}",
        f"Values: {vals_str}",
    ]
    if confidence < 1.0:
        evidence.append(
            f"Low confidence — {eff_sample:.1f} {location_label.lower()} games (need {config.MIN_SAMPLE['home_away']})"
        )

    return FactorResult(
        name=f"{location_label} Performance",
        score=score,
        weight=weight,
        evidence=evidence,
        data={
            "values": values,
            "avg": avg_val,
            "hit_rate": hit_rate,
            "location": location_label,
        },
        confidence=confidence,
    )
