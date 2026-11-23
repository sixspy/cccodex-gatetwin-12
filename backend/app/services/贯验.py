from app.db import 连接
from app.seed import 此刻
from app.services import 时间
from app.modules import 闸机时钟漂移 as 漂移
import json


def 跑贯验() -> dict:
    """行程账与刷卡点互证：每笔已成对行程对应两笔已成对刷卡；旁路/开腿命运自洽。

    漂移口径（漂移秒吸收）附加不变量：
    - 原始负历时行程（出站事件时<进站事件时）必须带漂移审计且历时按 0；
    - 每笔漂移审计对应行程存在、历时 0、两刷卡已成对；
    - 负历时超漂移旁路的事件不得再有任何行程（不得旁路与行程双落）。
    """
    conn = 连接()
    try:
        问题 = []
        刷卡数 = conn.execute("SELECT COUNT(*) FROM 刷卡点").fetchone()[0]
        行程 = conn.execute("SELECT * FROM 行程账 WHERE 状态='已成对'").fetchall()
        开腿数 = conn.execute("SELECT COUNT(*) FROM 开腿账 WHERE 状态='在途'").fetchone()[0]
        旁路数 = conn.execute("SELECT COUNT(*) FROM 旁路匣").fetchone()[0]

        for t in 行程:
            进 = conn.execute(
                "SELECT * FROM 刷卡点 WHERE 事件编号=?", (t["进站事件编号"],)
            ).fetchone()
            出 = conn.execute(
                "SELECT * FROM 刷卡点 WHERE 事件编号=?", (t["出站事件编号"],)
            ).fetchone()
            if not 进 or not 出:
                问题.append(f"行程{t['行程键']}缺刷卡点")
                continue
            if 进["命运"] != "已成对" or 出["命运"] != "已成对":
                问题.append(f"行程{t['行程键']}刷卡命运非已成对")
            if 进["行程键"] != t["行程键"] or 出["行程键"] != t["行程键"]:
                问题.append(f"行程{t['行程键']}刷卡行程键不一致")
            if 进["卡号"] != t["卡号"] or 出["卡号"] != t["卡号"]:
                问题.append(f"行程{t['行程键']}卡号不一致")
            if 进["方向"] != "进站" or 出["方向"] != "出站":
                问题.append(f"行程{t['行程键']}方向不配对")
            if 时间.差秒(t["进站事件时"], t["出站事件时"]) < 0:
                审 = conn.execute(
                    "SELECT * FROM 漂移审计 WHERE 行程键=?", (t["行程键"],)
                ).fetchone()
                if not 审:
                    问题.append(f"行程{t['行程键']}负历时无漂移审计")
                if t["历时秒"] != 0:
                    问题.append(f"行程{t['行程键']}负历时历时非0")

        成对刷 = conn.execute(
            "SELECT COUNT(*) FROM 刷卡点 WHERE 命运='已成对'"
        ).fetchone()[0]
        if 成对刷 != len(行程) * 2:
            问题.append(f"已成对刷卡{成对刷} ≠ 行程{len(行程)}×2")

        开腿刷 = conn.execute(
            "SELECT COUNT(*) FROM 刷卡点 WHERE 命运='已开腿'"
        ).fetchone()[0]
        if 开腿刷 != 开腿数:
            问题.append(f"已开腿刷卡{开腿刷} ≠ 在途开腿{开腿数}")

        for a in conn.execute("SELECT * FROM 漂移审计").fetchall():
            t = conn.execute(
                "SELECT * FROM 行程账 WHERE 行程键=?", (a["行程键"],)
            ).fetchone()
            if not t:
                问题.append(f"漂移审计{a['行程键']}无对应行程")
                continue
            if t["历时秒"] != 0:
                问题.append(f"漂移审计{a['行程键']}对应行程历时非0")
            if 时间.差秒(t["进站事件时"], t["出站事件时"]) >= 0:
                问题.append(f"漂移审计{a['行程键']}对应行程非负历时")
            if a["负历时秒"] != -时间.差秒(t["进站事件时"], t["出站事件时"]):
                问题.append(f"漂移审计{a['行程键']}负历时秒与行程不符")
            if a["负历时秒"] > a["漂移秒"]:
                问题.append(f"漂移审计{a['行程键']}负历时超漂移秒仍成对")

        for b in conn.execute(
            "SELECT * FROM 旁路匣 WHERE 原因=?", (漂移.旁路原因,)
        ).fetchall():
            try:
                载荷 = json.loads(b["载荷"])
            except Exception:
                载荷 = {}
            涉事件 = {b["事件编号"], 载荷.get("进站事件编号"), 载荷.get("出站事件编号")}
            for ev in 涉事件:
                if not ev:
                    continue
                刷 = conn.execute(
                    "SELECT 命运 FROM 刷卡点 WHERE 事件编号=?", (ev,)
                ).fetchone()
                if 刷 and 刷["命运"] != "已旁路":
                    问题.append(f"负历时旁路事件{ev}刷卡命运为{刷['命运']}")
                撞 = conn.execute(
                    "SELECT 行程键 FROM 行程账 WHERE 进站事件编号=? OR 出站事件编号=?",
                    (ev, ev),
                ).fetchone()
                if 撞:
                    问题.append(f"负历时旁路事件{ev}与行程{撞['行程键']}双落")

        通过 = 1 if not 问题 else 0
        说明 = "行程账与刷卡点互证通过" if 通过 else "；".join(问题)[:800]
        conn.execute(
            """INSERT INTO 行程贯验(时刻,刷卡数,行程数,开腿数,旁路数,是否通过,说明)
               VALUES (?,?,?,?,?,?,?)""",
            (此刻(), 刷卡数, len(行程), 开腿数, 旁路数, 通过, 说明),
        )
        conn.commit()
        return {
            "是否通过": bool(通过),
            "刷卡数": 刷卡数,
            "行程数": len(行程),
            "开腿数": 开腿数,
            "旁路数": 旁路数,
            "说明": 说明,
            "问题": 问题,
        }
    finally:
        conn.close()
