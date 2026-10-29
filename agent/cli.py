"""터미널 채팅 인터페이스."""

from __future__ import annotations

import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from . import config
from .analyst import AnalystAgent

console = Console()

BANNER = """[bold cyan]자연어 데이터 분석 에이전트[/bold cyan]
질문을 한국어로 입력하세요. 예) "2026년 2분기 지역별 매출 상위 5개 제품은?"
명령: [dim]/schema[/dim] 스키마 보기 · [dim]/sql[/dim] 직전 질문의 SQL 다시 보기 · [dim]/exit[/dim] 종료"""


def _on_event(event: str, detail: str) -> None:
    if event == "tool":
        console.print(f"  [dim]→ {detail}[/dim]")
    elif event == "error":
        console.print(f"  [yellow]⚠ {detail}[/yellow]")


def _check_ready() -> bool:
    if not config.DB_PATH.exists():
        console.print(
            f"[red]데이터베이스가 없습니다:[/red] {config.DB_PATH}\n"
            "먼저 데이터를 생성하세요:  [bold]python -m data.seed[/bold]"
        )
        return False
    return True


def main() -> int:
    load_dotenv()
    if not _check_ready():
        return 1

    console.print(Panel(BANNER, border_style="cyan"))

    try:
        agent = AnalystAgent(verbose_callback=_on_event)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]에이전트 초기화 실패:[/red] {e}")
        console.print("[dim]ANTHROPIC_API_KEY 환경변수가 설정되어 있는지 확인하세요.[/dim]")
        return 1

    last: list[str] = []
    while True:
        try:
            q = console.input("\n[bold green]질문›[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n종료합니다.")
            return 0

        if not q:
            continue
        if q in ("/exit", "/quit", "exit", "quit"):
            console.print("종료합니다.")
            return 0
        if q == "/schema":
            from . import db

            console.print(Panel(db.get_schema(config.DB_PATH), title="스키마", border_style="blue"))
            continue
        if q == "/sql":
            if last:
                console.print(Panel("\n\n".join(last), title="직전 실행 SQL", border_style="blue"))
            else:
                console.print("[dim]아직 실행된 SQL이 없습니다.[/dim]")
            continue

        try:
            with console.status("[cyan]분석 중…[/cyan]", spinner="dots"):
                turn = agent.ask(q)
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]오류:[/red] {e}")
            continue

        last = turn.executed_sql
        console.print()
        console.print(Markdown(turn.answer or "(응답 없음)"))
        if turn.charts:
            for c in turn.charts:
                console.print(f"[green]📊 차트 저장됨:[/green] {c}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
