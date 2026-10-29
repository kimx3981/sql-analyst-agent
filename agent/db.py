"""데이터베이스 접근 + 읽기 전용 SQL 가드레일.

에이전트가 생성한 SQL은 신뢰할 수 없다고 가정한다. 두 겹으로 방어한다.
  1) 정적 검사: SELECT/WITH 로 시작하는 단일 구문만 허용, 위험 키워드 차단.
  2) 물리적 방어: SQLite 를 read-only(mode=ro) 로 열어 쓰기를 원천 차단.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

# 읽기 전용이라도 명시적으로 막아 의도를 분명히 한다.
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|"
    r"ATTACH|DETACH|PRAGMA|VACUUM|REINDEX|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


class UnsafeQueryError(ValueError):
    """가드레일에 걸린 쿼리."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool  # 행 수 제한으로 잘렸는지 여부

    def to_text(self, max_show: int = 50) -> str:
        """에이전트에게 돌려줄 텍스트 표현."""
        if not self.rows:
            return "(결과 행 없음)"
        head = " | ".join(self.columns)
        sep = "-+-".join("-" * len(c) for c in self.columns)
        body = "\n".join(
            " | ".join("" if v is None else str(v) for v in row)
            for row in self.rows[:max_show]
        )
        out = f"{head}\n{sep}\n{body}"
        note = []
        if len(self.rows) > max_show:
            note.append(f"(상위 {max_show}/{len(self.rows)}행만 표시)")
        if self.truncated:
            note.append("(행 수 제한으로 결과가 잘렸을 수 있음)")
        if note:
            out += "\n" + " ".join(note)
        return out


def _strip_sql(query: str) -> str:
    """주석을 제거하고 공백을 정리한다."""
    # 블록 주석 /* ... */ 제거
    q = re.sub(r"/\*.*?\*/", " ", query, flags=re.DOTALL)
    # 라인 주석 -- ... 제거
    q = re.sub(r"--[^\n]*", " ", q)
    return q.strip().rstrip(";").strip()


def validate(query: str) -> str:
    """정적 가드레일. 통과하면 정리된 쿼리를 반환, 아니면 예외."""
    q = _strip_sql(query)
    if not q:
        raise UnsafeQueryError("빈 쿼리입니다.")

    # 다중 구문 차단 (문자열/주석 제거 후 세미콜론이 남으면 거부)
    if ";" in q:
        raise UnsafeQueryError("여러 SQL 구문은 허용되지 않습니다. 하나의 SELECT만 보내세요.")

    first = q.split(None, 1)[0].upper()
    if first not in ("SELECT", "WITH"):
        raise UnsafeQueryError("읽기 전용 에이전트입니다. SELECT 또는 WITH 쿼리만 실행할 수 있습니다.")

    if _FORBIDDEN.search(q):
        raise UnsafeQueryError("데이터를 변경하거나 스키마를 조작하는 키워드는 사용할 수 없습니다.")

    return q


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    """read-only 모드로 연결. 쓰기 시도는 SQLite 레벨에서 거부된다."""
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def run_query(db_path: Path, query: str, max_rows: int) -> QueryResult:
    """가드레일을 통과한 SELECT 를 read-only 로 실행한다."""
    safe = validate(query)
    conn = connect_readonly(db_path)
    try:
        cur = conn.cursor()
        cur.execute(safe)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(max_rows + 1)
        truncated = len(rows) > max_rows
        return QueryResult(columns=columns, rows=rows[:max_rows], truncated=truncated)
    finally:
        conn.close()


def get_schema(db_path: Path) -> str:
    """사람이 읽기 좋은 스키마 설명 + 간단한 통계."""
    conn = connect_readonly(db_path)
    try:
        cur = conn.cursor()
        ddl_rows = cur.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL ORDER BY name"
        ).fetchall()
        ddl = "\n\n".join(r[0] for r in ddl_rows)

        # 범주형 컬럼의 대표 값들
        regions = [r[0] for r in cur.execute("SELECT DISTINCT region FROM customers ORDER BY region")]
        cats = [r[0] for r in cur.execute("SELECT DISTINCT category FROM products ORDER BY category")]
        statuses = [r[0] for r in cur.execute("SELECT DISTINCT status FROM orders ORDER BY status")]
        (min_d,) = cur.execute("SELECT MIN(order_date) FROM orders").fetchone()
        (max_d,) = cur.execute("SELECT MAX(order_date) FROM orders").fetchone()
    finally:
        conn.close()

    return (
        f"{ddl}\n\n"
        "-- 참고 --\n"
        f"customers.region 값: {', '.join(regions)}\n"
        f"products.category 값: {', '.join(cats)}\n"
        f"orders.status 값: {', '.join(statuses)}\n"
        f"orders.order_date 범위: {min_d} ~ {max_d}\n"
        "매출(revenue) 규칙: status='completed' 인 주문의 "
        "order_items.quantity * order_items.unit_price 합계로 계산한다.\n"
        "order_items.unit_price 는 주문 시점 단가이며 products.price 와 같다."
    )
