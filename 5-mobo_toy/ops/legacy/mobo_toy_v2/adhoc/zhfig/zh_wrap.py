"""Re-run an existing English figure script and save Chinese versions of its figures.

    python zh_wrap.py OUTDIR script.py [--call FUNC] [-- script args]

The script runs unchanged; Figure.savefig is patched so that, just before saving, every text in the figure (titles, axis
labels, tick labels, legends, annotations) is translated with zh_dict.json and drawn in a CJK font, and the file is written
to OUTDIR/<same file name> instead of the original path. Data and layout are the original script's.
Collect mode (ZH_COLLECT=strings.json): nothing is saved; all English strings are appended to the JSON file.
Fonts: Microsoft YaHei on Windows; on Linux set ZH_FONT=/path/to/font file (registered with matplotlib).
"""
import json
import os
import re
import runpy
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.text import Text  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
OUTDIR = os.path.abspath(args.pop(0))
script = os.path.abspath(args.pop(0))
call = None
if args and args[0] == "--call":
    call = args[1]
    args = args[2:]
if args and args[0] == "--":
    args = args[1:]
COLLECT = os.environ.get("ZH_COLLECT")
D = json.load(open(os.environ.get("ZH_DICT", os.path.join(HERE, "zh_dict.json")), encoding="utf-8")) if not COLLECT else {}
EXACT, PARTIAL = D.get("exact", {}), D.get("partial", [])
FONT = "Microsoft YaHei"
if os.environ.get("ZH_FONT"):                     # one or more font files, comma-separated (regular, bold)
    fonts = os.environ["ZH_FONT"].split(",")
    for f_ in fonts:
        font_manager.fontManager.addfont(f_)
    FONT = font_manager.FontProperties(fname=fonts[0]).get_name()
WORD = re.compile(r"[A-Za-z]{2,}")
missing = set()


def translate(s):
    k = s.strip()
    if not k or not WORD.search(k):
        return s
    if k in EXACT:
        return EXACT[k]
    out = k
    for a, b in PARTIAL:
        out = out.replace(a, b)
    if WORD.search(re.sub(r"(µm|MPa|mm|cm|N·m|SED|vM|P\d\d|GP|ARD|BO|HV|FE|FI|ISO|Sobol|CalculiX|Abaqus|PLA|LVDT|DIC|"
                          r"[A-Z]\d|wrap_fit|neck\d\w*|[A-Z]{1,3}\b|\b[a-z]_?\w{0,3}\b)", "", out)):
        missing.add(k)
    return out


strings = []
_orig = Figure.savefig


def savefig(self, fname, *a, **kw):
    texts = [t for t in self.findobj(Text) if t.get_text()]
    if COLLECT:
        strings.extend(t.get_text() for t in texts if WORD.search(t.get_text()))
        return None
    # tick labels are regenerated from the axis formatter at draw time: draw once, then replace word labels via the axis
    self.canvas.draw()
    for ax in self.axes:
        for axis in (ax.xaxis, ax.yaxis):
            labs = [t.get_text() for t in axis.get_majorticklabels()]
            if any(WORD.search(l) and not l.startswith("$") for l in labs):
                axis.set_ticks(axis.get_majorticklocs())
                axis.set_ticklabels([translate(l) for l in labs])
            for t in axis.get_majorticklabels() + axis.get_minorticklabels():
                t.set_fontfamily([FONT, "DejaVu Sans"])
            axis.set_tick_params(which="both", labelfontfamily=FONT)
    texts = [t for t in self.findobj(Text) if t.get_text()]
    for t in texts:
        t.set_text(translate(t.get_text()))
        t.set_fontfamily([FONT, "DejaVu Sans"])
    name = os.path.basename(str(fname))
    os.makedirs(OUTDIR, exist_ok=True)
    return _orig(self, os.path.join(OUTDIR, name), *a, **kw)


Figure.savefig = savefig
plt.savefig = lambda fname, *a, **kw: plt.gcf().savefig(fname, *a, **kw)
plt.rcParams["axes.unicode_minus"] = False
sys.argv = [script] + args
sys.path.insert(0, os.path.dirname(script))
os.chdir(os.path.dirname(script))
if call:
    g = runpy.run_path(script, run_name="zh_wrap_module")
    g[call]()
else:
    runpy.run_path(script, run_name="__main__")
if COLLECT:
    old = json.load(open(COLLECT, encoding="utf-8")) if os.path.exists(COLLECT) else []
    json.dump(sorted(set(old) | set(strings)), open(COLLECT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print("collected", len(set(strings)), "->", COLLECT)
elif missing:
    print("UNTRANSLATED:", json.dumps(sorted(missing), ensure_ascii=False))
