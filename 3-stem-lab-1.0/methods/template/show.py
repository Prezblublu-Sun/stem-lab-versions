"""空模板的结果展示：读算出来的结果，画成图，把图交回给 run.py。

约定只有一条：draw(run) 把图存进实验目录（一般是 out/ 下面），返回 [{"title": 标题, "path": 相对实验目录的位置}]；
run.py 把这份清单写进 result.json 的 "figures"，页面就把图摆在判定后面。也可以单独跑：python show.py <实验目录>。

画图用什么都行：
  - 下面的 svg_chart 只用标准库，画折线、散点、参考线，在哪台机器上都出得来；
  - 这台机器装了 matplotlib 的话，也可以存 PNG：
        import matplotlib
        matplotlib.use("Agg")                 # 不开窗口
        import matplotlib.pyplot as plt
        plt.plot(xs, ys)
        plt.savefig(os.path.join(run, "out", "y.png"), dpi=120)
        return [{"title": "…", "path": "out/y.png"}]
"""
import csv
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
    whole = all(float(x).is_integer() for x in xs) and x1 - x0 <= 30   # 横轴是序号、层号这类整数时，刻度也用整数
    xticks = (range(int(x0), int(x1) + 1, max(1, round((x1 - x0) / 10))) if whole
              else [x0 + (x1 - x0) * i / 5 for i in range(6)])
    for gx in xticks:   # 刻度和网格
        out.append(f'<line x1="{px(gx):.1f}" y1="{T}" x2="{px(gx):.1f}" y2="{H - B}" stroke="#eee"/>'
                   f'<text x="{px(gx):.1f}" y="{H - B + 16}" text-anchor="middle">{gx:.4g}</text>')
    for gy in [y0 + (y1 - y0) * i / 5 for i in range(6)]:
        out.append(f'<line x1="{L}" y1="{py(gy):.1f}" x2="{W - R}" y2="{py(gy):.1f}" stroke="#eee"/>'
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
    out.append(f'<rect x="{W - R - 176}" y="{T + 3}" width="174" height="{len(legend) * 16 + 6}" '
               f'fill="white" fill-opacity="0.85"/>')   # 图例底下垫一块白，免得压在线上看不清
    for i, (name, c, style) in enumerate(legend):   # 图例：右上角，一行一个
        y, x = T + 16 + i * 16, W - R - 170
        dash = ' stroke-dasharray="4 3"' if style == "虚线" else ""
        out.append(f'<circle cx="{x + 8}" cy="{y - 4}" r="4" fill="{c}"/>' if style == "点" else
                   f'<line x1="{x}" y1="{y - 4}" x2="{x + 16}" y2="{y - 4}" stroke="{c}" stroke-width="2"{dash}/>')
        out.append(f'<text x="{x + 22}" y="{y}">{esc(name)}</text>')
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out + ["</svg>"]))


def draw(run):
    """把 run.py 写的表画成一条线。"""
    with open(os.path.join(run, "out", "table.csv"), encoding="utf-8", newline="") as f:
        pts = [(float(r["x"]), float(r["y"])) for r in csv.DictReader(f)]
    svg_chart(os.path.join(run, "out", "table.svg"), "空模板画的一条线", "x", "y", [("y", pts, "线点")])
    return [{"title": "空模板画的一条线", "path": "out/table.svg"}]


if __name__ == "__main__":
    print(draw(sys.argv[1]))
