"""평가 세트로 에이전트의 Text-to-SQL 정확도를 측정한다.

지표: 실행 결과 일치(execution match).
  - 정답 SQL과 에이전트가 실행한 SQL을 각각 DB에서 돌려 결과를 비교한다.
  - SQL 문자열이 달라도 결과 집합이 같으면 정답으로 친다 (표준 방식).
  - 순서에 민감하지 않도록 행을 정렬해 비교하고, 수치는 소수점 2자리로 반올림한다.

사용법:
    python -m evals.run_eval                 # 전체 실행
    python -m evals.run_eval --limit 5       # 앞 5개만
    python -m evals.run_eval --check-gold    # API 호출 없이 정답 SQL만 검증
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

# Windows 콘솔에서도 한글/이모지 출력이 깨지지 않도록 UTF-8 보장
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from agent import config, db
from agent.analyst import AnalystAgent

EVAL_FILE = Path(__file__).resolve().parent / "eval_set.jsonl"


def load_cases(limit: int | None = None) -> list[dict]:
    cases = []
    with open(EVAL_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases[:limit] if limit else cases


def _normalize(rows: list[tuple]) -> list[tuple]:
    """수치 반올림 후 정렬해 비교용 정규화."""
    norm = []
    for row in rows:
        cells = []
        for v in row:
            if isinstance(v, float):
                cells.append(round(v, 2))
            else:
                cells.append(v)
        norm.append(tuple(cells))
    return sorted(norm, key=lambda r: tuple(str(c) for c in r))


def _execute(conn: sqlite3.Connection, sql: str) -> list[tuple] | None:
    try:
        return conn.execute(sql).fetchall()
    except Exception:
        return None


def check_gold() -> bool:
    """정답 SQL이 모두 오류 없이 실행되는지 확인 (API 불필요)."""
    conn = db.connect_readonly(config.DB_PATH)
    ok = True
    for case in load_cases():
        res = _execute(conn, case["gold_sql"])
        status = "OK " if res is not None else "실패"
        if res is None:
            ok = False
        print(f"  [{status}] #{case['id']:>2} {case['question']}")
    conn.close()
    print("\n정답 SQL 검증:", "모두 통과 ✅" if ok else "실패한 항목 있음 ❌")
    return ok


def run(limit: int | None = None) -> None:
    load_dotenv()
    cases = load_cases(limit)
    conn = db.connect_readonly(config.DB_PATH)

    passed = 0
    failures: list[dict] = []

    for case in cases:
        gold_rows = _execute(conn, case["gold_sql"])
        # 평가 시에는 차트 도구를 끄고 SQL 생성에 집중시킨다.
        agent = AnalystAgent(enable_chart=False)
        turn = agent.ask(case["question"])

        pred_sql = turn.executed_sql[-1] if turn.executed_sql else ""
        pred_rows = _execute(conn, pred_sql) if pred_sql else None

        match = (
            gold_rows is not None
            and pred_rows is not None
            and _normalize(gold_rows) == _normalize(pred_rows)
        )
        if match:
            passed += 1
            mark = "✅"
        else:
            mark = "❌"
            failures.append({"case": case, "pred_sql": pred_sql})

        print(f"{mark} #{case['id']:>2} [{case['category']}] {case['question']}")

    conn.close()
    total = len(cases)
    acc = passed / total * 100 if total else 0
    print(f"\n{'='*60}")
    print(f"실행 일치 정확도: {passed}/{total} = {acc:.1f}%")

    if failures:
        print(f"\n--- 틀린 항목 {len(failures)}개 ---")
        for f in failures:
            print(f"\n#{f['case']['id']} {f['case']['question']}")
            print(f"  정답 SQL : {f['case']['gold_sql']}")
            print(f"  예측 SQL : {f['pred_sql'] or '(SQL 미실행)'}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Text-to-SQL 에이전트 평가")
    ap.add_argument("--limit", type=int, default=None, help="앞에서 N개만 평가")
    ap.add_argument("--check-gold", action="store_true", help="정답 SQL만 검증(API 미사용)")
    args = ap.parse_args()

    if not config.DB_PATH.exists():
        print(f"데이터베이스가 없습니다: {config.DB_PATH}\n먼저 'python -m data.seed' 를 실행하세요.")
        raise SystemExit(1)

    if args.check_gold:
        raise SystemExit(0 if check_gold() else 1)
    run(args.limit)


if __name__ == "__main__":
    main()
