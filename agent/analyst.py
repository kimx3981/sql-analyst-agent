"""Text-to-SQL 분석 에이전트의 핵심 루프."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import anthropic

from . import config
from .tools import TOOLS, ToolExecutor


def _today() -> str:
    return config.TODAY or date.today().isoformat()


def build_system_prompt() -> str:
    return f"""\
당신은 사내 BI 데이터를 분석하는 시니어 데이터 분석가 에이전트입니다.
오늘 날짜는 {_today()} 입니다. "지난 분기", "최근 3개월" 같은 상대 표현은 이 날짜를 기준으로 해석하세요.

작업 절차:
1. 처음 보는 질문이면 먼저 get_schema 를 호출해 테이블 구조와 실제 컬럼명, \
범주형 값(지역/카테고리/상태), 날짜 범위, 매출 계산 규칙을 확인하세요. 컬럼명을 추측하지 마세요.
2. run_sql 로 읽기 전용 SELECT 쿼리를 실행하세요.
   - SQLite 문법을 사용하세요 (날짜는 'YYYY-MM-DD' 문자열 비교, strftime 사용 가능).
   - 쿼리가 오류를 반환하면 메시지를 읽고 원인을 고쳐 다시 실행하세요. 최대 {config.MAX_SQL_RETRIES}회까지 스스로 복구하세요.
   - 큰 테이블은 적절히 집계/LIMIT 하세요.
3. 비교·추세·구성비를 보여줄 때는 create_chart 로 시각화하세요.
4. 마지막에 한국어로 분석 리포트를 작성하세요. 포함할 것:
   - 핵심 답변 (필요하면 표 형태로)
   - 눈에 띄는 이상치나 패턴이 있으면 설명 (예: 특정 제품/지역의 급증·급감)
   - 실행한 SQL을 코드블록으로 함께 제시 (재현성)

정직하게 보고하세요. 데이터로 확인되지 않은 내용은 단정하지 마세요."""


@dataclass
class Turn:
    """한 번의 질문에 대한 처리 결과(평가·디버깅용)."""

    answer: str
    executed_sql: list[str] = field(default_factory=list)
    charts: list = field(default_factory=list)
    stop_reason: str = ""


class AnalystAgent:
    def __init__(self, *, enable_chart: bool = True, verbose_callback=None):
        self.client = anthropic.Anthropic()
        self.enable_chart = enable_chart
        self.messages: list[dict] = []
        self.system = build_system_prompt()
        # verbose_callback(event:str, detail:str) 로 진행 상황을 외부(CLI)에 알린다.
        self._notify = verbose_callback or (lambda event, detail: None)

    def _tools(self) -> list[dict]:
        if self.enable_chart:
            return TOOLS
        return [t for t in TOOLS if t["name"] != "create_chart"]

    def ask(self, question: str) -> Turn:
        """질문 하나를 처리하고 최종 답변 + 실행된 SQL을 반환한다."""
        self.messages.append({"role": "user", "content": question})
        executor = ToolExecutor(config.DB_PATH, config.CHART_DIR, config.MAX_RESULT_ROWS)

        # 한 질문에서 도구 호출이 무한 반복되지 않도록 상한을 둔다.
        max_iterations = 2 + config.MAX_SQL_RETRIES * 2 + 8
        stop_reason = ""

        for _ in range(max_iterations):
            response = self.client.messages.create(
                model=config.MODEL,
                max_tokens=config.MAX_TOKENS,
                system=self.system,
                messages=self.messages,
                tools=self._tools(),
                thinking={"type": "adaptive"},
                output_config={"effort": config.EFFORT},
            )
            stop_reason = response.stop_reason
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                break

            # 이 어시스턴트 턴의 모든 tool_use 블록을 처리해 하나의 user 메시지로 응답
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                self._notify("tool", f"{block.name} {_short_input(block.input)}")
                output, is_error = executor.run(block.name, block.input)
                if is_error:
                    self._notify("error", output)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                        "is_error": is_error,
                    }
                )
            self.messages.append({"role": "user", "content": tool_results})
        else:
            # 반복 상한 도달
            self._notify("error", "도구 호출 반복 상한에 도달했습니다.")

        answer = _final_text(self.messages[-1]["content"]) if self.messages else ""
        return Turn(
            answer=answer,
            executed_sql=executor.executed_sql,
            charts=executor.charts,
            stop_reason=stop_reason,
        )


def _short_input(inp: dict) -> str:
    if "query" in inp:
        q = " ".join(str(inp["query"]).split())
        return q[:80] + ("…" if len(q) > 80 else "")
    if "title" in inp:
        return str(inp["title"])
    return ""


def _final_text(content) -> str:
    if isinstance(content, str):
        return content
    parts = [b.text for b in content if getattr(b, "type", None) == "text"]
    return "\n".join(parts).strip()
