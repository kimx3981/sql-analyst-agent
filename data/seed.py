"""합성 이커머스 판매 데이터를 SQLite DB로 생성한다.

회사 기밀 데이터 대신 가상의 판매 데이터를 사용한다. 고정 시드를 쓰므로
매번 동일한 데이터가 생성되어 평가(eval) 결과가 재현 가능하다.

스키마
------
customers(customer_id, name, region, signup_date)
products(product_id, product_name, category, price)
orders(order_id, customer_id, order_date, status)
order_items(order_item_id, order_id, product_id, quantity, unit_price)

매출(revenue) 규칙: status='completed' 인 주문의
order_items.quantity * order_items.unit_price 합계.
"""

from __future__ import annotations

import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

# Windows 콘솔(cp1252)에서도 한글이 깨지지 않도록 UTF-8 출력 보장
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

SEED = 42
DB_PATH = Path(__file__).resolve().parent / "sales.db"

REGIONS = ["서울", "경기", "부산", "인천", "대구", "대전", "광주", "울산"]

# (카테고리, [(제품명, 가격), ...])
CATALOG = {
    "전자제품": [
        ("프리미엄 노트북", 1890000),
        ("무선 이어폰", 219000),
        ("4K 모니터", 450000),
        ("기계식 키보드", 129000),
        ("스마트워치", 329000),
    ],
    "의류": [
        ("기본 티셔츠", 19900),
        ("데님 팬츠", 59000),
        ("패딩 점퍼", 189000),
        ("운동화", 89000),
        ("가죽 벨트", 39000),
    ],
    "식품": [
        ("원두커피 1kg", 24000),
        ("유기농 꿀", 32000),
        ("견과류 세트", 28000),
        ("프리미엄 한우", 98000),
        ("생수 24병", 12000),
    ],
    "가구": [
        ("원목 책상", 259000),
        ("인체공학 의자", 329000),
        ("3단 선반", 79000),
        ("퀸 침대 프레임", 420000),
        ("소파 2인용", 650000),
    ],
    "뷰티": [
        ("수분 크림", 38000),
        ("선크림 SPF50", 22000),
        ("립스틱", 29000),
        ("향수 50ml", 120000),
        ("클렌징 폼", 15000),
    ],
    "스포츠": [
        ("요가 매트", 35000),
        ("덤벨 세트", 89000),
        ("자전거 헬멧", 65000),
        ("등산 배낭", 149000),
        ("테니스 라켓", 185000),
    ],
    "도서": [
        ("파이썬 입문서", 32000),
        ("데이터 분석 실무", 38000),
        ("소설 베스트셀러", 15800),
        ("경제 교양서", 18000),
        ("어린이 그림책", 12000),
    ],
    "완구": [
        ("블록 조립 세트", 59000),
        ("보드게임", 42000),
        ("인형", 25000),
        ("RC 자동차", 78000),
        ("퍼즐 1000피스", 19000),
    ],
}

STATUSES = ["completed", "completed", "completed", "completed", "cancelled", "returned", "pending"]

START = date(2025, 1, 1)
END = date(2026, 9, 30)


def _random_date(rng: random.Random) -> date:
    span = (END - START).days
    return START + timedelta(days=rng.randint(0, span))


def build(db_path: Path = DB_PATH) -> Path:
    rng = random.Random(SEED)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            region      TEXT NOT NULL,
            signup_date TEXT NOT NULL
        );
        CREATE TABLE products (
            product_id   INTEGER PRIMARY KEY,
            product_name TEXT NOT NULL,
            category     TEXT NOT NULL,
            price        REAL NOT NULL
        );
        CREATE TABLE orders (
            order_id    INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
            order_date  TEXT NOT NULL,
            status      TEXT NOT NULL
        );
        CREATE TABLE order_items (
            order_item_id INTEGER PRIMARY KEY,
            order_id      INTEGER NOT NULL REFERENCES orders(order_id),
            product_id    INTEGER NOT NULL REFERENCES products(product_id),
            quantity      INTEGER NOT NULL,
            unit_price    REAL NOT NULL
        );
        """
    )

    # products
    products: list[tuple[int, str, str, float]] = []
    pid = 1
    for category, items in CATALOG.items():
        for name, price in items:
            products.append((pid, name, category, float(price)))
            pid += 1
    cur.executemany("INSERT INTO products VALUES (?,?,?,?)", products)

    # customers
    n_customers = 500
    customers = []
    for cid in range(1, n_customers + 1):
        region = rng.choice(REGIONS)
        signup = START + timedelta(days=rng.randint(-365, (END - START).days))
        customers.append((cid, f"고객{cid:04d}", region, signup.isoformat()))
    cur.executemany("INSERT INTO customers VALUES (?,?,?,?)", customers)

    # orders + order_items
    n_orders = 8000
    orders = []
    items = []
    item_id = 1
    for oid in range(1, n_orders + 1):
        cid = rng.randint(1, n_customers)
        odate = _random_date(rng)
        status = rng.choice(STATUSES)
        orders.append((oid, cid, odate.isoformat(), status))

        n_items = rng.randint(1, 5)
        chosen = rng.sample(products, n_items)
        for p in chosen:
            qty = rng.randint(1, 4)
            # 2026년 3분기에 '프리미엄 노트북' 판매량 급증(이상치) 주입
            if p[1] == "프리미엄 노트북" and odate >= date(2026, 7, 1):
                qty *= 6
            items.append((item_id, oid, p[0], qty, p[3]))
            item_id += 1

    cur.executemany("INSERT INTO orders VALUES (?,?,?,?)", orders)
    cur.executemany("INSERT INTO order_items VALUES (?,?,?,?,?)", items)

    cur.executescript(
        """
        CREATE INDEX idx_orders_date ON orders(order_date);
        CREATE INDEX idx_orders_customer ON orders(customer_id);
        CREATE INDEX idx_items_order ON order_items(order_id);
        CREATE INDEX idx_items_product ON order_items(product_id);
        """
    )

    conn.commit()
    conn.close()
    return db_path


if __name__ == "__main__":
    path = build()
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    for tbl in ("customers", "products", "orders", "order_items"):
        (n,) = cur.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()
        print(f"  {tbl:12s}: {n:,} 행")
    conn.close()
    print(f"\n생성 완료 → {path}")
