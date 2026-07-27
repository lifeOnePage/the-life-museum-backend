"""할인 쿠폰 금액 계산.

주의: 프론트엔드(the-life-museum/app/utils/payment.js의 applyCouponDiscount)와
정확히 같은 정수 연산을 써야 한다 — 결제 검증이 금액 일치를 요구하므로
반올림 방식이 다르면 정상 결제가 거부된다.
"""

# 할인 상한(KRW) → USD 환산용 고정 환율 (프론트와 동일 값 유지)
KRW_PER_USD = 1400


def discount_amounts(
    price_krw: int, price_usd_cents: int, percent: int, cap_krw: int
) -> tuple[int, int]:
    """(KRW 할인액, USD 할인액[cents])를 반환. 내림(floor) 고정."""
    d_krw = min(price_krw * percent // 100, cap_krw)
    cap_usd_cents = cap_krw * 100 // KRW_PER_USD
    d_usd = min(price_usd_cents * percent // 100, cap_usd_cents)
    return d_krw, d_usd


def discounted_prices(
    price_krw: int, price_usd_cents: int, percent: int, cap_krw: int
) -> tuple[int, int]:
    """할인 적용 후 (KRW 결제액, USD 결제액[cents])."""
    d_krw, d_usd = discount_amounts(price_krw, price_usd_cents, percent, cap_krw)
    return max(0, price_krw - d_krw), max(0, price_usd_cents - d_usd)
