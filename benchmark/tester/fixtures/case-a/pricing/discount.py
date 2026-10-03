def apply_discount(total: float, vip: bool = False) -> float:
    amount = total * 0.90 if vip else total
    return round(amount, 2)
