#!/usr/bin/env python3
"""
奶茶地图数据采集脚本
调用腾讯位置服务 WebService API，采集指定城市的奶茶/果茶/冷饮店铺数据。
数据保存为 JSON，供前端热力图加载使用。
"""

import json
import os
import time
import urllib.request
import urllib.parse
from pathlib import Path

# ============== 配置 ==============

# 读取 API Key
CONFIG_PATH = os.path.expanduser("~/.tencentmap/tempkey.json")
BASE_URL = "https://apis.map.qq.com/ws/place/v1/search"

# 搜索关键词列表（覆盖奶茶、果茶、冷饮等品类）
KEYWORDS = ["奶茶", "果茶", "柠檬茶", "冷饮", "茶饮", "烧仙草"]

# 知名品牌列表（用于从店名中提取品牌，按长度降序避免短名误匹配）
BRANDS = [
    "蜜雪冰城", "霸王茶姬", "奈雪的茶", "茶颜悦色", "书亦烧仙草",
    "茶百道", "古茗", "沪上阿姨", "一点点", "CoCo都可",
    "7分甜", "悸动烧仙草", "甜啦啦", "喜茶", "乐乐茶",
    "伏见桃山", "丘大叔", "林里柠檬茶", "新时茶", "鹿角巷",
    "益禾堂", "茗香奶茶", "快乐柠檬", "大杯茶", "猫印茶",
    "茶小暖", "柠檬森林", "阿水大杯茶", "一只酸奶牛",
    "茶理宜世", "苏阁鲜茶", "Manner", "瑞幸", "库迪",
    " UncleCoffee",
]
# 去重并按长度降序排列
BRANDS = sorted(set(BRANDS), key=lambda x: -len(x))

# 目标城市列表（adcode 或城市名）
# 大城市按区采集以绕过200条限制，小城市直接按市采集
CITIES = [
    {"name": "武汉市", "adcode": "420100", "level": "city"},
]

# 大城市的区级列表（用于分区域采集，绕过200条限制）
# 先只做武汉市，后续可扩展
DISTRICTS = {
    "420100": ["江岸区", "江汉区", "硚口区", "汉阳区", "武昌区", "青山区", "洪山区", "东西湖区", "汉南区", "蔡甸区", "江夏区", "黄陂区", "新洲区"],
}

# 输出文件路径
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "milktea_data.json")

# QPS 限制：临时 Key = 5 次/秒
REQUEST_INTERVAL = 0.25  # 每次请求间隔 250ms

# ============== 工具函数 ==============

def load_api_key():
    """从本地配置读取 API Key"""
    if not os.path.exists(CONFIG_PATH):
        print(f"❌ 未找到配置文件: {CONFIG_PATH}")
        print("请先按 tempkey-guide.md 配置 API Key")
        return None
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    # tempkey.json 格式: { "手机号": { "key": "xxx", ... } }
    key = None
    for phone, info in config.items():
        if isinstance(info, dict) and info.get("key"):
            key = info["key"]
            break
    if not key:
        print("❌ 配置文件中未找到 key 字段")
        return None
    print(f"✅ API Key: {key[:8]}...{key[-4:]}")
    return key


def search_pois(key, keyword, boundary, page_size=20, max_pages=10):
    """
    调用地点搜索 API
    :param key: API Key
    :param keyword: 搜索关键词
    :param boundary: 搜索范围，如 "region(武汉,0)" 或 "nearby(39.98,116.30,1000)"
    :param page_size: 每页条目数（最大20）
    :param max_pages: 最大页数（最多10页=200条）
    :return: POI 列表
    """
    all_pois = []
    for page in range(1, max_pages + 1):
        params = {
            "key": key,
            "keyword": keyword,
            "boundary": boundary,
            "page_size": str(page_size),
            "page_index": str(page),
            "added_fields": "category_code",
        }
        url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"  ⚠️ 请求失败 (page {page}): {e}")
            break

        if result.get("status") != 0:
            print(f"  ⚠️ API 返回错误: status={result.get('status')}, message={result.get('message')}")
            break

        data = result.get("data", [])
        all_pois.extend(data)
        total = result.get("count", 0)
        print(f"  [{keyword}] page {page}: 获取 {len(data)} 条，累计 {len(all_pois)}/{total}")

        if len(data) < page_size:
            break  # 没有更多数据了

        time.sleep(REQUEST_INTERVAL)

    return all_pois


def parse_brand(title):
    """
    从店铺名称中解析品牌名
    :param title: 店铺标题，如 "喜茶(三里屯太古里店)"
    :return: 品牌名，如 "喜茶"
    """
    # 先匹配已知品牌
    for brand in BRANDS:
        if brand in title:
            return brand
    # 未知品牌：取第一个 ( 或 （ 前面的文字
    for sep in ["(", "（", " "]:
        idx = title.find(sep)
        if idx > 0:
            return title[:idx].strip()
    # 如果没有分隔符，取前 6 个字符作为品牌名
    return title[:6].strip() if len(title) > 6 else title.strip()


def deduplicate(pois):
    """按 POI id 去重"""
    seen = set()
    unique = []
    for poi in pois:
        pid = poi.get("id")
        if pid and pid not in seen:
            seen.add(pid)
            unique.append(poi)
    return unique


# ============== 主流程 ==============

def collect_city(key, city):
    """
    采集一个城市的奶茶店数据
    :param key: API Key
    :param city: {"name": "武汉市", "adcode": "420100", "level": "city"}
    :return: 该城市的所有奶茶店 POI 列表
    """
    city_name = city["name"]
    adcode = city["adcode"]
    print(f"\n{'='*60}")
    print(f"开始采集: {city_name} (adcode={adcode})")
    print(f"{'='*60}")

    all_pois = []

    # 判断是否需要按区采集
    districts = DISTRICTS.get(adcode)
    if districts:
        # 大城市：按区逐个搜索
        for district in districts:
            print(f"\n📍 区域: {district}")
            boundary = f"region({district},0)"
            for keyword in KEYWORDS:
                print(f"  搜索关键词: {keyword}")
                pois = search_pois(key, keyword, boundary)
                all_pois.extend(pois)
                time.sleep(REQUEST_INTERVAL)
    else:
        # 小城市：直接按市搜索
        print(f"\n📍 区域: {city_name} (全市)")
        boundary = f"region({city_name},0)"
        for keyword in KEYWORDS:
            print(f"  搜索关键词: {keyword}")
            pois = search_pois(key, keyword, boundary)
            all_pois.extend(pois)
            time.sleep(REQUEST_INTERVAL)

    # 去重
    unique_pois = deduplicate(all_pois)
    print(f"\n📊 {city_name} 采集完成: 原始 {len(all_pois)} 条，去重后 {len(unique_pois)} 条")
    return unique_pois


def build_output(pois, city_name):
    """
    构建输出数据结构
    :return: 热力图数据 + 品牌统计 + 区域统计
    """
    # 品牌统计
    brand_stats = {}  # {品牌: count}
    brand_shops = {}  # {品牌: [{lat, lng, title, address, district}]}

    # 区域统计
    district_stats = {}  # {区: {品牌: count}}

    for poi in pois:
        title = poi.get("title", "")
        brand = parse_brand(title)
        location = poi.get("location", {})
        lat = location.get("lat")
        lng = location.get("lng")
        ad_info = poi.get("ad_info", {})
        district = ad_info.get("district", "")

        if lat is None or lng is None:
            continue

        # 品牌统计
        brand_stats[brand] = brand_stats.get(brand, 0) + 1
        if brand not in brand_shops:
            brand_shops[brand] = []
        brand_shops[brand].append({
            "lat": lat,
            "lng": lng,
            "title": title,
            "address": poi.get("address", ""),
            "district": district,
        })

        # 区域统计
        if district:
            if district not in district_stats:
                district_stats[district] = {}
            district_stats[district][brand] = district_stats[district].get(brand, 0) + 1

    # 构建热力图数据点（所有店铺）
    heat_points = []
    for poi in pois:
        location = poi.get("location", {})
        lat = location.get("lat")
        lng = location.get("lng")
        if lat and lng:
            heat_points.append({"lat": lat, "lng": lng, "count": 1})

    # 按品牌构建热力图数据点
    brand_heat_points = {}
    for brand, shops in brand_shops.items():
        brand_heat_points[brand] = [
            {"lat": s["lat"], "lng": s["lng"], "count": 1}
            for s in shops
        ]

    # 品牌列表（按数量降序）
    brand_list = sorted(brand_stats.items(), key=lambda x: -x[1])
    brand_list = [{"name": b, "count": c} for b, c in brand_list]

    output = {
        "meta": {
            "city": city_name,
            "total_shops": len(pois),
            "total_brands": len(brand_stats),
            "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "brand_stats": brand_stats,
        "brand_list": brand_list,
        "district_stats": district_stats,
        "heat_points": heat_points,
        "brand_heat_points": brand_heat_points,
        "shops": pois,  # 原始数据，用于后续功能
    }
    return output


def main():
    print("🧋 奶茶地图数据采集工具")
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    key = load_api_key()
    if not key:
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_data = {}
    for city in CITIES:
        pois = collect_city(key, city)
        output = build_output(pois, city["name"])
        all_data[city["adcode"]] = output

        # 也单独保存每个城市的数据
        city_file = os.path.join(OUTPUT_DIR, f"milktea_{city['adcode']}.json")
        with open(city_file, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"  ✅ 保存至: {city_file}")

    # 保存汇总数据
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    print(f"\n📁 汇总数据保存至: {OUTPUT_FILE}")

    # 打印统计摘要
    print(f"\n{'='*60}")
    print("📈 采集摘要")
    print(f"{'='*60}")
    for adcode, data in all_data.items():
        meta = data["meta"]
        print(f"\n{meta['city']}:")
        print(f"  总店铺数: {meta['total_shops']}")
        print(f"  品牌数: {meta['total_brands']}")
        print(f"  Top 10 品牌:")
        for i, b in enumerate(data["brand_list"][:10], 1):
            print(f"    {i}. {b['name']}: {b['count']} 家")


if __name__ == "__main__":
    main()
