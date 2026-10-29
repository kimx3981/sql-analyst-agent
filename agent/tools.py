"""에이전트 도구 정의 + 핸들러.

도구 3종:
  - get_schema : 테이블 구조와 대표 값을 반환 (SQL 작성 전에 먼저 호출)
  - run_sql    : 읽기 전용 SELECT 실행 (가드레일 통과한 것만)
  - create_chart : 결과를 막대/선/파이 차트 PNG 로 저장
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import db

# Anthropic Messages API tool 스키마
TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_schema",
        "description": (
            "데이터베이스의 테이블 구조(DDL), 범주형 컬럼의 대표 값, 날짜 범위, "
            "매출 계산 규칙을 반환한다. SQL을 작성하기 전에 반드시 먼저 호출해 "
            "실제 컬럼명과 값을 확인하라."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "run_sql",
        "description": (
            "SQLite 데이터베이스에서 읽기 전용 SELECT(또는 WITH) 쿼리를 실행하고 "
            "결과 행을 반환한다. 데이터를 변경하는 쿼리는 거부된다. 쿼리가 실패하면 "
            "오류 메시지가 반환되니, 메시지를 읽고 쿼리를 수정해 다시 호출하라."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "실행할 단일 SELECT/WITH SQL 구문"}
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_chart",
        "description": (
            "쿼리 결과를 시각화해 PNG 파일로 저장한다. 사용자가 차트를 요청했거나 "
            "추세·비교·구성비를 보여주면 이해에 도움이 될 때 호출하라. 저장 경로를 반환한다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "chart_type": {"type": "string", "enum": ["bar", "line", "pie"]},
                "title": {"type": "string"},
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "x축(또는 파이 조각) 라벨",
                },
                "values": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "라벨에 대응하는 수치 (labels와 길이가 같아야 함)",
                },
                "x_label": {"type": "string"},
                "y_label": {"type": "string"},
            },
            "required": ["chart_type", "title", "labels", "values"],
            "additionalProperties": False,
        },
    },
]


class ToolExecutor:
    """도구 호출을 실제 동작으로 연결한다."""

    def __init__(self, db_path: Path, chart_dir: Path, max_result_rows: int):
        self.db_path = Path(db_path)
        self.chart_dir = Path(chart_dir)
        self.max_result_rows = max_result_rows
        # 평가/디버깅용: 성공적으로 실행된 쿼리 기록
        self.executed_sql: list[str] = []
        self.last_result: db.QueryResult | None = None
        self.charts: list[Path] = []

    def run(self, name: str, tool_input: dict) -> tuple[str, bool]:
        """도구를 실행하고 (결과 텍스트, is_error) 를 반환한다."""
        try:
            if name == "get_schema":
                return db.get_schema(self.db_path), False
            if name == "run_sql":
                return self._run_sql(tool_input["query"])
            if name == "create_chart":
                return self._create_chart(tool_input), False
            return f"알 수 없는 도구: {name}", True
        except db.UnsafeQueryError as e:
            return f"쿼리 거부됨(가드레일): {e}", True
        except Exception as e:  # noqa: BLE001 - 오류를 모델에게 그대로 전달해 복구 유도
            return f"{type(e).__name__}: {e}", True

    def _run_sql(self, query: str) -> tuple[str, bool]:
        result = db.run_query(self.db_path, query, self.max_result_rows)
        self.executed_sql.append(db.validate(query))
        self.last_result = result
        return result.to_text(), False

    def _create_chart(self, inp: dict) -> str:
        import matplotlib

        matplotlib.use("Agg")  # 화면 없는 환경 대비
        import matplotlib.pyplot as plt
        from matplotlib import font_manager, rcParams

        # 한글 폰트 자동 탐색 (없으면 기본 폰트 — 라벨이 □ 로 보일 수 있음)
        for cand in ("Malgun Gothic", "AppleGothic", "NanumGothic", "Noto Sans CJK KR"):
            if any(cand in f.name for f in font_manager.fontManager.ttflist):
                rcParams["font.family"] = cand
                break
        rcParams["axes.unicode_minus"] = False

        labels = [str(x) for x in inp["labels"]]
        values = [float(x) for x in inp["values"]]
        chart_type = inp["chart_type"]
        title = inp["title"]

        self.chart_dir.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(figsize=(9, 5))

        if chart_type == "bar":
            ax.bar(labels, values, color="#4C78A8")
            ax.set_xlabel(inp.get("x_label", ""))
            ax.set_ylabel(inp.get("y_label", ""))
            fig.autofmt_xdate(rotation=30)
        elif chart_type == "line":
            ax.plot(labels, values, marker="o", color="#4C78A8")
            ax.set_xlabel(inp.get("x_label", ""))
            ax.set_ylabel(inp.get("y_label", ""))
            fig.autofmt_xdate(rotation=30)
        elif chart_type == "pie":
            ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90)
            ax.axis("equal")

        ax.set_title(title)
        fig.tight_layout()

        safe_name = "".join(c if c.isalnum() else "_" for c in title)[:40] or "chart"
        n = len(self.charts) + 1
        path = self.chart_dir / f"{n:02d}_{safe_name}.png"
        fig.savefig(path, dpi=120)
        plt.close(fig)
        self.charts.append(path)
        return f"차트를 저장했습니다: {path}"
