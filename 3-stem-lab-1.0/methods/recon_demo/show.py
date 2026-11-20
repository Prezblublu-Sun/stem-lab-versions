"""重建示例的结果展示：读各层的皮质厚度，画成图。示例，不是科学。

run.py 算完会调这里的 draw()；也可以单独跑：python show.py <实验目录>，照已有的结果重画。
图用纯标准库写成 SVG，不依赖任何包。
"""
import csv
import json
import os
import sys
from html import escape as esc


def svg_chart(path, title, xlabel, ylabel, series, hlines=()):
    """画一张图，存成 SVG。series：[(图例, [(x, y), ...], 样式)]，样式是 "线"、"点"、"线点" 或 "虚线"；
    hlines：[(y, 图例)] 水平参考线（比如门槛）。"""
    W, H, L, R, T, B = 640, 400, 70, 20, 40, 56          # 宽、高、左右上下留白
    xs = [x for _, pts, _ in series for x, _ in pts]
    ys = [y for _, pts, _ in series for _, y in pts] + [y for y, _ in hlines]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    x0, x1 = (x0 - 1, x1 + 1) if x0 == x1 else (x0, x1)
    pad = (y1 - y0) * 0.08 or 1
    y0, y1 = y0 - pad, y1 + pad
    px = lambda x: L + (x - x0) / (x1 - x0) * (W - L - R)
    py = lambda y: H - B - (y - y0) / (y1 - y0) * (H - T - B)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           f'font-family="Microsoft YaHei, sans-serif" font-size="12">', f'<rect width="{W}" height="{H}" fill="white"/>',
           f'<text x="{W / 2}" y="24" text-anchor="middle" font-size="15">{esc(title)}</text>']
    for i in range(6):   # 刻度和网格
        gx, gy = x0 + (x1 - x0) * i / 5, y0 + (y1 - y0) * i / 5
        out.append(f'<line x1="{px(gx):.1f}" y1="{T}" x2="{px(gx):.1f}" y2="{H - B}" stroke="#eee"/>'
                   f'<text x="{px(gx):.1f}" y="{H - B + 16}" text-anchor="middle">{gx:.4g}</text>'
                   f'<line x1="{L}" y1="{py(gy):.1f}" x2="{W - R}" y2="{py(gy):.1f}" stroke="#eee"/>'
                   f'<text x="{L - 6}" y="{py(gy) + 4:.1f}" text-anchor="end">{gy:.4g}</text>')
    out += [f'<rect x="{L}" y="{T}" width="{W - L - R}" height="{H - T - B}" fill="none" stroke="#999"/>',
            f'<text x="{(L + W - R) / 2}" y="{H - 14}" text-anchor="middle">{esc(xlabel)}</text>',
            f'<text x="16" y="{(T + H - B) / 2}" text-anchor="middle" '
            f'transform="rotate(-90 16 {(T + H - B) / 2})">{esc(ylabel)}</text>']
    colors, legend = ["#2367c7", "#d1495b", "#3b8b4b", "#8a5cc2"], []
    for i, (name, pts, style) in enumerate(series):
        c = colors[i % len(colors)]
        if "线" in style:
            dash = ' stroke-dasharray="6 4"' if style == "虚线" else ""
            out.append(f'<polyline fill="none" stroke="{c}" stroke-width="2"{dash} points="'
                       + " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in pts) + '"/>')
        if "点" in style:
            out += [f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="4" fill="{c}"/>' for x, y in pts]
        legend.append((name, c, style))
    for y, name in hlines:
        out.append(f'<line x1="{L}" y1="{py(y):.1f}" x2="{W - R}" y2="{py(y):.1f}" stroke="#b9770e" '
                   f'stroke-width="1.5" stroke-dasharray="6 4"/>')
        legend.append((name, "#b9770e", "虚线"))
    for i, (name, c, style) in enumerate(legend):   # 图例：右上角，一行一个
        y, x = T + 16 + i * 16, W - R - 170
        dash = ' stroke-dasharray="4 3"' if style == "虚线" else ""
        out.append(f'<circle cx="{x + 8}" cy="{y - 4}" r="4" fill="{c}"/>' if style == "点" else
                   f'<line x1="{x}" y1="{y - 4}" x2="{x + 16}" y2="{y - 4}" stroke="{c}" stroke-width="2"{dash}/>')
        out.append(f'<text x="{x + 22}" y="{y}">{esc(name)}</text>')
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out + ["</svg>"]))


def draw(run):
    """画各层的皮质厚度，和平均值那条线。返回交给平台的图的清单。"""
    with open(os.path.join(run, "task.json"), encoding="utf-8") as f:
        S = json.load(f)["settings"]
    with open(os.path.join(run, "out", "layers.csv"), encoding="utf-8", newline="") as f:
        pts = [(int(r["layer"]), float(r["thickness_mm"])) for r in csv.DictReader(f)]
    mean = sum(t for _, t in pts) / len(pts)
    svg_chart(os.path.join(run, "out", "layers.svg"),
              f"各层的皮质厚度（阈值 {S['threshold']:g} HU，平滑 {S['smooth']} 次）", "第几层", "皮质厚度 (mm)",
              [("各层", pts, "线点")], [(mean, f"平均 {mean:.3f} mm")])
    return [{"title": "各层的皮质厚度", "path": "out/layers.svg"}]


if __name__ == "__main__":
    print(draw(sys.argv[1]))
