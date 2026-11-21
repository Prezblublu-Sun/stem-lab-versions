"""Inference of the POD + ridge field model. Copied verbatim into predictor packages: numpy and the standard library only.

Scalars are predicted exactly like the quadratic ridge ensemble. A field is predicted through its POD coefficients:
    field = mean + coefficients @ modes
Each ensemble member predicts the coefficients; the spread of the members, the out-of-bag error of the coefficients and
the part of the training fields the kept modes could not rebuild (floor) are added in quadrature for the interval.

A point is {"bone_id", "design": {...}, "conditions": {...}}. meta["features"] says how a point becomes numbers.
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
    rows = [{"values": {}, "lower": {}, "upper": {}} for _ in points]
    if meta["targets"]:
        each = np.einsum("np,bpt->bnt", x, weights["coef"])             # members x points x targets, on the fitted scale
        mean, spread = each.mean(axis=0), each.std(axis=0)
        width = meta["z"] * np.sqrt(spread ** 2 + weights["sigma"][None, :] ** 2)
        for n, row in enumerate(rows):
            for t, target in enumerate(meta["targets"]):
                log = meta["scale"].get(target) == "log10"
                middle, low, high = mean[n, t], mean[n, t] - width[n, t], mean[n, t] + width[n, t]
                row["values"][target] = float(10.0 ** middle if log else middle)
                row["lower"][target] = float(10.0 ** low if log else low)
                row["upper"][target] = float(10.0 ** high if log else high)
    for number, name in enumerate(meta.get("fields") or []):
        modes, centre, floor = weights[f"field{number}_modes"], weights[f"field{number}_mean"], weights[f"field{number}_floor"]
        each = np.einsum("np,bpk->bnk", x, weights[f"field{number}_coef"])          # members x points x modes
        cells = each @ modes                                                        # members x points x cells
        value = centre[None, :] + cells.mean(axis=0)
        noise = (weights[f"field{number}_sigma"] ** 2) @ (modes ** 2)               # out-of-bag error of the coefficients, per cell
        width = meta["z"] * np.sqrt(cells.std(axis=0) ** 2 + noise[None, :] + floor[None, :] ** 2)
        shape = tuple(meta["field_shapes"][name])
        for n, row in enumerate(rows):
            stacked = np.stack([value[n], value[n] - width[n], value[n] + width[n]]).reshape((3, *shape))
            row.setdefault("fields", {})[name] = stacked
    return rows
