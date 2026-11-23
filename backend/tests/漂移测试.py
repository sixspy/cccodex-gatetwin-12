#!/usr/bin/env python3
"""闸机时钟漂移：口径夹具 + 裁决并发测试（服务层，不依赖 fastapi）。

覆盖：
1. 正历时成对（happy path 口径不变）；
2. 小幅负历时（早 10 秒 ≤ 漂移秒 30）→ 乙口径成对吸收：有行程、历时 0、带漂移审计；
   甲口径（任何负历时即旁路）下应无行程——两口径靠 裁决() 的 口径/命运 字段区分；
3. 超大负历时（早 2 小时 > 漂移秒）→ 旁路无行程（两口径均旁路）；
4. 裁决并发：同腿被「窗内出站」与「超窗出站」并发争抢——不得旁路与行程双落；
   同事件并发装载——幂等，不重落。
"""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

_根 = Path(__file__).resolve().parents[2]
os.environ["数据目录"] = tempfile.mkdtemp(prefix="gatetwin-drift-")
os.environ["夹具目录"] = str(_根 / "fixtures")
sys.path.insert(0, str(_根 / "backend"))

from app import seed  # noqa: E402
from app.db import 连接  # noqa: E402
from app.services import 装载, 贯验  # noqa: E402
from app.modules import 闸机时钟漂移 as 漂移  # noqa: E402

失败 = []


def 查(条件: bool, 名目: str) -> None:
    print(("  ✓ " if 条件 else "  ✗ ") + 名目)
    if not 条件:
        失败.append(名目)


def 装(事件, 批次="批-测"):
    return 装载.装一批({"批次编号": 批次, "事件": 事件})


def 一行(sql, 参=()):
    conn = 连接()
    try:
        return conn.execute(sql, 参).fetchone()
    finally:
        conn.close()


def 全部(sql, 参=()):
    conn = 连接()
    try:
        return conn.execute(sql, 参).fetchall()
    finally:
        conn.close()


seed.初始化库()

print("== 1. 只读裁决口径 ==")
进 = "2026-11-22T12:00:00Z"
c = 漂移.裁决(进, "2026-11-22T12:00:10Z", 30)
查(c["命运"] == 漂移.正历时成对 and c["valid"] is True and c["负历时秒"] == 0, "正历时→正历时成对 valid")
c = 漂移.裁决(进, "2026-11-22T11:59:50Z", 30)
查(c["命运"] == 漂移.成对吸收 and c["valid"] is True and c["负历时秒"] == 10, "早10秒≤漂移30→成对吸收 valid")
查(c["口径"] == "漂移秒吸收" and c["漂移秒"] == 30, "裁决带口径与漂移秒")
# 口径分叉点：同一输入在甲口径（任何负历时即旁路）下无行程；乙口径下有行程
查(漂移.裁决(进, "2026-11-22T11:59:50Z", 30)["命运"] != 漂移.旁路, "乙口径下早10秒有行程（甲口径则无，可区分）")
c = 漂移.裁决(进, "2026-11-22T11:59:29Z", 30)
查(c["命运"] == 漂移.旁路 and c["valid"] is False and c["负历时秒"] == 31, "早31秒>漂移30→旁路 invalid")
c = 漂移.裁决(进, "2026-11-22T10:00:00Z", 30)
查(c["命运"] == 漂移.旁路 and c["负历时秒"] == 7200, "早2小时→旁路")
c = 漂移.裁决(进, "不是时间", 30)
查(c["命运"] == 漂移.不可裁决 and c["valid"] is False, "坏时间→不可裁决")

print("== 2. 正历时成对（happy path 不变）==")
r = 装([
    {"事件编号": "p1", "卡号": "卡P", "站点键": "站A", "方向": "进站", "事件时": "2026-11-22T08:00:00Z", "处理时": "2026-11-22T08:00:01Z"},
    {"事件编号": "p2", "卡号": "卡P", "站点键": "站B", "方向": "出站", "事件时": "2026-11-22T08:25:00Z", "处理时": "2026-11-22T08:25:02Z"},
])
查(r["成对"] == 1 and r["漂移吸收"] == 0, "正历时成对 1 笔")
t = 一行("SELECT * FROM 行程账 WHERE 卡号='卡P'")
查(t is not None and t["历时秒"] == 1500, "正历时行程历时=1500 秒")
查(一行("SELECT COUNT(*) c FROM 漂移审计")["c"] == 0, "正历时不写漂移审计")

print("== 3. 小幅负历时 → 成对吸收带审计 ==")
r = 装载.装一批(json.loads((Path(os.environ["夹具目录"]) / "漂移吸收样例.json").read_text(encoding="utf-8")))
查(r["成对"] == 1 and r["漂移吸收"] == 1 and r["旁路"] == 0, "吸收样例成对 1、漂移吸收 1、旁路 0")
t = 一行("SELECT * FROM 行程账 WHERE 卡号='卡55'")
查(t is not None and t["历时秒"] == 0, "吸收行程存在且历时按 0")
查(t["出站事件时"] < t["进站事件时"], "吸收行程原始时刻仍为负历时（出站早于进站）")
a = 一行("SELECT * FROM 漂移审计 WHERE 卡号='卡55'")
查(a is not None and a["负历时秒"] == 10 and a["漂移秒"] == 30 and a["行程键"] == t["行程键"], "漂移审计：负历时10 漂移30 挂行程键")
腿 = 一行("SELECT * FROM 开腿账 WHERE 卡号='卡55'")
查(腿["状态"] == "已成对", "开腿同票已成对")
刷 = 全部("SELECT * FROM 刷卡点 WHERE 卡号='卡55' ORDER BY 事件编号")
查(all(s["命运"] == "已成对" and s["行程键"] == t["行程键"] for s in 刷), "进出站刷卡同票已成对带行程键")

print("== 4. 超大负历时 → 拒配旁路（两口径均旁路）==")
r = 装载.装一批(json.loads((Path(os.environ["夹具目录"]) / "漂移超界样例.json").read_text(encoding="utf-8")))
查(r["成对"] == 0 and r["旁路"] == 1, "超界样例无成对、旁路 1")
查(一行("SELECT * FROM 行程账 WHERE 卡号='卡56'") is None, "超界无行程")
腿 = 一行("SELECT * FROM 开腿账 WHERE 卡号='卡56'")
查(腿["状态"] == "已旁路", "开腿同票已旁路")
刷 = 全部("SELECT * FROM 刷卡点 WHERE 卡号='卡56' ORDER BY 事件编号")
查(all(s["命运"] == "已旁路" for s in 刷), "进出站刷卡同票已旁路")
b = 一行("SELECT * FROM 旁路匣 WHERE 原因=? AND 卡号='卡56'", (漂移.旁路原因,))
查(b is not None, "旁路匣有负历时超漂移记录")
载 = json.loads(b["载荷"])
查(载["负历时秒"] == 7200 and 载["漂移秒"] == 30 and 载["口径"] == "漂移秒吸收", "旁路载荷带裁决快照")

print("== 5. 贯验（含漂移不变量）==")
v = 贯验.跑贯验()
查(v["是否通过"], f"贯验通过：{v['说明']}")

print("== 6. 裁决并发：同腿窗内/超窗争抢，不得双落 ==")


def 并发抢腿(轮: int) -> None:
    卡 = f"卡C{轮}"
    装([{"事件编号": f"c{轮}-in", "卡号": 卡, "站点键": "站A", "方向": "进站",
         "事件时": "2026-11-22T12:00:00Z", "处理时": "2026-11-22T12:00:01Z"}], f"批-并发{轮}-进")
    闸 = threading.Barrier(9)
    错 = []

    def 打(事件编号, 出站时):
        闸.wait()
        体 = {"事件编号": 事件编号, "卡号": 卡, "站点键": "站B", "方向": "出站",
              "事件时": 出站时, "处理时": "2026-11-22T12:00:09Z"}
        for _ in range(4):  # 冲突整批回滚后重试，终态必须收敛
            try:
                装([体], f"批-并发{轮}-{事件编号}")
                return
            except Exception as e:  # 裁决冲突 → 重试
                错.append(str(e))
                time.sleep(0.05)
        装([体], f"批-并发{轮}-{事件编号}-终")

    线程 = []
    for i in range(4):
        线程.append(threading.Thread(target=打, args=(f"c{轮}-w{i}", "2026-11-22T11:59:50Z")))  # 窗内→吸收
        线程.append(threading.Thread(target=打, args=(f"c{轮}-x{i}", "2026-11-22T10:00:00Z")))  # 超窗→旁路
    [t.start() for t in 线程]
    闸.wait()
    [t.join() for t in 线程]

    行程 = 全部("SELECT * FROM 行程账 WHERE 卡号=?", (卡,))
    超漂 = 全部("SELECT * FROM 旁路匣 WHERE 卡号=? AND 原因=?", (卡, 漂移.旁路原因))
    查(len(行程) <= 1, f"轮{轮}：行程至多 1 笔（实得 {len(行程)}）")
    查(len(超漂) <= 1, f"轮{轮}：负历时超漂移旁路至多 1 笔（实得 {len(超漂)}）")
    查(not (行程 and 超漂), f"轮{轮}：不得旁路与行程双落")
    腿 = 一行("SELECT * FROM 开腿账 WHERE 卡号=?", (卡,))
    查(腿["状态"] in ("已成对", "已旁路"), f"轮{轮}：开腿终态 {腿['状态']}")
    未完 = [s for s in 全部("SELECT * FROM 刷卡点 WHERE 卡号=? AND 方向='出站'", (卡,))
            if s["命运"] not in ("已成对", "已旁路")]
    查(not 未完, f"轮{轮}：全部出站事件命运已终态")
    if 行程:
        查(行程[0]["历时秒"] == 0 and 一行("SELECT * FROM 漂移审计 WHERE 行程键=?", (行程[0]["行程键"],)) is not None,
           f"轮{轮}：若成对则为吸收行程且带审计")


for 轮 in range(5):
    并发抢腿(轮)

print("== 7. 同事件并发装载：幂等不重落 ==")
装([{"事件编号": "m1", "卡号": "卡M", "站点键": "站A", "方向": "进站",
     "事件时": "2026-11-22T12:00:00Z", "处理时": "2026-11-22T12:00:01Z"}], "批-幂等进")
闸 = threading.Barrier(7)  # 6 工作线程 + 主线程


def 灌同事件(i):
    闸.wait()
    for _ in range(4):
        try:
            return 装([{"事件编号": "m2", "卡号": "卡M", "站点键": "站B", "方向": "出站",
                        "事件时": "2026-11-22T11:59:50Z", "处理时": "2026-11-22T12:00:09Z"}], f"批-幂等{i}")
        except Exception:
            time.sleep(0.05)


线程 = [threading.Thread(target=灌同事件, args=(i,)) for i in range(6)]
[t.start() for t in 线程]
闸.wait()
[t.join() for t in 线程]
查(一行("SELECT COUNT(*) c FROM 刷卡点 WHERE 事件编号='m2'")["c"] == 1, "同事件并发后刷卡点恰 1 行")
查(一行("SELECT COUNT(*) c FROM 行程账 WHERE 卡号='卡M'")["c"] == 1, "同事件并发后行程恰 1 笔")
查(一行("SELECT COUNT(*) c FROM 漂移审计 WHERE 卡号='卡M'")["c"] == 1, "同事件并发后漂移审计恰 1 笔")

print("== 8. 终态贯验 ==")
v = 贯验.跑贯验()
查(v["是否通过"], f"并发后贯验通过：{v['说明']}")

print()
if 失败:
    print(f"失败 {len(失败)} 项：")
    for f in 失败:
        print(" -", f)
    sys.exit(1)
print(f"全部通过（库：{os.environ['数据目录']}）")
