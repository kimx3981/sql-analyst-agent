"""에이전트 설정값."""

from __future__ import annotations

import os
from pathlib import Path

# 프로젝트 루트
ROOT = Path(__file__).resolve().parent.parent

# 기본 모델: Claude Opus 5.5 (최신 기본 모델)
# 필요하면 AGENT_MODEL 환경변수로 교체 (예: claude-sonnet-5-5, claude-haiku-5-5)
MODEL = os.environ.get("AGENT_MODEL", "claude-opus-5-5")

# 응답 토큰 상한
MAX_TOKENS = int(os.environ.get("AGENT_MAX_TOKENS", "8000"))

# 추론 강도: low | medium | high | xhigh | max
EFFORT = os.environ.get("AGENT_EFFORT", "medium")

# 데이터베이스 경로
DB_PATH = Path(os.environ.get("AGENT_DB_PATH", ROOT / "data" / "sales.db"))

# 차트 저장 폴더
CHART_DIR = Path(os.environ.get("AGENT_CHART_DIR", ROOT / "charts"))

# SQL 결과에서 에이전트에게 돌려줄 최대 행 수 (컨텍스트 보호)
MAX_RESULT_ROWS = int(os.environ.get("AGENT_MAX_RESULT_ROWS", "200"))

# SQL 오류 시 에이전트가 스스로 고쳐 재시도할 최대 횟수
MAX_SQL_RETRIES = int(os.environ.get("AGENT_MAX_SQL_RETRIES", "3"))

# 오늘 날짜 ("지난 분기" 같은 상대 표현 해석용). 테스트 재현을 위해 고정 가능.
TODAY = os.environ.get("AGENT_TODAY", "")  # 빈 값이면 실제 오늘 날짜 사용
