"""页面：仪表盘、新建实验、实验和结果、登记的东西、核对。

这里只把现状拼成 HTML，不往账本里写东西（写的事都在 web.py）。
"""
import csv
import os
import time
from html import escape
from urllib.parse import quote

from . import fingerprint, ledger, runs, things
from .things import METHOD

CSS = """
body{font:15px/1.6 system-ui,"Microsoft YaHei",sans-serif;margin:0;color:#222;background:#f6f7f9}
nav{background:#2d3e50;padding:8px 16px}nav b{color:#fff;margin-right:24px}
nav a{color:#cfd8e3;margin-right:18px;text-decoration:none}nav a.here{color:#fff;border-bottom:2px solid #fff}
main{max-width:1150px;margin:0 auto;padding:8px 16px 60px}h1{font-size:22px}
h2{font-size:17px;margin-top:26px;border-bottom:1px solid #ddd;padding-bottom:2px}h3{font-size:15px;margin:14px 0 4px}
table{border-collapse:collapse;margin:6px 0;background:#fff}td,th{border:1px solid #ddd;padding:3px 8px;text-align:left;vertical-align:top}
th{background:#eef0f3;font-weight:normal;color:#555;white-space:nowrap}.nw{white-space:nowrap}.small{font-size:12px;color:#888}
.ok{color:#17803d;font-weight:bold}.bad{color:#c0392b;font-weight:bold}.mid{color:#b9770e;font-weight:bold}.run{color:#2367c7;font-weight:bold}
.box{background:#fff;border:1px solid #ddd;border-radius:6px;padding:8px 14px;margin:8px 0}
.err{background:#fdecea;border:1px solid #e6a5a0;padding:8px 12px;border-radius:6px;margin:8px 0}
.note{background:#eaf4ff;border:1px solid #b6d4f2;padding:8px 12px;border-radius:6px;margin:8px 0}
pre{background:#23272e;color:#e8e8e8;padding:8px;overflow:auto;max-height:320px;font-size:12px;white-space:pre-wrap}
.bar{display:inline-block;width:180px;height:10px;background:#dde;border-radius:5px;vertical-align:middle}
.bar i{display:block;height:100%;background:#2367c7;border-radius:5px}
figure{display:inline-block;margin:6px 12px 6px 0;background:#fff;border:1px solid #ddd;padding:6px}
figure img{max-width:100%}figcaption{font-size:13px;color:#555}
fieldset{border:1px solid #ccc;border-radius:6px;margin:10px 0;background:#fff}legend{font-weight:bold;padding:0 4px}
input,select,textarea,button{font:inherit}button{padding:3px 12px;cursor:pointer}button.go{font-size:16px;padding:6px 22px}
a.pick{display:inline-block;padding:5px 14px;margin:3px 6px 3px 0;border:1px solid #2367c7;border-radius:6px;text-decoration:none;background:#fff}
a.pick.on{background:#2367c7;color:#fff}form.inline{display:inline}
"""

# 带 data-live 的那一块，每 3 秒向服务端要一份新的；页面不在前台就不要。
# 实验页上，状态从“在跑”变了，就整页重新载入，好显示判定和产出。
JS = """
(function(){var b=document.querySelector('[data-live]');if(!b)return;
function pull(){if(document.visibilityState!=='visible')return;
fetch(b.dataset.live).then(function(r){return r.text()}).then(function(t){
var w=(t.match(/data-word="([^"]*)"/)||[])[1];
if(b.dataset.word&&w&&w!==b.dataset.word){location.reload();return}b.innerHTML=t}).catch(function(){})}
setInterval(pull,3000);document.addEventListener('visibilitychange',pull)})();
"""

CATEGORIES = ("重建", "FEA", "代理", "优化")   # 一页纸里的四类；做法写了别的类，也照样列出来
EMPTY = ('<div class="note">库里还是空的：到<a href="/things">登记的东西</a>点“把自带的模板和示例材料登记进来”，'
         '就有几个模板和示例材料可以试；也可以登记你自己的。</div>')
NAV = [("/", "仪表盘"), ("/new", "新建实验"), ("/exps", "实验和结果"), ("/things", "登记的东西"), ("/check", "核对")]
OPS = {"<=": "≤", ">=": "≥", "<": "<", ">": ">"}
WORD_CLASS = {"在跑": "run", "完成": "ok", "失败": "bad", "中断": "mid", "停了": "small", "没启动": "small",
              "合格": "ok", "不合格": "bad", "未设门槛": "mid", "一样": "ok", "不一样": "bad", "没有": "ok", "记着": "mid"}


def e(x):
    """把任何值变成能放进 HTML 的文字。"""
    return escape("" if x is None else str(x))


def page(title, body, here="", data=None):
    """拼一整页。给了 data，账本有对不上的地方就在顶上用红字说出来。"""
    nav = "".join(f'<a href="{u}"{" class=here" if u == here else ""}>{t}</a>' for u, t in NAV)
    warn = trouble_html(data) if data else ""
    return (f'<!doctype html><html lang="zh"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(title)} - stem-lab</title><style>{CSS}</style></head><body>'
            f'<nav><b>stem-lab</b>{nav}</nav><main>{warn}<h1>{e(title)}</h1>{body}</main>'
            f'<script>{JS}</script></body></html>')


def trouble_html(data):
    """账本现在有对不上的地方，就用红字说出来，带去核对页的链接。"""
    bad = ledger.trouble(data)
    return (f'<div class="err">账本有 {len(bad)} 处对不上：{e(bad[0][2])}。下面显示的记录不一定可信，'
            f'<a href="/check?go=1">去核对页看是哪几条</a>。</div>' if bad else "")


def what(entry):
    """账本里的一条是什么，用人话说。"""
    kind, n = entry.get("kind"), entry.get("exp") or entry.get("n") or 0
    if kind == "register":
        made_by = (entry.get("source") or {}).get("experiment")
        return f'{entry.get("type")}「{entry.get("name")}」的登记' + (f"（{eid(made_by)} 的产出）" if made_by else "")
    return {"seal": f'{eid(n)}「{entry.get("title")}」的封存记录', "start": f'{eid(n)} 的第 {entry.get("attempt")} 次启动',
            "end": f"{eid(n)} 的结束记录", "gap": "一条“账本出过问题”的记录"}.get(kind, f"一条“{kind}”记录")


def msgs(errors=(), notes=()):
    out = "".join(f'<div class="err">{e(x)}</div>' for x in errors)
    return out + "".join(f'<div class="note">{e(x)}</div>' for x in notes)


def word(w):
    return f'<span class="{WORD_CLASS.get(w, "")}">{e(w)}</span>'


def ago(sec):
    if sec is None:
        return "—"
    sec = int(sec)
    for size, unit in ((86400, "天"), (3600, "小时"), (60, "分钟")):
        if sec >= size:
            return f"{sec // size} {unit}"
    return f"{sec} 秒"


def fmt(v):
    """显示一个值：2300.0 显示成 2300，开关显示成 开/关。"""
    if isinstance(v, bool):
        return "开" if v else "关"
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    return "" if v is None else str(v)


def eid(n):
    return f"e{n:04d}"


def final(x):
    """实验最后一次结束且是“完成”时，返回那条结束记录；否则 None。"""
    ends = [ev for ev in x["events"] if ev["kind"] == "end"]
    return ends[-1] if ends and ends[-1]["status"] == "完成" and x["events"][-1]["kind"] == "end" else None


def origin(st, t, html=True):
    """一样东西的来历：外来的，还是哪个实验产出的（连同那个实验用的做法和判定）。"""
    n = (t.get("source") or {}).get("experiment")
    x = st.exps.get(n)
    if not x:   # 外来的：登记时写了说明，就带上说明的前一小段
        note = (t.get("note") or "").strip()
        text = "外来" + (f"（{note[:24]}{'…' if len(note) > 24 else ''}）" if note else "")
        return e(text) if html else text
    end, m = final(x), x["seal"]["method"]
    verdict = end["verdict"]["result"] if end else "还没判定"
    if not html:
        return f"{eid(n)}「{x['seal']['title']}」产出，{m['name']} 第{m['version']}版，{verdict}"
    return (f'<a href="/exp?id={n}">{eid(n)}「{e(x["seal"]["title"])}」</a>产出'
            f'（{e(m["name"])} 第{m["version"]}版；{word(verdict)}）')


def gate_text(gates, reports):
    """把门槛写成一句话，比如“最大应力 ≤ 120；平均微动 ≤ 50”。"""
    return "；".join(f'{reports.get(g["metric"], {}).get("name") or g["metric"]} {OPS[g["op"]]} {fmt(g["value"])}'
                    for g in gates) or "未设"


def same_before(st, x):
    """封存这个实验之前，已经用同一版做法、同样指纹的东西、同样的设置跑出过结果，门槛却不一样的实验。"""
    s = x["seal"]
    def key(t):
        return (t["method"]["fingerprint"], {k: r and r["fingerprint"] for k, r in t["inputs"].items()}, t["settings"])
    gates = lambda t: {g["metric"]: (g["op"], g["value"]) for g in t["gates"]}
    return [(y, final(y)) for y in st.exps.values() if y is not x and final(y) and final(y)["n"] < s["n"]
            and key(y["seal"]) == key(s) and gates(y["seal"]) != gates(s)]


def ver(t, sep=""):
    """外来的东西和做法：“第几版”；实验的产出不排版本，返回空。"""
    return "" if (t.get("source") or {}).get("experiment") else f'{sep}第{t["version"]}版'


def spec_of(data, t):
    try:
        return things.read_method(things.where(data, t))
    except things.Problem:
        return None


def bar(p):
    if not p:
        return '<span class="small">还没有报进度</span>'
    done, total = p.get("done"), p.get("total")
    pct = int(100 * done / total) if isinstance(done, (int, float)) and total else 0
    return (f'<span class="bar"><i style="width:{min(pct, 100)}%"></i></span> '
            f'{e(fmt(done))}/{e(fmt(total))} · {e(p.get("note", ""))}')


# ---------- 仪表盘 ----------

def dashboard(data):
    return page("仪表盘", f'<div data-live="/live">{dashboard_live(data)}</div>', "/")   # 红字在刷新的那一块里


def dashboard_live(data):
    """只读账本和每个实验的几个小文件，不起任何进程。"""
    st = ledger.state(data)
    rows = [(x, runs.status(data, x)) for x in reversed(list(st.exps.values()))]
    out = [trouble_html(data),
           f'<p class="small">每 3 秒自动更新，页面不在前台时不更新 · 更新于 {time.strftime("%H:%M:%S")}</p>',
           EMPTY if not st.things else "", "<h2>在跑</h2>"]
    running = [(x, i) for x, i in rows if i["word"] == "在跑"]
    if not running:
        out.append('<p>现在没有在跑的实验。<a href="/new">新建一个</a></p>')
    for x, i in running:
        n, s = x["seal"]["n"], x["seal"]
        p, quiet = runs.progress(data, n)
        again = f'（第 {i["attempts"]} 次启动）' if i["attempts"] > 1 else ""
        out.append(f'<div class="box"><a href="/exp?id={n}"><b>{e(s["title"])}</b></a> '
                   f'<span class="small">{eid(n)} · {e(s["category"])} · {e(s["method"]["name"])} '
                   f'第{s["method"]["version"]}版{again}</span><br>{bar(p)}<br>'
                   f'<span class="small">{ago(quiet)}前有动静</span></div>')
    out.append("<h2>哪里停了</h2>")
    stuck = [(x, i) for x, i in rows if i["word"] in ("中断", "失败", "停了", "没启动")][:10]
    if not stuck:
        out.append("<p>没有停下来、没跑完的实验。</p>")
    for x, i in stuck:
        n, s, end = x["seal"]["n"], x["seal"], i["end"] or {}
        p, quiet = runs.progress(data, n)
        why = {"中断": "看护进程不在了（机器重启、进程被杀……）", "没启动": "封存了，但没启动起来"}.get(
            i["word"], end.get("why", ""))
        code = f' · 退出码 {e(end["code"])}' if end.get("code") is not None else ""
        log = runs.tail(os.path.join(runs.run_dir(data, n), "log.txt"), 8)
        out.append(f'<div class="box"><a href="/exp?id={n}"><b>{e(s["title"])}</b></a> {word(i["word"])}'
                   f'<span class="small"> {eid(n)} · {e(why)}{code} · {ago(quiet)}前最后有动静</span><br>'
                   f'最后的进度：{bar(p)}<pre>{e(log) or "（日志是空的）"}</pre></div>')
    out.append("<h2>最近跑完的</h2>")
    done = [(x, i) for x, i in rows if i["word"] == "完成"][:8]
    if not done:
        out.append("<p>还没有跑完的实验。</p>")
    else:
        out.append("<table><tr><th>实验</th><th>判定</th><th>跑完的时间</th></tr>" + "".join(
            f'<tr><td><a href="/exp?id={x["seal"]["n"]}">{e(x["seal"]["title"])}</a> '
            f'<span class="small">{eid(x["seal"]["n"])}</span></td>'
            f'<td>{word(i["end"]["verdict"]["result"])}</td><td>{e(i["end"]["time"])}</td></tr>'
            for x, i in done) + "</table>")
    return "".join(out)


# ---------- 新建实验 ----------

def split_gate(text):
    """把 "<= 0.8" 这样的建议门槛拆成 ("<=", "0.8")。"""
    text = str(text or "").strip()
    for op in ("<=", ">=", "<", ">"):
        if text.startswith(op):
            return op, text[len(op):].strip()
    return "", ""


def default_and_range(s):
    """一个设置项的默认值和范围，比如“默认 2300 N · 范围 500 ~ 5000 N”。"""
    parts = [f'默认 {fmt(s["default"])} {s.get("unit", "")}'.strip()] if "default" in s else []
    if things.range_text(s):
        parts.append(("可选 " if s["kind"] == "选项" else "范围 ") + things.range_text(s))
    return " · ".join(parts)


def setting_input(s, raw):
    """一个设置项的输入框：开关是勾选框，选项是下拉框，数、整数、文字是文本框。"""
    attrs = f'name="set_{e(s["key"])}" aria-label="{e(s.get("name") or s["key"])}"'
    if s["kind"] == "开关":
        try:
            on = things.parse_value(s, raw)
        except things.Problem:
            on = False
        return f'<input type="checkbox" {attrs} value="1"{" checked" if on else ""}>'
    if s["kind"] == "选项":
        return f'<select {attrs}>' + "".join(
            f'<option{" selected" if str(c) == str(raw) else ""}>{e(c)}</option>'
            for c in s.get("choices", [])) + "</select>"
    size = 10 if s["kind"] in ("数", "整数") else 36
    return f'<input type="text" {attrs} value="{e(fmt(raw))}" size="{size}">'


def new_form(data, v, errors=(), notes=(), changed=()):
    """新建实验。v 是表单上现有的值；没给的项用默认（做法写的默认值、最新的一版、建议的门槛）。"""
    st = ledger.state(data)
    methods = [t for t in st.things.values() if t["type"] == METHOD]
    m = st.things.get(v.get("method"))
    m = m if m and m["type"] == METHOD else None
    cat = m["category"] if m else v.get("cat")
    out = [msgs(errors, notes), EMPTY if not methods else "", "<h2>第 1 步：选哪一类</h2>"]
    out.append("<p>" + "".join(
        f'<a class="pick{" on" if c == cat else ""}" href="/new?cat={quote(c)}">{e(c)}</a>'
        for c in dict.fromkeys(list(CATEGORIES) + [t["category"] for t in methods])) + "</p>")
    if not cat:
        return page("新建实验", "".join(out), "/new", data)
    out.append("<h2>第 2 步：选做法和要用的东西</h2>")
    groups = {}
    for t in methods:
        if t["category"] == cat:
            groups.setdefault(t["name"], []).append(t)
    if not groups:
        out.append(f'<p>「{e(cat)}」这一类还没有登记做法。到<a href="/things">登记的东西</a>里登记一个：类型写“做法”，'
                   f'路径指向一个带 method.toml 的文件夹（里面写 category = "{e(cat)}"）。</p>')
        return page("新建实验", "".join(out), "/new", data)
    if not m:
        for name, vs in groups.items():
            spec = spec_of(data, vs[-1]) or {}
            older = " ".join(f'<a href="/new?method={t["n"]}">第{t["version"]}版</a>' for t in reversed(vs[:-1]))
            out.append(f'<p><a class="pick" href="/new?method={vs[-1]["n"]}">{e(name)} · 第{vs[-1]["version"]}版'
                       f'</a> <span class="small">{"更早的：" + older if older else ""}</span><br>'
                       f'<span class="small">{e(spec.get("about", ""))}</span></p>')
        return page("新建实验", "".join(out), "/new", data)
    try:
        spec = things.read_method(things.where(data, m))
    except things.Problem as err:
        out.append(msgs([f"这个做法读不出来：{err}。换一个版本，或把 method.toml 改好再登记一版。"]))
        return page("新建实验", "".join(out), "/new", data)
    others = " ".join(f'<a href="/new?method={t["n"]}">第{t["version"]}版</a>'
                      for t in reversed(groups.get(m["name"], [])) if t["n"] != m["n"])
    out.append(f'<p>做法：<b>{e(m["name"])} · 第{m["version"]}版</b> <a href="/new?cat={quote(cat)}">换一个做法</a>'
               f' <span class="small">{"别的版本：" + others if others else ""}</span><br>'
               f'<span class="small">{e(spec.get("about", ""))}</span></p>')
    f = ['<form method="post" action="/new">', f'<input type="hidden" name="method" value="{m["n"]}">',
         f'<input type="hidden" name="from" value="{e(v.get("from") or "")}">']
    for key, t, why in changed:   # 对不上只有两种：外来东西的留底被人动过，或实验的产出跑完以后被人改过
        made_by = (t.get("source") or {}).get("experiment")
        button = f'<button name="action" value="rereg:{e(key)}">'
        fix = (f'这是 {eid(made_by)} 的产出，那个实验跑完以后被人改过。{button}把它现在的样子登记成一样外来的东西，'
               f'并选上它</button>' if made_by else f'它的留底被人动过。{button}照原处的文件恢复留底</button> '
               f'<span class="small">原处的文件也改过的话，会成为新的一版，并替你选上</span>')
        f.append(f'<div class="err">{e(t["type"])}{e(things.label(t))}和登记时不一样了：{e(why)}。{fix}</div>')
    rows = []
    for inp in spec.get("inputs", []):
        key, typ, label = inp["key"], inp["type"], inp.get("label") or inp["key"]
        opts = sorted((t for t in st.things.values() if t["type"] == typ), key=lambda t: -t["n"])
        if not opts:
            rows.append(f'<tr><td>{e(label)}</td><td>还没有登记过「{e(typ)}」。到<a href="/things">登记的东西</a>'
                        f'里登记一个，或者先跑一个产出「{e(typ)}」的实验。</td></tr>')
            continue
        chosen = v.get("inputs", {}).get(key)   # 没选过就停在“请选”，不替用户挑
        o = [f'<option value="">{"（不选）" if inp.get("optional") else "（请选）"}</option>']
        o += [f'<option value="{t["n"]}"{" selected" if t["n"] == chosen else ""}>{e(t["name"])}{ver(t, " · ")}'
              f' · {e(origin(st, t, html=False))}</option>' for t in opts]
        rows.append(f'<tr><td>{e(label)}<div class="small">{e(typ)}{"，可以不选" if inp.get("optional") else ""}'
                    f'</div></td><td><select name="in_{e(key)}" aria-label="{e(label)}">{"".join(o)}</select></td></tr>')
    f.append("<table>" + "".join(rows) + "</table>" if rows else "<p>这个做法不用选东西。</p>")

    f.append("<h2>第 3 步：填设置</h2>")
    opened = " open" if v.get("fill_json") or v.get("fill_path") else ""
    f.append(f'<details{opened}><summary>从一份外来的设置填表</summary><p class="small">贴一段 JSON，'
             f'比如 {{"load": 2500, "摩擦系数": 0.2}}（键或名字都认）；也可以写一个 JSON 或 TOML 文件的路径。'
             f'认不得的项会列出来，不会悄悄丢掉。</p><textarea name="fill_json" rows="4" cols="80">'
             f'{e(v.get("fill_json", ""))}</textarea><br>文件路径 <input name="fill_path" size="60" '
             f'value="{e(v.get("fill_path", ""))}"> <button name="action" value="fill">照它填表</button></details>')
    sgroups = {}
    for s in spec.get("settings", []):
        sgroups.setdefault(s.get("group") or "其他", []).append(s)
    for g, items in sgroups.items():
        f.append(f"<fieldset><legend>{e(g)}</legend><table>" + "".join(
            f'<tr><td>{e(s.get("name") or s["key"])}</td>'
            f'<td>{setting_input(s, v.get("settings", {}).get(s["key"], s.get("default", "")))}</td>'
            f'<td>{e(s.get("unit", ""))}</td><td class="small">{e(default_and_range(s))}</td>'
            f'<td class="small">{e(s.get("about", ""))}</td></tr>' for s in items) + "</table></fieldset>")
    if not sgroups:
        f.append("<p>这个做法没有设置项。</p>")

    f.append("<h2>写门槛（可以不写）</h2><p class='small'>门槛和实验一起封存，启动以后改不了、补不了；"
             "跑完由系统照它判定。不写，结果就只显示“未设门槛”，不会显示合格。判定只是记下来，不挡任何事。</p>")
    grows = []
    for r in spec.get("reports", []):
        key = r["key"]
        op, val = split_gate(r.get("suggest")) if v.get("gates") is None else v["gates"].get(key, ("", ""))
        sel = "".join(f'<option value="{k}"{" selected" if k == op else ""}>{t}</option>'
                      for k, t in [("", "不设")] + list(OPS.items()))
        hint = f'做法建议 {e(r["suggest"])}' if r.get("suggest") else ""
        grows.append(f'<tr><td>{e(r.get("name") or key)}</td><td><select name="gop_{e(key)}">{sel}</select> '
                     f'<input name="gval_{e(key)}" value="{e(val)}" size="8"> {e(r.get("unit", ""))}</td>'
                     f'<td class="small">{hint}</td></tr>')
    f.append("<table>" + "".join(grows) + "</table>" if grows else "<p>这个做法没说它会报哪些数，没法写门槛。</p>")
    title = v.get("title") or f'{m["name"]} {time.strftime("%m-%d %H:%M")}'
    f.append(f'<h2>第 4 步：启动</h2><p>标题 <input name="title" value="{e(title)}" size="50"></p>'
             f'<p><button class="go" name="action" value="start">封存并启动</button> '
             f'<span class="small">点了以后，这些选择、设置和门槛就封存了，改不了；想换就再开一个。'
             f'然后到仪表盘看它跑。</span></p></form>')
    return page("新建实验", "".join(out + f), "/new", data)


# ---------- 实验和结果 ----------

def exps_list(data, cat=""):
    st = ledger.state(data)
    cats = list(dict.fromkeys(x["seal"]["category"] for x in st.exps.values()))
    out = ["<p>" + "".join(f'<a class="pick{" on" if c == cat else ""}" href="/exps?cat={quote(c)}">{e(c)}</a>'
                           for c in cats) + (' <a href="/exps">全部</a>' if cat else "") + "</p>"]
    rows = []
    for x in reversed(list(st.exps.values())):
        s = x["seal"]
        if cat and s["category"] != cat:
            continue
        i = runs.status(data, x)
        verdict = word(i["end"]["verdict"]["result"]) if i["word"] == "完成" else ""
        rows.append(f'<tr><td><a href="/exp?id={s["n"]}">{e(s["title"])}</a> <span class="small">{eid(s["n"])}'
                    f'</span></td><td>{e(s["category"])}</td><td>{e(s["method"]["name"])} 第{s["method"]["version"]}版'
                    f'</td><td>{word(i["word"])}</td><td>{verdict}</td><td>{e(s["time"])}</td></tr>')
    out.append("<table><tr><th>实验</th><th>类</th><th>做法</th><th>现在</th><th>判定</th><th>封存时间</th></tr>"
               + "".join(rows) + "</table>" if rows else '<p>还没有实验。<a href="/new">新建一个</a></p>')
    return page("实验和结果", "".join(out), "/exps", data)


def experiment_live(data, n):
    st = ledger.state(data)
    x = st.exps[n]
    i = runs.status(data, x)
    p, quiet = runs.progress(data, n)
    end = i["end"] or {}
    extra = f' · 退出码 {e(end["code"])}' if end.get("code") is not None else ""
    extra += f' · {e(end["why"])}' if end.get("why") else ""
    times = f'第 {i["attempts"]} 次启动 · ' if i["attempts"] > 1 else ""
    times += f"{ago(quiet)}前有动静" if i["word"] in ("在跑", "中断") else f'结束于 {e(end.get("time"))}' if end else ""
    log = runs.tail(os.path.join(runs.run_dir(data, n), "log.txt"), 15)
    return (f'<span data-word="{e(i["word"])}"></span><p>现在：{word(i["word"])}'
            f'<span class="small"> {times}{extra}</span></p><p>进度：{bar(p)}</p>'
            f'<details{" open" if i["word"] != "完成" else ""}><summary>日志末尾</summary>'
            f'<pre>{e(log) or "（日志是空的）"}</pre></details>')


def experiment(data, n, errors=(), notes=()):
    st = ledger.state(data)
    x = st.exps.get(n)
    if not x:
        return page("找不到这个实验", '<p>账本里没有这个实验。<a href="/exps">回到实验列表</a></p>')
    s, i = x["seal"], runs.status(data, x)
    m = st.things.get(s["method"]["n"])
    spec = spec_of(data, m) or {}
    run = runs.run_dir(data, n)
    out = [msgs(errors, notes), f'<p class="small">编号 {eid(n)} · {e(s["category"])} · 封存于 {e(s["time"])}</p>',
           f'<div class="box" data-live="/exp_live?id={n}" data-word="{e(i["word"])}">{experiment_live(data, n)}</div><p>']
    if i["word"] == "在跑":
        out.append(f'<form class="inline" method="post" action="/stop"><input type="hidden" name="id" value="{n}">'
                   f'<button>停下</button></form> ')
    if i["word"] in ("中断", "失败", "停了", "没启动"):
        out.append(f'<form class="inline" method="post" action="/continue"><input type="hidden" name="id" '
                   f'value="{n}"><button>继续</button></form> <span class="small">在同一个目录里再起一次；'
                   f'从头算还是接着算，由做法决定。</span> ')
    out.append(f'<a class="pick" href="/new?from={n}">照这个再开一个</a> <span class="small">把这次的选择、设置和门槛'
               f'带进新建页，改了再启动；这一个原样留着。</span></p>')

    out.append("<h2>判定</h2>")
    end = final(x)
    reports = {r["key"]: r for r in spec.get("reports", [])}
    if not s["gates"]:
        out.append(f"<p>{word('未设门槛')}：这个实验封存时没写门槛，所以不显示合格或不合格。</p>")
    else:
        out.append(f'<p class="small">门槛写于 {e(s["time"])}，和实验一起封存，在这个实验的结果出来之前。</p>')
    for y, y_end in same_before(st, x):   # 只是摆出来，不挡
        out.append(msgs(notes=[f'同样的东西和设置，{eid(y["seal"]["n"])} 已经跑出过结果（门槛：'
                               f'{gate_text(y["seal"]["gates"], reports)}，{y_end["verdict"]["result"]}）。'
                               f'这次的门槛是在那之后写的。']))
    if end:
        if s["gates"]:
            out.append(f'<p>判定：{word(end["verdict"]["result"])} <span class="small">（{e(end["time"])} 跑完时由系统'
                       f'照门槛算出）</span></p>')
        rows = []
        checks = {c["metric"]: c for c in end["verdict"]["checks"]}
        for key in [k for k in reports if k in end["reports"]] + [k for k in end["reports"] if k not in reports]:
            val, r, c = end["reports"][key], reports.get(key, {}), checks.get(key)
            gate = f'{OPS[c["op"]]} {fmt(c["value"])}' if c else "—"
            ok = word("合格" if c["ok"] else "不合格") if c else ""
            rows.append(f'<tr><td>{e(r.get("name") or key)}</td><td>{e(fmt(val))} {e(r.get("unit", ""))}</td>'
                        f'<td>{e(gate)}</td><td>{ok}</td></tr>')
        for key, c in checks.items():
            if key not in end["reports"]:
                rows.append(f'<tr><td>{e(key)}</td><td>做法没报这个数</td>'
                            f'<td>{e(OPS[c["op"]])} {e(fmt(c["value"]))}</td><td>{word("不合格")}</td></tr>')
        out.append("<table><tr><th>报的数</th><th>数值</th><th>门槛</th><th></th></tr>" + "".join(rows) + "</table>")
    elif s["gates"]:
        out.append("<table><tr><th>报的数</th><th>门槛</th></tr>" + "".join(
            f'<tr><td>{e(reports.get(g["metric"], {}).get("name") or g["metric"])}</td>'
            f'<td>{e(OPS[g["op"]])} {e(fmt(g["value"]))} {e(reports.get(g["metric"], {}).get("unit", ""))}</td></tr>'
            for g in s["gates"]) + "</table><p>还没跑完，还没有判定。</p>")
    if end and end.get("figures"):
        out.append("<h2>图</h2>" + "".join(
            f'<figure><img src="/file?id={n}&path={quote(g["path"])}" alt="{e(g["title"])}">'
            f'<figcaption>{e(g["title"])}</figcaption></figure>' for g in end["figures"]))
    if end and end.get("table"):
        out.append("<h2>结果表</h2>" + csv_table(os.path.join(run, end["table"])))

    out.append("<h2>它用了什么</h2><table>")
    out.append(f'<tr><th>做法</th><td>{e(s["method"]["name"])} · 第{s["method"]["version"]}版 '
               f'<span class="small">指纹 {e(s["method"]["fingerprint"][:12])} · 留底在 '
               f'{e(things.where(data, m)) if m else ""}</span></td></tr>')
    labels = {inp["key"]: inp.get("label") or inp["key"] for inp in spec.get("inputs", [])}
    for key, ref in s["inputs"].items():
        t = st.things.get(ref["n"]) if ref else None
        used = (f'{e(ref["type"])}「{e(ref["name"])}」{ver(t)} · {origin(st, t)} <span class="small">'
                f'指纹 {e(ref["fingerprint"][:12])} · {"留底" if t["path"] else "在"} {e(things.where(data, t))}'
                f'{" · 从 " + e(t["path"]) + " 抄来" if t["path"] else ""}</span>' if t else "（没选）")
        out.append(f'<tr><th>{e(labels.get(key, key))}</th><td>{used}</td></tr>')
    if s.get("from"):
        out.append(f'<tr><th>照哪个开的</th><td><a href="/exp?id={s["from"]}">{eid(s["from"])}</a></td></tr>')
    drift = "".join(f'<br>第 {ev["attempt"]} 次启动时 stemlab/ 的指纹是 {e(ev["system"][:12])}，和封存时不一样：'
                    f'中间改过系统，那一次跑的是改过的代码' for ev in x["events"]
                    if ev["kind"] == "start" and ev.get("system") and ev["system"] != s["system"])
    out.append(f'<tr><th>系统</th><td><span class="small">封存时 stemlab/ 的指纹 {e(s["system"][:12])}</span>'
               f'{drift}</td></tr></table>')
    named = {d["key"]: d for d in spec.get("settings", [])}   # 按做法里写的顺序列，做法读不出来就按键
    keys = [k for k in named if k in s["settings"]] + [k for k in s["settings"] if k not in named]
    out.append("<h3>设置</h3><table><tr><th>分组</th><th>名字</th><th>值</th><th>单位</th></tr>" + "".join(
        f'<tr><td>{e(named.get(k, {}).get("group", ""))}</td><td>{e(named.get(k, {}).get("name") or k)} '
        f'<span class="small">{e(k)}</span></td><td>{e(fmt(s["settings"][k]))}</td>'
        f'<td>{e(named.get(k, {}).get("unit", ""))}</td></tr>' for k in keys) + "</table>")

    out.append("<h2>产出</h2>")
    if x["outputs"]:
        out.append("<ul>" + "".join(f'<li>{e(t["type"])}「<a href="/things#t{t["n"]}">{e(t["name"])}</a>」'
                                     f' <span class="small">{e(things.where(data, t))}</span></li>'
                                     for t in x["outputs"]) + "</ul>")
    else:
        out.append("<p>还没有产出。</p>")
    for problem in (end or {}).get("problems", []):
        out.append(msgs([problem]))
    out.append("<h2>实验目录里的文件</h2>" + file_list(run, n))
    return page(s["title"], "".join(out), "/exps", data)


def csv_table(path, limit=200):
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
    except (OSError, UnicodeDecodeError, csv.Error) as err:
        return msgs([f"结果表读不出来：{err}"])
    if not rows:
        return "<p>结果表是空的。</p>"
    more = f'<p class="small">只显示前 {limit} 行，一共 {len(rows) - 1} 行。</p>' if len(rows) > limit + 1 else ""
    return ("<table><tr>" + "".join(f"<th>{e(c)}</th>" for c in rows[0]) + "</tr>" + "".join(
        "<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in rows[1:limit + 1]) + "</table>" + more)


def file_list(run, n, limit=200):
    found = []
    for root, dirs, names in os.walk(run):
        dirs.sort()
        for name in sorted(names):
            rel = os.path.relpath(os.path.join(root, name), run).replace(os.sep, "/")
            found.append((rel, os.path.getsize(os.path.join(root, name))))
    if not found:
        return "<p>目录还是空的。</p>"
    return (f'<p class="small">{e(run)}</p><ul>' + "".join(
        f'<li><a href="/file?id={n}&path={quote(rel)}">{e(rel)}</a> <span class="small">{size:,} 字节</span></li>'
        for rel, size in found[:limit]) + "</ul>")


# ---------- 登记的东西 ----------

def rereg_button(t, label="登记成新的一版"):
    """把一样东西照原来的类型、名字、路径再登记一次。"""
    return (f'<form class="inline" method="post" action="/register">'
            + "".join(f'<input type="hidden" name="{k}" value="{e(val)}">' for k, val in
                      (("type", t["type"]), ("name", t["name"]), ("path", t["path"]),
                       ("note", f"从{things.label(t)}重新登记")))
            + f"<button>{label}</button></form>")


def things_page(data, form=None, errors=(), notes=()):
    st = ledger.state(data)
    form = form or {}
    types = sorted({t["type"] for t in st.things.values()} - {METHOD})
    out = [msgs(errors, notes), '<form method="post" action="/register_all"><p><button>把自带的模板和示例材料登记进来'
           '</button> <span class="small">清单在 examples/catalog.toml，可以随手改；登记过、内容没变的不会多出来</span>'
           '</p></form><h2>登记一样东西</h2><form method="post" action="/register"><table>',
           f'<tr><td>类型</td><td><input name="type" list="types" value="{e(form.get("type", ""))}" size="12"> '
           f'<datalist id="types">{"".join(f"<option>{e(t)}</option>" for t in [METHOD] + types)}</datalist>'
           f'<span class="small">一个词：骨、点、CT、结果、模型……；做法就写“做法”</span></td></tr>',
           f'<tr><td>名字</td><td><input name="name" value="{e(form.get("name", ""))}" size="30"> '
           f'<span class="small">同类型同名字再登记一次，就是新的一版。做法可以不写，用 method.toml 里的名字</span></td></tr>',
           f'<tr><td>路径</td><td><input name="path" value="{e(form.get("path", ""))}" size="70"><br>'
           f'<span class="small">一个文件或一个文件夹。可以写全路径，也可以写相对于 {e(os.getcwd())} 的路径，'
           f'比如 methods/fea_demo、examples/points_demo.csv。登记时会抄一份留底，实验用的是留底：'
           f'大文件要等一会儿、多占一份地方；之后原处的文件随你动，要用改过的就再登记一次。'
           f'做法是带 method.toml 的文件夹。</span></td></tr>',
           f'<tr><td>说明（来源）</td><td><input name="note" value="{e(form.get("note", ""))}" size="70"></td></tr>',
           '</table><p><button class="go">登记</button></p></form>']
    if not st.things:
        out.append("<p>还没有登记任何东西。</p>")
    for typ in [METHOD] + types:
        names = [(k[1], vs) for k, vs in st.names.items() if k[0] == typ]
        if not names:
            continue
        out.append(f"<h2>{e(typ)}</h2>")
        for name, vs in names:
            out.append(f"<h3>{e(name)}</h3><table><tr><th>哪一版</th>{'<th>类</th>' if typ == METHOD else ''}"
                       "<th>登记时间</th><th>来历</th><th>从哪来</th><th>说明</th></tr>")
            for t in reversed(vs):
                cat = f'<td>{e(t.get("category"))}</td>' if typ == METHOD else ""
                made_by = (t.get("source") or {}).get("experiment")
                out.append(f'<tr id="t{t["n"]}"><td class="nw">{ver(t) or eid(made_by) + " 的产出"} '
                           f'<span class="small">#{t["n"]}</span>'
                           f'</td>{cat}<td class="nw">{e(t["time"])}</td><td>{origin(st, t)}</td><td>{e(t["path"] or things.where(data, t))}<br>'
                           f'<span class="small">指纹 {e(t["fingerprint"][:12])} · {len(t["files"])} 个文件'
                           f'{" · 留底 " + e(t["kept"]) if t["path"] else ""}</span>'
                           f'</td><td>{e(t["note"])}</td></tr>')
            out.append("</table>")
    return page("登记的东西", "".join(out), "/things", data)


# ---------- 核对 ----------

def check_page(data, go=False):
    out = ["<p>把账本的链、每样登记的东西、每个实验的产出，和记下时比一遍。东西多、文件大时要等一会儿。</p>"]
    if not go:
        out.append('<p><a class="pick" href="/check?go=1">开始核对</a></p>')
        return page("核对", "".join(out), "/check", data)
    st = ledger.state(data)
    count, bad = ledger.verify(data)
    out.append(f"<h2>账本</h2><p>{word('一样') if not bad else word('不一样')} 一共 {count} 行，"
               f"{'链是完整的' if not bad else f'{len(bad)} 处对不上'}。</p>")
    gaps = [x for x in ledger.read(data) if x.get("kind") == "gap"]   # 以前出过、已经记进账本的事
    out.append("".join(f'<p>{word("记着")} 第 {x["n"]} 条记着：在它之前，{e(x["why"])}。</p>' for x in gaps))
    if bad:
        out.append("<table>" + "".join(
            f"<tr><td>{f'第 {i} 行' if i else '末尾'}</td><td>{e(what(x)) if x else ''}</td><td>{e(why)}</td></tr>"
            for i, x, why in bad[:20]) + "</table>" + (f"<p>……一共 {len(bad)} 处，只列前 20 处。</p>" if len(bad) > 20 else ""))
    rows, bad = [], 0
    for t in st.things.values():
        why = things.check(data, t)
        made_by = (t.get("source") or {}).get("experiment")
        if why:   # 外来的：留底被人动过，照原处恢复；实验的产出：跑完以后被人改过
            bad += 1
            note = f"{word('不一样')} {e(why)} " + (
                f'<span class="small">这是 {eid(made_by)} 的产出，那个实验跑完以后被人改过</span>' if made_by else
                rereg_button(t, "照原处的文件恢复留底") + ' <span class="small">原处的文件也改过的话，'
                '会成为新的一版，这一版的留底照旧是坏的</span>')
        elif t["type"] == METHOD and st.names[(t["type"], t["name"])][-1] is t and \
                fingerprint.check(t["path"], t["fingerprint"], t["files"]):   # 只对做法查原处：小，查得起
            note = (f"{word('一样')} <span class='small'>原来的文件夹后来改过，要用改过的就再登记一版</span> "
                    + rereg_button(t))
        else:
            note = word("一样")
        rows.append(f'<tr><td>{e(t["type"])}{e(things.label(t))} <span class="small">#{t["n"]}</span>'
                    f'</td><td>{note}</td></tr>')
    out.append(f"<h2>登记的东西</h2><p>{len(rows)} 样，{bad} 样不一样。</p><table>{''.join(rows)}</table>")
    rows, bad = [], 0
    for x in st.exps.values():
        end = final(x)
        if not end:
            continue
        n = x["seal"]["n"]
        why = fingerprint.check(runs.run_dir(data, n), end["fingerprint"], end["files"])
        bad += bool(why)
        rows.append(f'<tr><td><a href="/exp?id={n}">{e(x["seal"]["title"])}</a> <span class="small">{eid(n)}</span></td>'
                    f'<td>{(word("不一样") + " " + e(why)) if why else word("一样")}</td></tr>')
    out.append(f"<h2>实验的产出</h2><p>{len(rows)} 个跑完的实验，{bad} 个的目录和跑完时不一样。</p>"
               f"<table>{''.join(rows)}</table>")
    # 账本末尾被砍掉、或被旧的换回去，链本身看不出来；data/ 里有、账本上没有的东西能露出一点
    known = {os.path.basename(runs.run_dir(data, n)) for n in st.exps}
    known |= {t["kept"].split("/")[1] for t in st.things.values() if t["kept"].startswith("store/")}
    extra = [os.path.join(part, d) for part in ("runs", "store") if os.path.isdir(os.path.join(data, part))
             for d in sorted(os.listdir(os.path.join(data, part)))
             if os.path.isdir(os.path.join(data, part, d)) and d not in known and not d.startswith("tmp-")]
    out.append("<h2>data 里有、账本上没有的</h2>" + (
        msgs([f"data 里有 {len(extra)} 个实验目录或留底，账本上没有：{'、'.join(extra)}。"
              "账本末尾可能被砍掉过，或被换成了旧的。"]) if extra else f"<p>{word('没有')}</p>"))
    now = fingerprint.of(runs.SYSTEM)[0]
    other = sum(1 for x in st.exps.values() if x["seal"]["system"] != now)
    out.append(f'<h2>系统自己</h2><p>stemlab/ 现在的指纹 <span class="small">{now[:12]}</span>；'
               f'{other} 个实验封存时用的是别的版本（每个实验页上都记着它当时的指纹）。</p>')
    return page("核对", "".join(out), "/check", data)
