"""一页纸里最少要守住的三件事，各几条。"""
import os
import shutil
import textwrap
import unittest

from util import REPO, Lab
from stemlab import fingerprint, ledger, runs, things
from stemlab.things import Problem


def tiny_method(lab, folder, script):
    """在测试的数据目录里写一个最小的做法，登记上。"""
    folder = os.path.join(lab.data, folder)
    os.makedirs(folder)
    with open(os.path.join(folder, "method.toml"), "w", encoding="utf-8") as f:
        f.write('name = "%s"\ncategory = "FEA"\ncommand = "{python} {method}/run.py {run}"\n' % os.path.basename(folder))
    with open(os.path.join(folder, "run.py"), "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(script))
    return things.register(lab.data, "做法", "", folder)[0]


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
        self.assertEqual(ledger.verify(d), (3, []))
        path = os.path.join(d, ledger.FILE)
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.writelines([lines[0], lines[1].replace("第 2 条", "改过的"), lines[2].replace("第 3 条", "也改过")])
        self.assertEqual([i for i, _, _ in ledger.verify(d)[1]], [2, 3])   # 不在第一处就停
        _, html = self.lab.get("/")                                          # 平常的页面顶上就说
        self.assertIn("账本有 2 处对不上", html)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.writelines([lines[0], lines[2]])
        self.assertEqual([i for i, _, _ in ledger.verify(d)[1]], [2])

    def test_cut_tail_shows_up_in_check(self):
        """末尾被砍，和账本旁边的头一比就认得出来；data 里有、账本上没有的东西也列出来。"""
        lab = self.lab
        m = lab.method("fea_demo")
        os.makedirs(os.path.join(lab.data, "runs", "e0099"))
        path = os.path.join(lab.data, ledger.FILE)
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(lines[:-1])          # 砍掉最后一条：登记做法的那条
        self.assertIn("末尾少了 1 条", ledger.verify(lab.data)[1][-1][2])
        _, html = lab.get("/check?go=1")
        self.assertIn("末尾少了 1 条", html)
        self.assertIn("账本上没有", html)
        self.assertIn("e0099", html)
        self.assertIn(m["fingerprint"][:16], html)
        # 接着照常往里加（这里是登记一样东西）：痕迹记进账本，一直在；红字只管现在对不上的
        lab.post("/register", {"type": "骨", "name": "示例骨", "path": os.path.join(REPO, "examples", "bone_demo.json")})
        self.assertEqual(ledger.verify(lab.data)[1], [])
        _, html = lab.get("/check?go=1")
        self.assertIn("在它之前，账本末尾少了 1 条", html)
        self.assertNotIn("处对不上", lab.get("/live")[1])
        os.remove(os.path.join(lab.data, ledger.HEAD))           # 把头删掉再加：也记下来
        lab.register("点", "示例点", "examples/points_demo.csv")
        self.assertIn("在它之前，账本旁边的头不见了", lab.get("/check?go=1")[1])

    def test_first_start_needs_a_fresh_directory(self):
        lab = self.lab
        m = lab.method("fea_demo")
        bone = lab.register("骨", "示例骨", "examples/bone_demo.json")
        pts = lab.register("点", "示例点", "examples/points_demo.csv")
        nxt = ledger.read(lab.data)[-1]["n"] + 1          # 下一个实验会用的目录，先放进旧东西
        os.makedirs(runs.run_dir(lab.data, nxt))
        with open(os.path.join(runs.run_dir(lab.data, nxt), "old.txt"), "w", encoding="utf-8") as f:
            f.write("旧的")
        _, html = lab.post("/new", lab.form(m, {"bone": bone, "points": pts}))
        self.assertIn("已经有东西了", html)
        self.assertEqual(runs.status(lab.data, lab.state().exps[nxt])["word"], "没启动")

    def test_previous_result_is_not_taken_for_this_attempt(self):
        """第一次写了结果但失败；继续以后什么也没算、退出码 0：不能把第一次的结果当成这一次的。"""
        lab = self.lab
        m = tiny_method(lab, "twice", """\
            import json, os, sys
            run = sys.argv[1]
            if os.path.exists(os.path.join(run, "result.attempt1.json")):
                sys.exit(0)              # 第二次：什么也没算，退出码 0
            with open(os.path.join(run, "result.json"), "w") as f:
                json.dump({"reports": {"a": 1}}, f)
            sys.exit(3)                  # 第一次：写了结果，但失败了
            """)
        n = runs.seal(lab.data, "FEA", "两次", m, {}, {}, [])["n"]
        runs.start(lab.data, n)
        self.assertEqual(lab.wait(n)["end"]["code"], 3)
        runs.start(lab.data, n)
        end = lab.wait(n)["end"]
        self.assertEqual((end["status"], end["code"]), ("失败", 0))
        self.assertTrue(os.path.exists(os.path.join(runs.run_dir(lab.data, n), "result.attempt1.json")))

    def test_one_watcher_per_experiment(self):
        """看护进程活着（收尾时也算）就是在跑，不显示中断；同一个实验不会有第二个看护进程。"""
        lab = self.lab
        m = lab.method("fea_demo")
        bone = lab.register("骨", "示例骨", "examples/bone_demo.json")
        pts = lab.register("点", "示例点", "examples/points_demo.csv")
        n = lab.start(lab.form(m, {"bone": bone, "points": pts}, pause=0.5))
        while not ledger.held(runs.lock_path(lab.data, n)) and runs.status(
                lab.data, lab.state().exps[n])["word"] == "在跑":
            pass
        self.assertTrue(ledger.held(runs.lock_path(lab.data, n)), "看护进程应当握着锁")
        self.assertRaisesRegex(Problem, "还没结束", runs.start, lab.data, n)
        self.assertEqual(lab.wait(n)["word"], "完成")
        self.assertEqual(sum(e["kind"] == "start" for e in lab.state().exps[n]["events"]), 1)
        # 用测试自己握住锁，装成一个收尾很久、很久没动静的看护进程
        x = runs.seal(lab.data, "FEA", "装的", m, {"bone": bone, "points": pts}, {}, [])
        ledger.append(lab.data, {"kind": "start", "exp": x["n"], "attempt": 1})
        old, runs.STARTING = runs.STARTING, 0
        self.addCleanup(setattr, runs, "STARTING", old)
        lock = ledger.grab(runs.lock_path(lab.data, x["n"]), 1)
        self.assertEqual(runs.status(lab.data, lab.state().exps[x["n"]])["word"], "在跑")
        self.assertRaisesRegex(Problem, "还没结束", runs.start, lab.data, x["n"])
        ledger._unlock(lock)
        lock.close()
        self.assertEqual(runs.status(lab.data, lab.state().exps[x["n"]])["word"], "中断")

    def test_kept_copy_is_what_runs_and_can_be_restored(self):
        """登记时抄一份留底：改原处不影响已登记的这一版；动了留底，启动被拦、核对认得出、能照原处恢复。"""
        lab = self.lab
        mine = os.path.join(lab.data, "my_points.csv")
        shutil.copy(os.path.join(REPO, "examples", "points_demo.csv"), mine)
        m = lab.method("fea_demo")
        bone = lab.register("骨", "示例骨", "examples/bone_demo.json")
        v1 = lab.register("点", "我的点", mine)
        with open(mine, "a", encoding="utf-8") as f:
            f.write("p99,150,30\n")                                    # 改了原处
        n = lab.start(lab.form(m, {"bone": bone, "points": v1}))
        self.assertEqual(lab.wait(n)["word"], "完成")
        with open(os.path.join(runs.run_dir(lab.data, n), "out", "results.csv"), encoding="utf-8") as f:
            self.assertEqual(len(f.readlines()), 1 + 12)                 # 用的还是登记时的 12 个点
        v2, _ = things.register(lab.data, "点", "我的点", mine)         # 再登记才是新的一版
        self.assertEqual(v2["version"], 2)
        with open(things.where(lab.data, v2), "a", encoding="utf-8") as f:
            f.write("p98,140,30\n")                                    # 有人动了第2版的留底
        before = len(lab.state().exps)
        _, html = lab.post("/new", lab.form(m, {"bone": bone, "points": v2}))
        self.assertIn("my_points.csv 变了", html)
        self.assertIn("留底被人动过", html)
        self.assertEqual(len(lab.state().exps), before, "不该封存")
        _, html = lab.get("/check?go=1")
        self.assertIn("照原处的文件恢复留底", html)
        form = dict(lab.form(m, {"bone": bone, "points": v2}), action="rereg:points")
        _, html = lab.post("/new", form)                                 # 原处没再变：照它恢复，不多出一版
        self.assertIn("已经照原处的文件恢复", html)
        self.assertIsNone(things.check(lab.data, v2))
        self.assertEqual(lab.wait(lab.start(lab.form(m, {"bone": bone, "points": v2})))["word"], "完成")

    def test_broken_method_copy_can_be_restored(self):
        lab = self.lab
        m = lab.method("fea_demo")
        with open(os.path.join(things.where(lab.data, m), "run.py"), "a", encoding="utf-8") as f:
            f.write("# 有人动了留底\n")
        self.assertIn("run.py 变了", things.check(lab.data, m))
        _, html = lab.get("/check?go=1")
        self.assertIn("照原处的文件恢复留底", html)
        _, told = things.register(lab.data, "做法", "", os.path.join(REPO, "methods", "fea_demo"))
        self.assertIn("已经照原处的文件恢复", told)
        self.assertIsNone(things.check(lab.data, m))

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
        moved = os.path.join(lab.data, "bone_moved.json")             # 内容一样、挪了地方：不多出一版
        shutil.copy(os.path.join(REPO, "examples", "bone_demo.json"), moved)
        same, told = things.register(lab.data, "骨", "示例骨", moved)
        self.assertEqual((same["n"], told[:5]), (bone["n"], "没有新登记"))
        with open(moved, "a", encoding="utf-8") as f:                  # 内容变了：第2版，但这次选第1版
            f.write("\n")
        self.assertEqual(things.register(lab.data, "骨", "示例骨", moved)[0]["version"], 2)
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
        self.assertEqual([e["system"] for e in x["events"] if e["kind"] == "start"], [s["system"]])
        [out] = x["outputs"]
        self.assertEqual((out["type"], out["source"], out["version"]), ("结果", {"experiment": n}, None))
        _, html = lab.get(f"/exp?id={n}")
        for words in ("它用了什么", "示例骨」第1版", "示例点」第1版", "FEA 示例 · 第1版", "载荷", "2600", "摩擦系数"):
            self.assertIn(words, html)


    def test_data_folder_can_move(self):
        """整个数据文件夹挪到别处再开：核对全是“一样”，旧的产出还能被选来开新实验。"""
        lab = Lab()
        rm, fm = lab.method("recon_demo"), lab.method("fea_demo")
        ct = lab.register("CT", "示例CT", "examples/ct_demo.txt")
        pts = lab.register("点", "示例点", "examples/points_demo.csv")
        n = lab.start(lab.form(rm, {"ct": ct}))
        lab.wait(n)
        [bone] = lab.state().exps[n]["outputs"]
        lab.close(keep=True)
        moved = lab.data + "-moved"
        shutil.move(lab.data, moved)
        lab = Lab(moved)
        self.addCleanup(lab.close)
        _, html = lab.get("/check?go=1")
        self.assertNotIn('class="bad">不一样', html)
        self.assertNotIn("找不到了", html)
        self.assertEqual(lab.wait(lab.start(lab.form(fm, {"bone": bone, "points": pts})))["word"], "完成")

    def test_output_must_be_inside_the_experiment(self):
        """做法把目录外面一个早就有的文件报成产出，不能算这个实验的产出。"""
        lab = Lab()
        self.addCleanup(lab.close)
        outside = os.path.join(REPO, "examples", "bone_demo.json")
        m = tiny_method(lab, "claims", f"""\
            import json, os, sys
            run = sys.argv[1]
            with open(os.path.join(run, "result.json"), "w") as f:
                json.dump({{"reports": {{}}, "outputs": [{{"type": "骨", "name": "别人的骨", "path": {outside!r}}}]}}, f)
            """)
        n = runs.seal(lab.data, "FEA", "冒领", m, {}, {}, [])["n"]
        runs.start(lab.data, n)
        end = lab.wait(n)["end"]
        self.assertEqual(lab.state().exps[n]["outputs"], [])
        self.assertIn("不在实验目录里", end["problems"][0])


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
        # 照不合格的那个再开、只把门槛放宽：页面上要看得出这次的门槛是在同样的结果出来以后写的
        again = lab.start(dict(lab.form(m, {"bone": bone, "points": pts}, gates={"max_stress": ("<=", "1e8")}),
                               **{"from": strict}))
        lab.wait(again)
        _, html = lab.get(f"/exp?id={again}")
        self.assertIn("在这个实验的结果出来之前", html)
        self.assertIn(f"e{strict:04d} 已经跑出过结果（门槛：最大应力 ≤ 1，不合格）", html)
        # nan、inf 不算数
        _, html = lab.post("/new", lab.form(m, {"bone": bone, "points": pts}, gates={"max_stress": ("<=", "nan")}))
        self.assertIn("实实在在的数", html)
        _, html = lab.post("/new", lab.form(m, {"bone": bone, "points": pts}, load="inf"))
        self.assertIn("实实在在的数", html)


if __name__ == "__main__":
    unittest.main()
