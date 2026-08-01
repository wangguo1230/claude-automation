"""SEPA IBAN 随机生成器。

使用 MOD-97 算法（ISO 13616）生成格式合法的 IBAN。
支持常见 SEPA 国家：DE（德国）、FR（法国）、NL（荷兰）、AT（奥地利）、BE（比利时）等。
"""

from __future__ import annotations

import random
from typing import Dict, Tuple

# (IBAN 总长度, 银行代码长度, 账号长度)
COUNTRY_SPECS: Dict[str, Tuple[int, int, int]] = {
    "DE": (22, 8, 10),   # 德国：BLZ(8) + 账号(10)
    "FR": (27, 5, 5 + 11 + 2),  # 法国特殊处理
    "NL": (18, 4, 10),   # 荷兰：银行(4) + 账号(10)
    "AT": (20, 5, 11),   # 奥地利：BLZ(5) + 账号(11)
    "BE": (16, 3, 7 + 2),  # 比利时特殊处理
    "ES": (24, 4, 4 + 2 + 10),  # 西班牙
    "IT": (27, 1 + 5 + 5, 12),  # 意大利
    "IE": (22, 4, 6 + 8),  # 爱尔兰
    "LU": (20, 3, 13),   # 卢森堡
    "PT": (25, 4, 4 + 11 + 2),  # 葡萄牙
    "FI": (18, 3, 11),   # 芬兰
    "LT": (20, 5, 11),   # 立陶宛
}

# 常见银行代码前缀（让生成的 IBAN 看起来更真实）
_BANK_PREFIXES: Dict[str, list[str]] = {
    "DE": ["10010010", "50010517", "37040044", "20050550", "76010085", "30060601"],
    "FR": ["30004", "20041", "30002", "10096"],
    "NL": ["ABNA", "INGB", "RABO", "TRIO"],
    "AT": ["19200", "20111", "32000", "36200"],
    "BE": ["539", "310", "001", "068"],
}


def _letters_to_digits(s: str) -> str:
    """A=10, B=11, ..., Z=35"""
    result = []
    for c in s:
        if c.isdigit():
            result.append(c)
        else:
            result.append(str(ord(c.upper()) - 55))
    return "".join(result)


def _compute_check_digits(country: str, bban: str) -> str:
    """计算 IBAN 校验位（MOD-97 算法）。"""
    raw = _letters_to_digits(bban + country + "00")
    remainder = int(raw) % 97
    check = 98 - remainder
    return f"{check:02d}"


def _random_digits(n: int) -> str:
    return "".join(str(random.randint(0, 9)) for _ in range(n))


def generate_iban(country: str = "DE") -> str:
    """生成指定国家的随机合法 IBAN。"""
    country = country.upper().strip()
    if country not in COUNTRY_SPECS:
        country = "DE"

    bban = _generate_bban(country)
    check = _compute_check_digits(country, bban)
    return f"{country}{check}{bban}"


def _generate_bban(country: str) -> str:
    total_len, bank_len, acct_len = COUNTRY_SPECS[country]
    bban_len = total_len - 4  # 减去国家码(2) + 校验位(2)

    prefixes = _BANK_PREFIXES.get(country, [])

    if country == "DE":
        bank_code = random.choice(prefixes) if prefixes else _random_digits(8)
        account = _random_digits(10)
        return bank_code + account

    if country == "FR":
        bank_code = random.choice(prefixes) if prefixes else _random_digits(5)
        branch = _random_digits(5)
        account = _random_digits(11)
        check_key = _random_digits(2)
        return bank_code + branch + account + check_key

    if country == "NL":
        bank_code = random.choice(prefixes) if prefixes else "ABNA"
        account = _random_digits(10)
        return bank_code + account

    if country == "AT":
        bank_code = random.choice(prefixes) if prefixes else _random_digits(5)
        account = _random_digits(11)
        return bank_code + account

    if country == "BE":
        bank_code = random.choice(prefixes) if prefixes else _random_digits(3)
        account = _random_digits(7)
        check_key = _random_digits(2)
        return bank_code + account + check_key

    # 通用处理
    if prefixes:
        bank_code = random.choice(prefixes)
        remaining = bban_len - len(bank_code)
        return bank_code + _random_digits(max(0, remaining))

    return _random_digits(bban_len)


def validate_iban(iban: str) -> bool:
    """验证 IBAN 校验位是否正确。"""
    iban = iban.replace(" ", "").upper()
    if len(iban) < 5:
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = _letters_to_digits(rearranged)
    return int(numeric) % 97 == 1


if __name__ == "__main__":
    for cc in ["DE", "FR", "NL", "AT", "BE"]:
        iban = generate_iban(cc)
        valid = validate_iban(iban)
        print(f"{cc}: {iban} (valid={valid})")
