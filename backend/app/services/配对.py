import json
from app.seed import 此刻
from app.services import 时间


class 配对冲突(Exception):
    """开腿在落账前已被并发事务改写——与写库同成败，整批回滚。"""


def 占位开腿(conn, 开腿键: str, 新状态: str, 处理时: str) -> bool:
    """在途→终态的原子占位：并发下只有一方能占位成功，另一方不得再落账。"""
    cur = conn.execute(
        "UPDATE 开腿账 SET 状态=?, 更新处理时=? WHERE 开腿键=? AND 状态='在途'",
        (新状态, 处理时, 开腿键),
    )
    return cur.rowcount == 1


def 扫缺腿超时(conn, 最大行程秒: int, 水位事件时: str, 处理时: str) -> int:
    """水位推进后，把超最大行程秒仍在途的开腿打进旁路。"""
    n = 0
    rows = list(conn.execute("SELECT * FROM 开腿账 WHERE 状态='在途'"))
    for leg in rows:
        if 时间.差秒(leg["进站事件时"], 水位事件时) < 最大行程秒:
            continue
        if not 占位开腿(conn, leg["开腿键"], "已旁路", 处理时):
            continue  # 已被并发成对/旁路，不得双落
        conn.execute(
            "UPDATE 刷卡点 SET 命运=? WHERE 事件编号=?",
            ("已旁路", leg["进站事件编号"]),
        )
        conn.execute(
            "INSERT INTO 旁路匣(原因, 卡号, 事件编号, 载荷, 时刻) VALUES (?,?,?,?,?)",
            (
                "缺腿超时",
                leg["卡号"],
                leg["进站事件编号"],
                json.dumps(
                    {
                        "开腿键": leg["开腿键"],
                        "进站事件时": leg["进站事件时"],
                        "水位": 水位事件时,
                        "最大行程秒": 最大行程秒,
                    },
                    ensure_ascii=False,
                ),
                处理时,
            ),
        )
        n += 1
    return n


def 成对写出站(conn, 开腿, 出站事件编号: str, 出站站点键: str, 出站事件时: str, 处理时: str) -> str:
    行程键 = f"行-{开腿['进站事件编号']}-{出站事件编号}"
    历时 = max(0, 时间.差秒(开腿["进站事件时"], 出站事件时))
    if not 占位开腿(conn, 开腿["开腿键"], "已成对", 处理时):
        raise 配对冲突(f"开腿{开腿['开腿键']}已被并发裁决")
    conn.execute(
        """INSERT INTO 行程账(行程键,卡号,进站事件编号,出站事件编号,进站站点键,出站站点键,
           进站事件时,出站事件时,历时秒,状态,版本,处理时)
           VALUES (?,?,?,?,?,?,?,?,?,'已成对',1,?)""",
        (
            行程键,
            开腿["卡号"],
            开腿["进站事件编号"],
            出站事件编号,
            开腿["进站站点键"],
            出站站点键,
            开腿["进站事件时"],
            出站事件时,
            历时,
            处理时,
        ),
    )
    conn.execute(
        "UPDATE 刷卡点 SET 命运=?, 行程键=? WHERE 事件编号 IN (?,?)",
        ("已成对", 行程键, 开腿["进站事件编号"], 出站事件编号),
    )
    return 行程键
