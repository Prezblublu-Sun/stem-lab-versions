"""Inference of the nearest-neighbour model (a test stand-in). Copied verbatim into predictor packages: numpy only."""
import numpy as np


def raw(features: dict, points: list) -> np.ndarray:
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


def nearest(x: np.ndarray, known: np.ndarray, y: np.ndarray, k: int, skip_self: bool = False):
    """Inverse-distance weighted mean and spread of the k nearest known rows, for every row of x."""
    distance = np.sqrt(((x[:, None, :] - known[None, :, :]) ** 2).sum(axis=2))
    if skip_self:
        np.fill_diagonal(distance, np.inf)
    order = np.argsort(distance, axis=1, kind="stable")[:, :k]
    near = np.take_along_axis(distance, order, axis=1)
    weight = 1.0 / (near + 1e-9)
    weight /= weight.sum(axis=1, keepdims=True)
    values = y[order]                                                   # rows x k x targets
    mean = (weight[:, :, None] * values).sum(axis=1)
    spread = np.sqrt((weight[:, :, None] * (values - mean[:, None, :]) ** 2).sum(axis=1))
    return mean, spread


def predict(weights: dict, meta: dict, points: list) -> list:
    mean, spread = nearest(raw(meta["features"], points), weights["x"], weights["y"], meta["k"])
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
