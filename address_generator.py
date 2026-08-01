"""根据 IP 所在地区生成随机地址。

支持地区：US（免税州）、TW（台湾）、JP（日本）、HK（香港）、SG（新加坡）、KR（韩国）、GB（英国）、DE（德国）。
可通过代理探测出口 IP 自动选择地区。
"""

from __future__ import annotations

import json
import logging
import random
from typing import Any, Dict, Optional
from urllib.request import ProxyHandler, Request, build_opener
from urllib.error import URLError

logger = logging.getLogger(__name__)

REGIONS: Dict[str, Dict[str, Any]] = {
    "US": {
        "country": "US",
        "states": {
            "OR": [("Portland", "97205"), ("Eugene", "97401"), ("Salem", "97301"), ("Bend", "97701")],
            "DE": [("Wilmington", "19801"), ("Dover", "19901"), ("Newark", "19711")],
            "MT": [("Billings", "59101"), ("Missoula", "59801"), ("Bozeman", "59715")],
            "NH": [("Manchester", "03101"), ("Nashua", "03060"), ("Concord", "03301")],
        },
        "streets": ["Main", "Oak", "Maple", "Cedar", "Pine", "Elm", "Washington", "Lake", "Hill", "Park"],
        "suffixes": ["Street", "Avenue", "Road", "Lane", "Drive"],
    },
    "TW": {
        "country": "TW",
        "cities": [
            {"city": "Taipei", "state": "Taipei City", "postal": "100", "districts": ["Zhongzheng", "Daan", "Xinyi", "Zhongshan", "Songshan"]},
            {"city": "New Taipei", "state": "New Taipei City", "postal": "220", "districts": ["Banqiao", "Zhonghe", "Yonghe", "Sanchong", "Xinzhuang"]},
            {"city": "Taichung", "state": "Taichung City", "postal": "400", "districts": ["West", "North", "South", "Xitun", "Nantun"]},
            {"city": "Kaohsiung", "state": "Kaohsiung City", "postal": "800", "districts": ["Lingya", "Qianjin", "Xinxing", "Gushan", "Zuoying"]},
            {"city": "Taoyuan", "state": "Taoyuan City", "postal": "330", "districts": ["Taoyuan", "Zhongli", "Bade", "Pingzhen"]},
        ],
        "roads": ["Zhongxiao", "Renai", "Xinyi", "Heping", "Minsheng", "Minquan", "Minzu", "Nanjing", "Dunhua", "Fuxing"],
    },
    "JP": {
        "country": "JP",
        "cities": [
            {"city": "Tokyo", "state": "Tokyo", "postal": "100-0001", "districts": ["Chiyoda", "Minato", "Shibuya", "Shinjuku", "Meguro"]},
            {"city": "Osaka", "state": "Osaka", "postal": "530-0001", "districts": ["Kita-ku", "Chuo-ku", "Nishi-ku", "Tennoji"]},
            {"city": "Yokohama", "state": "Kanagawa", "postal": "220-0001", "districts": ["Nishi-ku", "Naka-ku", "Kanagawa-ku"]},
            {"city": "Nagoya", "state": "Aichi", "postal": "460-0001", "districts": ["Naka-ku", "Higashi-ku", "Chikusa-ku"]},
        ],
    },
    "HK": {
        "country": "HK",
        "cities": [
            {"city": "Hong Kong", "state": "Hong Kong Island", "postal": "000000", "districts": ["Central", "Wan Chai", "Causeway Bay", "North Point", "Admiralty"]},
            {"city": "Kowloon", "state": "Kowloon", "postal": "000000", "districts": ["Tsim Sha Tsui", "Mong Kok", "Jordan", "Yau Ma Tei"]},
            {"city": "New Territories", "state": "New Territories", "postal": "000000", "districts": ["Sha Tin", "Tsuen Wan", "Tuen Mun", "Yuen Long"]},
        ],
    },
    "SG": {
        "country": "SG",
        "cities": [
            {"city": "Singapore", "state": "Singapore", "postal_range": (10, 82), "districts": ["Orchard", "Marina Bay", "Bugis", "Tanjong Pagar", "Raffles Place", "Clementi", "Jurong", "Tampines", "Bedok"]},
        ],
    },
    "KR": {
        "country": "KR",
        "cities": [
            {"city": "Seoul", "state": "Seoul", "postal": "04524", "districts": ["Gangnam-gu", "Seocho-gu", "Mapo-gu", "Yongsan-gu", "Jongno-gu"]},
            {"city": "Busan", "state": "Busan", "postal": "48058", "districts": ["Haeundae-gu", "Busanjin-gu", "Nam-gu"]},
            {"city": "Incheon", "state": "Incheon", "postal": "21999", "districts": ["Namdong-gu", "Bupyeong-gu", "Yeonsu-gu"]},
        ],
    },
    "GB": {
        "country": "GB",
        "cities": [
            {"city": "London", "state": "England", "postal": "EC1A", "districts": ["Westminster", "Camden", "Islington", "Kensington"]},
            {"city": "Manchester", "state": "England", "postal": "M1", "districts": ["City Centre", "Didsbury", "Chorlton"]},
            {"city": "Edinburgh", "state": "Scotland", "postal": "EH1", "districts": ["Old Town", "New Town", "Leith"]},
        ],
    },
    "DE": {
        "country": "DE",
        "cities": [
            {"city": "Berlin", "state": "Berlin", "postal": "10115", "districts": ["Mitte", "Kreuzberg", "Charlottenburg", "Prenzlauer Berg"]},
            {"city": "Munich", "state": "Bavaria", "postal": "80331", "districts": ["Altstadt", "Schwabing", "Maxvorstadt"]},
            {"city": "Hamburg", "state": "Hamburg", "postal": "20095", "districts": ["Altstadt", "Neustadt", "St. Pauli"]},
        ],
    },
}

_FIRST_NAMES = [
    "James", "Robert", "Michael", "William", "David",
    "Richard", "Joseph", "Thomas", "Charles", "Daniel",
    "Mary", "Patricia", "Jennifer", "Linda", "Barbara",
    "Elizabeth", "Susan", "Jessica", "Sarah", "Karen",
    "Alex", "Taylor", "Jordan", "Casey", "Morgan",
]

_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones",
    "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
    "Anderson", "Thomas", "Jackson", "White", "Harris",
    "Clark", "Lewis", "Robinson", "Walker", "Young",
]


def random_name() -> str:
    return f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"


def detect_country(proxy: str = "") -> str:
    try:
        if proxy:
            p = proxy.strip()
            if "://" not in p:
                p = "http://" + p
            opener = build_opener(ProxyHandler({"http": p, "https": p}))
        else:
            opener = build_opener(ProxyHandler({}))
        req = Request("http://ip-api.com/json/?fields=countryCode", headers={"User-Agent": "curl/8.0"})
        with opener.open(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            cc = str(data.get("countryCode", "")).upper()
            logger.info("IP 地区检测: %s", cc)
            return cc
    except Exception as exc:
        logger.warning("IP 地区检测失败: %s", exc)
        return ""


def generate_address(country: str = "", proxy: str = "") -> Dict[str, str]:
    country = country.upper().strip()

    if not country and proxy:
        country = detect_country(proxy)

    if country == "US" or not country:
        return _generate_us_address()

    if country in REGIONS:
        return _generate_international_address(country)

    return _generate_us_address()


def _generate_us_address() -> Dict[str, str]:
    us = REGIONS["US"]
    state = random.choice(list(us["states"].keys()))
    city, postal = random.choice(us["states"][state])
    number = random.randint(100, 9999)
    line1 = f"{number} {random.choice(us['streets'])} {random.choice(us['suffixes'])}"
    return {
        "name": random_name(),
        "line1": line1,
        "city": city,
        "state": state,
        "postal_code": postal,
        "country": "US",
    }


def _generate_international_address(country: str) -> Dict[str, str]:
    region = REGIONS[country]
    city_info = random.choice(region["cities"])
    district = random.choice(city_info.get("districts", ["District 1"]))
    number = random.randint(1, 200)

    if country == "TW":
        road = random.choice(region.get("roads", ["Zhongshan"]))
        section = random.randint(1, 5)
        lane = random.randint(1, 300)
        line1 = f"No. {number}, Lane {lane}, Section {section}, {road} Road"
        postal = str(int(city_info["postal"]) + random.randint(0, 15))
    elif country == "JP":
        chome = random.randint(1, 8)
        ban = random.randint(1, 30)
        go = random.randint(1, 20)
        line1 = f"{district} {chome}-{ban}-{go}"
        postal = city_info["postal"]
    elif country == "SG":
        pr = city_info.get("postal_range", (10, 82))
        postal = f"{random.randint(pr[0], pr[1]):02d}{random.randint(1000, 9999)}"
        block = random.randint(1, 800)
        line1 = f"Blk {block} {district} Street {random.randint(1, 50)}"
    elif country == "HK":
        floor = random.randint(1, 40)
        flat = random.choice("ABCDEF")
        line1 = f"Flat {flat}, {floor}/F, {number} {district} Road"
        postal = ""
    elif country == "KR":
        dong = random.randint(1, 500)
        ho = random.randint(101, 2505)
        line1 = f"{dong}-{ho}, {district}"
        postal = city_info["postal"]
    elif country == "GB":
        line1 = f"{number} {district} Street"
        suffix = random.choice(["1AA", "2BB", "3CC", "4DD", "1AB", "2CD"])
        postal = f"{city_info['postal']} {suffix}"
    elif country == "DE":
        line1 = f"{district}str. {number}"
        postal = str(int(city_info["postal"]) + random.randint(0, 50))
    else:
        line1 = f"{number} {district} Street"
        postal = city_info.get("postal", "00000")

    return {
        "name": random_name(),
        "line1": line1,
        "city": city_info["city"],
        "state": city_info.get("state", ""),
        "postal_code": postal,
        "country": region["country"],
    }


if __name__ == "__main__":
    for cc in ["US", "TW", "JP", "HK", "SG", "KR", "GB", "DE"]:
        addr = generate_address(cc)
        print(f"{cc}: {addr['name']}, {addr['line1']}, {addr['city']}, {addr['state']} {addr['postal_code']}")
