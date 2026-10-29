# 자연어 데이터 분석 에이전트 (Text-to-SQL + 인사이트 리포트)

자연어 질문을 받아 **SQL을 직접 작성·실행**하고, 결과를 표·차트로 보여주며, 눈에 띄는 **이상치를 설명**하는 데이터 분석 에이전트입니다. Claude(Anthropic API) + Python + 터미널 CLI로 구현했습니다.

> 예) `"2026년 2분기 매출 상위 5개 제품은?"` → 에이전트가 스키마 확인 → SQL 작성 → 실행 → 표/차트 + 분석 리포트

## 핵심 특징

- **도구 기반 에이전트 루프** — `get_schema`, `run_sql`, `create_chart` 3개 도구를 모델이 스스로 선택·호출 (`agent/analyst.py`).
- **읽기 전용 가드레일** — 신뢰할 수 없는 생성 SQL을 2중으로 방어 (`agent/db.py`):
  1. 정적 검사: `SELECT`/`WITH` 단일 구문만 허용, `INSERT/UPDATE/DELETE/DROP/...` 차단, 다중 구문 차단.
  2. 물리적 방어: SQLite를 `mode=ro`(읽기 전용)로 열어 쓰기를 원천 차단.
- **SQL 오류 자동 복구 루프** — 쿼리가 실패하면 오류 메시지를 모델에 되돌려 스스로 수정·재시도 (기본 3회).
- **평가 세트 + 정확도 측정** — 질문·정답 SQL 30개(`evals/eval_set.jsonl`)에 대해 **실행 결과 일치(execution match)** 정확도를 측정 (`evals/run_eval.py`).
- **재현 가능한 합성 데이터** — 고정 시드로 생성한 가상 이커머스 판매 데이터(회사 기밀 데이터 미사용). 이상치도 의도적으로 주입.

## 데이터 스키마

| 테이블 | 주요 컬럼 |
|---|---|
| `customers` | customer_id, name, region, signup_date |
| `products` | product_id, product_name, category, price |
| `orders` | order_id, customer_id, order_date, status |
| `order_items` | order_item_id, order_id, product_id, quantity, unit_price |

- 기간: 2025-01-01 ~ 2026-09-30, 주문 약 8,000건
- 매출 규칙: `status='completed'` 주문의 `quantity * unit_price` 합계
- 주입된 이상치: 2026년 3분기 `프리미엄 노트북` 판매량 급증

## 빠른 시작

```bash
# 1) 설치
pip install -r requirements.txt

# 2) API 키 설정
cp .env.example .env    # .env 를 열어 ANTHROPIC_API_KEY 입력
#   (또는 환경변수로:  set ANTHROPIC_API_KEY=sk-ant-...  / export ANTHROPIC_API_KEY=...)

# 3) 합성 데이터 생성
python -m data.seed

# 4) 대화형 CLI 실행
python main.py
```

CLI 명령: `/schema` 스키마 보기 · `/sql` 직전 질문의 SQL 보기 · `/exit` 종료

## 평가 실행

```bash
# 정답 SQL이 모두 정상 실행되는지 먼저 확인 (API 호출 없음, 무료)
python -m evals.run_eval --check-gold

# 에이전트 정확도 측정 (API 호출 — 비용 발생)
python -m evals.run_eval            # 전체 30문항
python -m evals.run_eval --limit 5  # 앞 5문항만
```

측정 방식은 **실행 결과 일치**입니다. 정답 SQL과 에이전트가 생성한 SQL을 각각 DB에서 실행해 결과 집합을 비교하므로, SQL 표현이 달라도 결과가 같으면 정답으로 처리합니다. 평가 세트는 `evals/eval_set.jsonl`에 한 줄씩 `{질문, 정답 SQL}` 형태로 되어 있어 쉽게 추가·확장할 수 있습니다.

## 프로젝트 구조

```
sql-analyst-agent/
├── main.py                 # 진입점
├── agent/
│   ├── config.py           # 모델·경로·상한 등 설정
│   ├── db.py               # 읽기 전용 가드레일 + 쿼리 실행 + 스키마
│   ├── tools.py            # 도구 스키마 + 실행 핸들러
│   ├── analyst.py          # 에이전트 루프 (NL→SQL→실행→복구→리포트)
│   └── cli.py              # 터미널 채팅 UI
├── data/
│   └── seed.py             # 합성 이커머스 데이터 생성
├── evals/
│   ├── eval_set.jsonl      # 질문·정답 SQL 30문항
│   └── run_eval.py         # 실행 일치 정확도 측정
└── requirements.txt
```

## 설정 (환경변수)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **필수.** Anthropic API 키 |
| `AGENT_MODEL` | `claude-opus-5-5` | 사용할 모델 |
| `AGENT_EFFORT` | `medium` | 추론 강도 (low~max) |
| `AGENT_MAX_SQL_RETRIES` | `3` | SQL 오류 자동 복구 최대 횟수 |
| `AGENT_TODAY` | (오늘) | 상대 날짜("지난 분기") 해석 기준일 고정 |

## 동작 원리 (한 번의 질문)

1. 모델이 `get_schema`로 실제 컬럼명·범주 값·매출 규칙을 확인합니다.
2. `run_sql`로 읽기 전용 SELECT를 실행합니다. 오류가 나면 메시지를 보고 스스로 고쳐 재시도합니다.
3. 필요하면 `create_chart`로 PNG 차트를 `charts/`에 저장합니다.
4. 핵심 답변 + 이상치 설명 + 실행한 SQL을 한국어 리포트로 정리합니다.
