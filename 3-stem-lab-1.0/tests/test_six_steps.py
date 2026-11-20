"""一页纸的六步，四类各走一遍；每一类都只用外面登记进来的东西单独启动。再试一条一个接一个的线，和停、继续。"""
import re
import time
import unittest
import urllib.request
from urllib.parse import quote

from util import Lab
from stemlab import ledger, runs


class FirstUse(unittest.TestCase):

    def test_register_everything_shipped_with_one_click(self):
        """第一次用：一键把自带的模板和示例材料登记进来；再点一次不会多出东西。"""
        lab = Lab()
        self.addCleanup(lab.close)
        self.assertIn("库里还是空的", lab.get("/live")[1])
        _, html = lab.post("/register_all", {})
        made = len(lab.state().things)
        self.assertGreaterEqual(made, 10)
        self.assertNotIn('class="err"', html)
        _, html = lab.post("/register_all", {})
        self.assertEqual(len(lab.state().things), made)
        self.assertIn(f"另有 {made} 样早就登记过", html)


class SixSteps(unittest.TestCase):

    def setUp(self):
        self.lab = Lab()
        lab = self.lab
        self.m = {k: lab.method(k + "_demo") for k in ("recon", "fea", "surrogate", "optimize")}
        self.ct = lab.register("CT", "示例CT", "examples/ct_demo.txt")
        self.bone = lab.register("骨", "示例骨", "examples/bone_demo.json")
        self.pts = lab.register("点", "示例点", "examples/points_demo.csv")
        self.res = lab.register("结果", "示例结果", "examples/results_demo.csv")
        self.model = lab.register("模型", "示例模型", "examples/model_demo.json")

    def tearDown(self):
        self.lab.close()

    def walk(self, category, method, inputs, change, look_for):
        lab = self.lab
        # 1. 新建一个实验，选它是哪一类
        _, html = lab.get("/new")
        for c in ("重建", "FEA", "代理", "优化"):
            self.assertIn(f">{c}<", html)
        _, html = lab.get("/new?cat=" + quote(category))
        self.assertIn(method["name"], html)
        # 2. 选要用的东西：从登记过的里挑；3. 填设置：有名字、单位、默认值、范围
        _, html = lab.get(f"/new?method={method['n']}")
        for t in inputs.values():
            self.assertIn(f'value="{t["n"]}"', html)
        for words in look_for + ["默认", "（请选）"]:
            self.assertIn(words, html)
        _, html = lab.post("/new", lab.form(method, {k: None for k in inputs}))   # 不替用户挑：没选就不让启动
        self.assertIn("还没选", html)
        # 4. 点启动，在仪表盘上看它跑
        n = lab.start(lab.form(method, inputs))
        _, html = lab.get("/live")
        self.assertIn(f"e{n:04d}", html)
        # 5. 跑完看结果，点开能看到它用了什么
        info = lab.wait(n)
        self.assertEqual(info["word"], "完成", info)
        _, html = lab.get(f"/exp?id={n}")
        self.assertIn("它用了什么", html)
        self.assertIn(f'{method["name"]} · 第{method["version"]}版', html)
        figure = re.search(r'<figure><img src="([^"]+)"', html)               # 包画的图摆在结果页上
        self.assertTrue(figure, "结果页上没有图")
        with urllib.request.urlopen(lab.base + figure.group(1).replace("&amp;", "&")) as r:
            self.assertEqual(r.headers["Content-Type"], "image/svg+xml")
            self.assertIn("sandbox", r.headers["Content-Security-Policy"])
        for t in inputs.values():
            self.assertIn(f'「{t["name"]}」第{t["version"]}版', html)
        # 6. 换个设置再算：再开一个，前一个原样留着
        _, html = lab.get(f"/new?from={n}")
        self.assertIn(f"照 e{n:04d}", html)
        key, value = change
        n2 = lab.start(dict(lab.form(method, inputs), **{"set_" + key: value, "from": n}))
        self.assertEqual(lab.wait(n2)["word"], "完成")
        st = lab.state()
        self.assertEqual(st.exps[n2]["seal"]["from"], n)
        self.assertNotEqual(st.exps[n2]["seal"]["settings"][key], st.exps[n]["seal"]["settings"][key])
        self.assertEqual(runs.status(lab.data, st.exps[n])["word"], "完成")
        return st.exps[n]

    def test_reconstruction(self):
        x = self.walk("重建", self.m["recon"], {"ct": self.ct}, ("voxel", 1.5), ["阈值", "HU", "100 ~ 1500 HU"])
        self.assertEqual(x["outputs"][0]["type"], "骨")

    def test_fea(self):
        x = self.walk("FEA", self.m["fea"], {"bone": self.bone, "points": self.pts}, ("load", 1800),
                      ["载荷", "500 ~ 5000 N", "摩擦系数", "绑定接触", "最大应力"])
        self.assertEqual(x["outputs"][0]["type"], "结果")

    def test_surrogate_alone_from_an_outside_result(self):
        x = self.walk("代理", self.m["surrogate"], {"result": self.res}, ("degree", "一次"), ["多项式次数", "留出比例"])
        self.assertEqual(x["outputs"][0]["type"], "模型")

    def test_optimization_alone_from_an_outside_model(self):
        x = self.walk("优化", self.m["optimize"], {"model": self.model}, ("seed", 7), ["撒多少个点", "越小越好"])
        self.assertEqual(x["outputs"][0]["type"], "点")

    def test_one_after_another(self):
        """产出的类型对得上，就能一个接一个用：重建→FEA→代理→优化→再 FEA。系统不自动接，每一步都是人选的。"""
        lab = self.lab

        def run(key, inputs):
            n = lab.start(lab.form(self.m[key], inputs))
            self.assertEqual(lab.wait(n)["word"], "完成")
            return lab.state().exps[n]["outputs"][0]
        bone = run("recon", {"ct": self.ct})
        result = run("fea", {"bone": bone, "points": self.pts})
        model = run("surrogate", {"result": result})
        points = run("optimize", {"model": model})
        again = run("fea", {"bone": bone, "points": points})
        _, html = lab.get(f"/exp?id={again['source']['experiment']}")
        self.assertIn("重建示例 第1版", html)   # “它用了什么”里，骨的来历一直摆出来
        self.assertIn("优化示例 第1版", html)

    def test_stop_and_continue(self):
        lab = self.lab
        n = lab.start(dict(lab.form(self.m["fea"], {"bone": self.bone, "points": self.pts}), set_pause=0.5))
        deadline = time.time() + 20
        while runs.progress(lab.data, n)[0] is None and time.time() < deadline:
            time.sleep(0.2)
        _, html = lab.post("/continue", {"id": n})
        self.assertIn("不用继续", html)                       # 在跑的时候不会再起一个
        lab.post("/stop", {"id": n})
        self.assertEqual(runs.status(lab.data, lab.state().exps[n])["word"], "停了")
        _, html = lab.get("/live")
        self.assertIn("哪里停了", html)
        self.assertRegex(html, re.compile(f"e{n:04d}.*停了|停了.*e{n:04d}", re.S))
        lab.post("/continue", {"id": n})
        info = lab.wait(n, timeout=40)
        self.assertEqual((info["word"], info["attempts"]), ("完成", 2))
        self.assertTrue(ledger.verify(lab.data)[0])


if __name__ == "__main__":
    unittest.main()
