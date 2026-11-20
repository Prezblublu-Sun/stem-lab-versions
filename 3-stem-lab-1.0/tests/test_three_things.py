"""一页纸里最少要守住的三件事，各几条。"""
import os
import shutil
import unittest

from util import REPO, Lab
from stemlab import fingerprint, ledger, runs


class Untouched(unittest.TestCase):
    """记下来的不被悄悄改：只往后加；内容和登记时不一样，认得出来。"""

    def setUp(self):
        self.lab = Lab()

    def tearDown(self):
        self.lab.close()

    def test_edited_or_removed_line_is_caught(self):
        d = self.lab.data
        for i in range(3):
            ledger.append(d, {"kind": "note", "text": f"第 {i + 1} 条"})
        self.assertTrue(ledger.verify(d)[0])
        path = os.path.join(d, ledger.FILE)
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.writelines([lines[0], lines[1].replace("第 2 条", "改过的"), lines[2]])
        ok, msg = ledger.verify(d)
        self.assertFalse(ok)
        self.assertIn("第 2 行", msg)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.writelines([lines[0], lines[2]])
        ok, msg = ledger.verify(d)
        self.assertFalse(ok)
        self.assertIn("第 2 行", msg)

    def test_changed_thing_blocks_start_and_names_the_file(self):
        lab = self.lab
        mine = os.path.join(lab.data, "my_points.csv")   # 外来的东西留在原处，不抄
        shutil.copy(os.path.join(REPO, "examples", "points_demo.csv"), mine)
        m = lab.method("fea_demo")
        bone = lab.register("骨", "示例骨", "examples/bone_demo.json")
        pts = lab.register("点", "我的点", mine)
        with open(mine, "a", encoding="utf-8") as f:
            f.write("p99,150,30\n")
        before = len(lab.state().exps)
        _, html = lab.post("/new", lab.form(m, {"bone": bone, "points": pts}))
        self.assertIn("my_points.csv 变了", html)
        self.assertIn("登记成新的一版", html)
        self.assertEqual(len(lab.state().exps), before, "不该封存")
        # 一键登记成新的一版，再启动就行了
        form = lab.form(m, {"bone": bone, "points": pts})
        form["action"] = "rereg:points"
        _, html = lab.post("/new", form)
        self.assertIn("第2版", html)
        new = max(t["n"] for t in lab.state().things.values() if t["name"] == "我的点")
        form["action"], form["in_points"] = "start", new
        self.assertEqual(lab.wait(lab.start(form))["word"], "完成")

    def test_changed_output_is_caught(self):
        lab = self.lab
        m = lab.method("surrogate_demo")
        res = lab.register("结果", "示例结果", "examples/results_demo.csv")
        n = lab.start(lab.form(m, {"result": res}))
        end = lab.wait(n)["end"]
        out = os.path.join(runs.run_dir(lab.data, n), "out", "model.json")
        self.assertIsNone(fingerprint.check(runs.run_dir(lab.data, n), end["fingerprint"], end["files"]))
        with open(out, "a", encoding="utf-8") as f:
            f.write(" ")
        why = fingerprint.check(runs.run_dir(lab.data, n), end["fingerprint"], end["files"])
        self.assertIn("out/model.json 变了", why)
        _, html = lab.get("/check?go=1")
        self.assertIn("model.json 变了", html)


class Traceable(unittest.TestCase):
    """每个结果追得到来历：哪根骨、哪些点、哪个做法的哪一版、哪份设置，连系统自己的指纹。"""

    def test_seal_and_outputs_carry_where_they_came_from(self):
        lab = Lab()
        self.addCleanup(lab.close)
        m = lab.method("fea_demo")
        bone = lab.register("骨", "示例骨", "examples/bone_demo.json")
        lab.register("骨", "示例骨", "examples/bone_demo.json")      # 第2版，但这次选第1版
        pts = lab.register("点", "示例点", "examples/points_demo.csv")
        n = lab.start(lab.form(m, {"bone": bone, "points": pts}, load=2600))
        self.assertEqual(lab.wait(n)["word"], "完成")
        x = lab.state().exps[n]
        s = x["seal"]
        self.assertEqual((s["method"]["name"], s["method"]["version"]), ("FEA 示例", 1))
        self.assertEqual(s["method"]["fingerprint"], m["fingerprint"])
        self.assertEqual((s["inputs"]["bone"]["version"], s["inputs"]["bone"]["fingerprint"]),
                         (1, bone["fingerprint"]))
        self.assertEqual(s["settings"]["load"], 2600.0)
        self.assertEqual(s["system"], fingerprint.of(runs.SYSTEM)[0])
        [out] = x["outputs"]
        self.assertEqual((out["type"], out["source"]), ("结果", {"experiment": n}))
        _, html = lab.get(f"/exp?id={n}")
        for words in ("它用了什么", "示例骨」第1版", "示例点」第1版", "FEA 示例 · 第1版", "载荷", "2600", "摩擦系数"):
            self.assertIn(words, html)


class GateFirst(unittest.TestCase):
    """合格的门槛，看到结果之前写定：写在封存里，排在结束之前；没写就永远不显示合格。"""

    def test_judge(self):
        self.assertEqual(runs.judge([], {"a": 1})["result"], "未设门槛")
        self.assertEqual(runs.judge([{"metric": "a", "op": "<=", "value": 2}], {"a": 1})["result"], "合格")
        self.assertEqual(runs.judge([{"metric": "a", "op": ">", "value": 2}], {"a": 1})["result"], "不合格")
        self.assertEqual(runs.judge([{"metric": "b", "op": "<=", "value": 2}], {"a": 1})["result"], "不合格")

    def test_gate_is_sealed_before_result_and_judged_by_core(self):
        lab = Lab()
        self.addCleanup(lab.close)
        m = lab.method("fea_demo")
        bone = lab.register("骨", "示例骨", "examples/bone_demo.json")
        pts = lab.register("点", "示例点", "examples/points_demo.csv")
        strict = lab.start(lab.form(m, {"bone": bone, "points": pts}, gates={"max_stress": ("<=", "1")}))
        loose = lab.start(lab.form(m, {"bone": bone, "points": pts}, gates={"max_stress": ("<=", "1e9")}))
        none = lab.start(lab.form(m, {"bone": bone, "points": pts}))
        self.assertEqual(lab.wait(strict)["end"]["verdict"]["result"], "不合格")
        self.assertEqual(lab.wait(loose)["end"]["verdict"]["result"], "合格")
        self.assertEqual(lab.wait(none)["end"]["verdict"]["result"], "未设门槛")
        entries = ledger.read(lab.data)
        seal = next(e for e in entries if e["n"] == strict)
        end = next(e for e in entries if e.get("exp") == strict and e["kind"] == "end")
        self.assertLess(seal["n"], end["n"])
        self.assertEqual(seal["gates"], [{"metric": "max_stress", "op": "<=", "value": 1.0}])
        _, html = lab.get(f"/exp?id={none}")
        self.assertIn("未设门槛", html)
        self.assertNotIn(">合格<", html)
        # 不合格的产出照样能被选，只是带着标记
        sm = lab.method("surrogate_demo")
        _, html = lab.get(f"/new?method={sm['n']}")
        self.assertIn("不合格", html)


if __name__ == "__main__":
    unittest.main()
