"""后台进程：一个作业接一个作业地导出。插件的 start 把它起起来，之后它自己跑。

用法：python worker.py <这个实验的 plugin_state 文件夹>

它不碰实验记录。它只写 plugin_state 里的这几样，插件的 poll 来读：
  progress.jsonl   每个作业走到哪了，一行一条，只追加
  state.json       每个作业的结局：完成 或 失败
  rows/<作业>.json 这个作业的一行标签和清单
  done.json        这一趟做完了（包括汇总）
它看这两个文件来听话：STOP（有就尽快停）、PAUSE（有就做完手上这个作业后等着）。
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import fae_columns as C  # noqa: E402
import fae_core as K  # noqa: E402


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class Run:
    def __init__(self, state_dir: Path):
        self.dir = state_dir
        self.plan = json.loads((state_dir / "plan.json").read_text(encoding="utf-8"))
        self.archive = Path(self.plan["archive"])
        self.out = Path(self.plan["outputs"])
        self.quantities = list(self.plan["quantities"])
        self.rows_dir = state_dir / "rows"
        self.rows_dir.mkdir(exist_ok=True)
        self.state_file = state_dir / "state.json"
        self.state = json.loads(self.state_file.read_text(encoding="utf-8")) if self.state_file.exists() else {}

    # ---- 往外说 ---------------------------------------------------------

    def say(self, job: str, state: str, stage: str = "", **more) -> None:
        line = json.dumps({"time": now(), "job": job, "state": state, "stage": stage, **more}, ensure_ascii=False)
        with open(self.dir / "progress.jsonl", "ab") as f:
            f.write(line.encode("utf-8") + b"\n")
            f.flush()
            os.fsync(f.fileno())

    def save_state(self) -> None:
        tmp = self.state_file.with_name("state.json.part")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.state_file)

    # ---- 听话 -----------------------------------------------------------

    def stop_asked(self) -> bool:
        return (self.dir / "STOP").exists()

    def wait_if_paused(self) -> None:
        while (self.dir / "PAUSE").exists() and not self.stop_asked():
            time.sleep(0.3)

    # ---- 一个作业 --------------------------------------------------------

    def one(self, job: str) -> None:
        def stage(name: str) -> None:
            if self.stop_asked():
                raise K.Stopped()
            self.say(job, "运行", name)

        try:
            res = K.export_job(self.archive, job, self.out, self.quantities, stage=stage)
        except K.Stopped:
            raise
        except K.ArchiveError as err:
            self.state[job] = "失败"
            (self.rows_dir / f"{job}.json").write_text(
                json.dumps({"job_id": job, "unreadable": str(err)}, ensure_ascii=False), encoding="utf-8")
            self.say(job, "失败", "读归档", error=f"归档读不了：{err}", raw=traceback.format_exc())
            return
        except Exception as err:  # 没想到的错：记下来，接着做别的作业
            self.state[job] = "失败"
            (self.rows_dir / f"{job}.json").write_text(
                json.dumps({"job_id": job, "unreadable": f"{type(err).__name__}: {err}"}, ensure_ascii=False), encoding="utf-8")
            self.say(job, "失败", error=f"导出出错：{type(err).__name__}: {err}", raw=traceback.format_exc())
            return
        K.write_text(self.rows_dir / f"{job}.json", json.dumps(res, ensure_ascii=False, default=float))
        if res["errors"]:
            self.state[job] = "失败"
            self.say(job, "失败", error="；".join(res["errors"]), notes=res["notes"])
        else:
            self.state[job] = "完成"
            self.say(job, "完成", notes=res["notes"])

    # ---- 汇总 -----------------------------------------------------------

    def summary(self) -> dict:
        rows, invs, unreadable = [], [], []
        for job in self.plan["jobs"]:
            f = self.rows_dir / f"{job}.json"
            if not f.exists():
                continue
            rec = json.loads(f.read_text(encoding="utf-8"))
            if "unreadable" in rec:
                unreadable.append({"job_id": job, "error": rec["unreadable"]})
                continue
            rows.append(rec["row"])
            invs.append({**rec["inventory"], "errors": rec["errors"], "notes": rec["notes"]})
        if "标签" in self.quantities:
            K.write_labels(self.out, rows)
            old = json.loads((HERE / "old_columns.json").read_text(encoding="utf-8"))
            K.write_text(self.out / "标签" / "标签说明.json", json.dumps({
                "这是什么": "标签.csv 的每一列从哪来；旧表（db3406 的 scalars.csv）里哪些列这里没有，为什么",
                "写法": "和旧表相同：空格子是没有；小数用能原样读回的写法；布尔是 true / false；json 是紧凑的 json 文字",
                "列": [{"name": n, "type": t, "来源": cls, "从哪来": src} for n, t, cls, src in C.COLUMNS],
                "旧表的列": old,
                "原始json": "原始json/<作业号>.json 是归档里每个 json、标记文件、日志的原文，加归档的清单",
            }, ensure_ascii=False, indent=1))
        counts = {s: sum(1 for j in self.plan["jobs"] if self.state.get(j) == s) for s in ("完成", "失败")}
        doc = {
            "插件": f"fea-archive-export {K.VERSION}",
            "做完的时间": now(),
            "归档": str(self.archive),
            "导出的量": self.quantities,
            "作业数": len(self.plan["jobs"]),
            "结局": counts,
            "归档读不了的作业": unreadable,
            "界面场的格式": K.IFACE_DOC,
            "整体场的格式": K.GLOBAL_DOC,
            "每个作业": invs,
        }
        K.write_text(self.out / "说明" / "说明.json", json.dumps(doc, ensure_ascii=False, indent=1))
        K.write_text(self.out / "说明" / "说明.md", self.readme(doc, invs, unreadable))
        return counts

    def readme(self, doc: dict, invs: list, unreadable: list) -> str:
        lines = [
            "# 这份数据是什么",
            "",
            f"由插件 {doc['插件']} 从归档导出。归档在 `{doc['归档']}`，只读，没有改动。",
            f"一共 {doc['作业数']} 个作业：完成 {doc['结局']['完成']}，失败 {doc['结局']['失败']}。导出的量：{'、'.join(doc['导出的量'])}。",
            "",
            "| 产出 | 在哪 | 内容 |",
            "|---|---|---|",
            "| 标签 | `标签/标签.csv` | 一个作业一行，带作业的结局。列的来历在 `标签/标签说明.json` |",
            "| 界面场 | `界面场/<作业号>.npz` | 骨-柄界面每个节点对在每一步的相对位移、间隙、接触量、接触力，加界面三角形 |",
            "| 整体场 | `整体场/<作业号>.npz` | 网格，加每一步的位移、反力、应力、应变、应变能 |",
            "| 说明 | `说明/说明.json` | 两种场的格式，每个作业有什么、缺什么 |",
            "",
            "## 归档里本来就没有的",
            "",
        ]
        lines += [f"- {x}" for x in K.GLOBAL_DOC["归档里本来就没有的"]]
        lines += [f"- 界面场：{K.IFACE_DOC['没有的']}", "- 标签：旧表 300 列里没导出的列和原因，见 `标签/标签说明.json`", ""]
        if unreadable:
            lines += ["## 归档读不了的作业", "", "| 作业 | 原因 |", "|---|---|"]
            lines += [f"| {u['job_id']} | {u['error']} |" for u in unreadable]
            lines.append("")
        lines += ["## 每个作业", "", "| 作业 | 结局 | 模型和分析步 | 缺的 | 出的问题 |", "|---|---|---|---|---|"]
        for inv in invs:
            models = "；".join(f"{m}：{'、'.join(v['steps'])}" for m, v in inv["models"].items()) or "没有场"
            lines.append(f"| {inv['job_id']} | {inv['status']} | {models} | {'；'.join(inv['missing']) or '无'} | "
                         f"{'；'.join(inv['errors'] + inv['notes']) or '无'} |")
        return "\n".join(lines) + "\n"

    # ---- 整趟 -----------------------------------------------------------

    def run(self) -> int:
        if self.out.is_dir():  # 上一趟被结束时写了一半的文件
            for part in self.out.rglob("*.part"):
                part.unlink(missing_ok=True)
        todo = [j for j in self.plan["jobs"] if self.state.get(j) != "完成"]
        for job in todo:
            self.wait_if_paused()
            if self.stop_asked():
                return 0
            try:
                self.one(job)
            except K.Stopped:
                return 0
            self.save_state()
        if self.stop_asked():
            return 0
        counts = self.summary()
        tmp = self.dir / "done.json.part"
        tmp.write_text(json.dumps({"time": now(), "counts": counts}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.dir / "done.json")
        return 0


def main() -> int:
    state_dir = Path(sys.argv[1])
    try:
        return Run(state_dir).run()
    except Exception:
        with open(state_dir / "worker_crash.txt", "a", encoding="utf-8") as f:
            f.write(f"{now()}\n{traceback.format_exc()}\n")
        raise


if __name__ == "__main__":
    sys.exit(main())
