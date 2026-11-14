"""Inference of the quadratic ridge ensemble. Copied verbatim into predictor packages: numpy and the standard library only.

A point is {"bone_id", "design": {...}, "conditions": {...}}. meta["features"] says how a point becomes numbers:
numeric items are standardised, the others and the bone are one-hot coded (the first value seen is the baseline).
"""
import numpy as np


def raw(features: dict, points: list) -> np.ndarray:
    """One row per point: standardised numeric items, then the one-hot columns."""
    columns = []
    for item in features["numeric"]:
        values = np.array([float(point[item["group"]][item["name"]]) for point in points])
        columns.append((values - item["mean"]) / item["std"])
    for item in features["categorical"]:
        for value in item["values"][1:]:
            columns.append(np.array([1.0 if point[item["group"]][item["name"]] == value else 0.0 for point in points]))
    for bone in features["bones"][1:]:
        columns.append(np.array([1.0 if point["bone_id"] == bone else 0.0 for point in points]))
    return np.column_stack(columns) if columns else np.zeros((len(points), 0))


def expand(z: np.ndarray, degree: int) -> np.ndarray:
    """1, z, and for degree 2 every product z_i * z_j with i <= j."""
    parts = [np.ones((len(z), 1)), z]
    if degree >= 2 and z.shape[1]:
        first, second = np.triu_indices(z.shape[1])
        parts.append(z[:, first] * z[:, second])
    return np.hstack(parts)


def predict(weights: dict, meta: dict, points: list) -> list:
    x = expand(raw(meta["features"], points), meta["degree"])
    each = np.einsum("np,bpt->bnt", x, weights["coef"])                 # members x points x targets, on the fitted scale
    mean, spread = each.mean(axis=0), each.std(axis=0)
    width = meta["z"] * np.sqrt(spread ** 2 + weights["sigma"][None, :] ** 2)
    rows = []
    for n in range(len(points)):
        row = {"values": {}, "lower": {}, "upper": {}}
        for t, target in enumerate(meta["targets"]):
            log = meta["scale"].get(target) == "log10"
            middle, low, high = mean[n, t], mean[n, t] - width[n, t], mean[n, t] + width[n, t]
            row["values"][target] = float(10.0 ** middle if log else middle)
            row["lower"][target] = float(10.0 ** low if log else low)
            row["upper"][target] = float(10.0 ** high if log else high)
        rows.append(row)
    return rows
