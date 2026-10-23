#!/usr/bin/env python3
"""
奶茶地图 API 代理服务器
- 代理腾讯位置服务 WebService API 请求
- /api/verify_brand: AI 智能验证品牌是否在指定城市存在
用法: python3 scripts/api_proxy.py
"""

import http.server
import urllib.request
import urllib.parse
import json
import sys
import os
import re
import difflib
import subprocess

PORT = int(os.environ.get("PORT", 8766))
API_KEY = None
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # milktea-map 根目录

# AI 验证开关：knot-cli 额度可用时自动启用
KNOT_CLI = os.path.expanduser("~/background_agent_cli/bin/knot-cli")
AI_MODEL = "glm-5.2"

# ============ 品牌智能验证 ============

# 饮品相关品类关键词（category 字段必须包含这些之一）
DRINK_CATEGORIES = ['饮', '茶', '奶茶', '果茶', '咖啡', '冷饮', '果汁', '冰激凌', '甜品', '小吃']

# 非饮品品类（直接排除）
EXCLUDE_CATEGORIES = ['医疗', '口腔', '科技', '公司', '企业', '公共设施', '厕所',
                       '眼镜', '服装', '数码', '电子', '汽修', '建材', '家具',
                       '美容', '美甲', '理发', '地产', '金融', '保险', '教育',
                       '培训', '律师', '会计', '物流', '快递', '维修', '五金',
                       '水果', '鲜花', '宠物', '母婴', '彩票', '报刊', '音像']

# 非饮品店名关键词（标题包含这些的直接排除）
EXCLUDE_TITLE_KEYWORDS = ['口腔', '牙', '诊所', '医院', '科技', '公司', '企业',
                           '眼镜', '服装', '数码', '美容', '美甲', '理发',
                           '地产', '中介', '保险', '培训', '教育', '律师',
                           '会计', '物流', '快递', '维修', '五金', '建材',
                           '汽修', '家具', '厕所', '公共', '便利店', '超市',
                           '糕点', '面包', '批发', '烟酒', '百货',
                           '水果店', '鲜果店', '水果商店', '榴莲', '蔬菜',
                           '花店', '鲜花', '宠物', '母婴', '彩票']

# 饮品店名关键词（标题包含这些的更可能是饮品店）
DRINK_TITLE_KEYWORDS = ['奶茶', '果茶', '茶饮', '冷饮', '烧仙草', '柠檬茶',
                         '茶铺', '茶室', '茶', '饮品', '咖啡', '果汁', '鲜奶',
                         '酸奶', '冰沙', '冰激凌', '奶盖', '波霸', '手作']

# 省份 → 省会城市（用于省会连锁检查）
PROVINCIAL_CAPITALS = {
    '北京': '北京', '天津': '天津', '上海': '上海', '重庆': '重庆',
    '河北': '石家庄', '山西': '太原', '内蒙古': '呼和浩特',
    '辽宁': '沈阳', '吉林': '长春', '黑龙江': '哈尔滨',
    '江苏': '南京', '浙江': '杭州', '安徽': '合肥', '福建': '福州',
    '江西': '南昌', '山东': '济南', '河南': '郑州', '湖北': '武汉',
    '湖南': '长沙', '广东': '广州', '广西': '南宁', '海南': '海口',
    '四川': '成都', '贵州': '贵阳', '云南': '昆明', '西藏': '拉萨',
    '陕西': '西安', '甘肃': '兰州', '青海': '西宁', '宁夏': '银川',
    '新疆': '乌鲁木齐', '香港': '香港', '澳门': '澳门', '台湾': '台北',
}


# 产品/品类通用词（从品牌名和店名中剥离，提取核心品牌标识）
# extract_core 用 str.remove 移除所有出现位置，前缀/后缀/中间均覆盖
PRODUCT_CATEGORY_WORDS = sorted([
    '酸奶紫米露', '鲜奶茶', '珍珠奶茶', '柠檬茶', '手工茶', '手作茶',
    '手工酸奶', '手作酸奶',
    '烧仙草', '冰激凌', '冰淇淋', '茶饮店', '饮品店',
    '紫米露', '果汁', '冷饮', '奶茶', '果茶', '茶饮', '饮品', '烤茶',
    '茶肆', '茶室', '茶铺', '茶馆', '茶坊',
    '酸奶', '珍珠', '门店', '店铺', '店',
], key=len, reverse=True)


def _is_subsequence(short, long):
    """检查 short 是否是 long 的子序列（每个字按顺序出现，不要求连续）"""
    it = iter(long)
    return all(c in it for c in short)


def split_zh_en(name):
    """将名称拆分为 (中文部分, 英文部分)。英文部分小写。"""
    zh = re.sub(r'[A-Za-z\s0-9]+', '', name)
    en_parts = re.findall(r'[A-Za-z]+', name)
    en = ''.join(en_parts).lower() if en_parts else ''
    return zh, en


def extract_core(name):
    """从名称中剥离产品/品类通用词，提取核心品牌标识。返回 (core, stripped)。"""
    core = name
    stripped = False
    # 含"·"时，"·"及之后是产品/品类描述，取之前的部分作为核心
    for dot in ['·', '・', '•', '‧', '･']:
        if dot in core:
            core = core.split(dot)[0]
            stripped = True
            break
    for word in PRODUCT_CATEGORY_WORDS:
        if word in core:
            core = core.replace(word, '')
            stripped = True
    return core.strip(), stripped


def ai_verify_candidates(brand, city_name, candidates):
    """
    用 LLM (knot-cli) 判断候选店铺是否和品牌同名/同品牌。
    返回: (ai_matched_titles: list, ai_reason: str)
    如果 AI 不可用（额度耗尽等），返回 (None, error_msg) 由调用方回退到逻辑匹配。
    """
    if not candidates:
        return [], "无候选"

    # 构造候选列表（最多20个，避免 prompt 过长）
    shop_list = []
    for i, poi in enumerate(candidates[:20], 1):
        shop_list.append(f"{i}. {poi.get('title', '')}")

    prompt = (
        f"你是奶茶/饮品品牌识别专家。品牌名：「{brand}」。城市：{city_name}。\n"
        f"以下是在该城市搜索到的候选店铺，判断哪些和品牌「{brand}」是同一家品牌"
        f"（包括简称、去掉中间修饰词如\"糯香\"、不同分店后缀等情况）。\n"
        f"注意：仅前缀相似但末字不同的（如\"老兵茶点\"vs\"老兵茶室\"）不是同品牌。\n"
        f"候选店铺：\n" + "\n".join(shop_list) + "\n\n"
        f"只返回匹配的店铺编号，用逗号分隔（如 1,3,5）。如果没有匹配，返回：无"
    )

    try:
        result = subprocess.run(
            [KNOT_CLI, "chat", "-m", AI_MODEL, "-p", prompt],
            capture_output=True, text=True, timeout=30
        )
        output = result.stdout.strip()

        # 检测额度耗尽
        if "额度" in output or "Token" in output:
            return None, "AI额度耗尽"

        # 解析返回的编号
        nums = re.findall(r'\d+', output.split('\n')[0])
        matched_titles = []
        for n in nums:
            idx = int(n) - 1
            if 0 <= idx < len(candidates):
                matched_titles.append(candidates[idx].get("title", ""))

        if matched_titles:
            return matched_titles, f"AI匹配{len(matched_titles)}家"
        else:
            return [], "AI判定无匹配"

    except Exception as e:
        return None, f"AI调用失败: {e}"


def find_provincial_capital(lat, lng):
    """逆地理编码获取所在省份和城市。返回 (省会城市名, 当前城市名)，失败返回 (None, None)。"""
    params = {
        "key": API_KEY,
        "location": f"{lat},{lng}",
        "get_poi": "0",
    }
    url = "https://apis.map.qq.com/ws/geocoder/v1/?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        if result.get("status") != 0:
            return None, None
        addr = result.get("result", {}).get("address_component", {})
        province = addr.get("province", "")
        city = addr.get("city", "") or province  # 直辖市 city 可能为空，用 province 兜底
        province_clean = province.replace('省', '').replace('市', '').replace('自治区', '').replace('特别行政区', '')
        capital = None
        # 直辖市/自治区特判
        for key in PROVINCIAL_CAPITALS:
            if key in province or province in key:
                capital = PROVINCIAL_CAPITALS[key]
                break
        if not capital and province_clean in PROVINCIAL_CAPITALS:
            capital = PROVINCIAL_CAPITALS[province_clean]
        return capital, city
    except Exception:
        return None, None


def verify_brand_in_city(brand, city_name, store_count=1, in_known_list=False):
    """
    智能验证品牌是否在指定城市存在
    store_count: 该品牌在搜索地附近有几家店
    in_known_list: 是否在已知连锁名单中
    返回: (found: bool, matched_shops: list, reason: str)
    """
    # 置信度组合判断：
    # 在名单里 = 已知连锁 → 宽松（跨城很正常）
    # 不在名单 + 1家 = 可能本地单店 → 严格（品牌名必须完整匹配+饮品品类）
    # 不在名单 + 2-4家 = 可能小连锁 → 正常
    # 不在名单 + 5家+ = 可能大连锁 → 宽松
    if in_known_list:
        confidence = "loose"
    elif store_count <= 1:
        confidence = "strict"
    elif store_count <= 4:
        confidence = "normal"
    else:
        confidence = "loose"
    # 搜索关键词用核心品牌名（剥离产品词和"·"后缀），长名更容易命中
    search_keyword = brand
    brand_core, _ = extract_core(brand)
    if brand_core and len(brand_core) >= 2:
        search_keyword = brand_core

    # 分页抓取（最多3页），避免无关结果淹没目标店
    boundary = f"region({city_name},0)"
    all_candidates = []
    total = 0
    for page in range(1, 4):
        params = {
            "key": API_KEY,
            "keyword": search_keyword,
            "boundary": boundary,
            "page_size": "20",
            "page_index": str(page),
        }
        url = "https://apis.map.qq.com/ws/place/v1/search?" + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            if page == 1:
                return False, [], f"API请求失败: {e}"
            break

        if result.get("status") != 0:
            if page == 1:
                return False, [], f"API错误: {result.get('message', '')}"
            break

        page_data = result.get("data", [])
        total = result.get("count", 0)
        all_candidates.extend(page_data)
        if not page_data or len(all_candidates) >= total:
            break

    # 按 id 去重（分页可能重叠）
    seen_ids = set()
    candidates = []
    for poi in all_candidates:
        pid = poi.get("id")
        if pid and pid in seen_ids:
            continue
        if pid:
            seen_ids.add(pid)
        candidates.append(poi)

    if not candidates:
        return False, [], "无搜索结果"

    # === Phase 1: 品类过滤（排除非饮品店）===
    drink_candidates = []
    rejected = []

    for poi in candidates:
        title = poi.get("title", "")
        category = poi.get("category", "")
        address = poi.get("address", "")
        text = title + " " + category + " " + address

        # 排除非饮品品类
        is_excluded = False
        for ex_cat in EXCLUDE_CATEGORIES:
            if ex_cat in category or ex_cat in title:
                rejected.append(f"{title} (排除:品类={ex_cat})")
                is_excluded = True
                break
        if is_excluded:
            continue

        # 排除非饮品店名
        for ex_kw in EXCLUDE_TITLE_KEYWORDS:
            if ex_kw in title:
                rejected.append(f"{title} (排除:店名含{ex_kw})")
                is_excluded = True
                break
        if is_excluded:
            continue

        # 验证是否是饮品店
        is_drink = False
        for dk in DRINK_CATEGORIES:
            if dk in category or dk in text:
                is_drink = True
                break
        if not is_drink:
            for dk in DRINK_TITLE_KEYWORDS:
                if dk in title:
                    is_drink = True
                    break
        if not is_drink:
            rejected.append(f"{title} (排除:非饮品店,category={category})")
            continue

        drink_candidates.append(poi)

    # === 品牌名匹配（双向子序列）===
    matched = []
    for poi in drink_candidates:
        title = poi.get("title", "")
        category = poi.get("category", "")
        address = poi.get("address", "")

        # 清洗（去括号内容），保留英文，统一小写用于匹配
        title_prefix = re.split(r'[（(]', title)[0].strip().lower()
        brand_clean = brand.lower()

        if not brand_clean or not title_prefix:
            rejected.append(f"{title} (排除:清洗后名称为空)")
            continue

        # 步骤1：全名双向子序列匹配（含英文，任一方每个字符按顺序出现在另一方中）
        fwd = _is_subsequence(brand_clean, title_prefix)
        rev = _is_subsequence(title_prefix, brand_clean)
        if not (fwd or rev):
            rejected.append(f"{title} (排除:非子序列)")
            continue

        # 步骤2：核心覆盖检测（品牌有通用词被剥离时执行）
        brand_core, brand_stripped = extract_core(brand_clean)
        if brand_stripped and brand_core:
            # 核心必须被候选店名覆盖（核心是店名的子序列）
            if not _is_subsequence(brand_core, title_prefix):
                rejected.append(f"{title} (排除:核心{brand_core}未被店名覆盖)")
                continue
            match_type = f"核心覆盖({brand_core})"
        elif brand_clean in title_prefix:
            match_type = "精确匹配"
        elif title_prefix in brand_clean:
            match_type = "双向子串"
        else:
            match_type = "子序列"

        matched.append({
            "title": title,
            "address": address,
            "category": category,
            "match_type": match_type,
        })

    found = len(matched) > 0
    reason = f"API返回{total}条, 品类过滤后{len(drink_candidates)}条, 逻辑匹配{len(matched)}条(含双向子串), 排除{len(rejected)}条"
    if rejected:
        reason += " | 排除: " + "; ".join(rejected[:3])

    return found, matched, reason


# ============ 代理服务器 ============

def load_api_key():
    global API_KEY
    env_key = os.environ.get("TENCENT_MAP_KEY")
    if env_key:
        API_KEY = env_key
        print(f"✅ API Key (env): {API_KEY[:8]}...{API_KEY[-4:]}")
        return True
    config_path = os.path.expanduser("~/.tencentmap/tempkey.json")
    if not os.path.exists(config_path):
        print(f"❌ 未找到配置文件: {config_path}")
        print("   可设置环境变量 TENCENT_MAP_KEY 代替。")
        return False
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    for phone, info in config.items():
        if isinstance(info, dict) and info.get("key"):
            API_KEY = info["key"]
            print(f"✅ API Key: {API_KEY[:8]}...{API_KEY[-4:]}")
            return True
    print("❌ 配置文件中未找到 key")
    return False


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self._send_json({"status": "ok"})
            return

        if not self.path.startswith("/api/"):
            self._serve_static()
            return

        # === AI 品牌验证端点 ===
        if self.path.startswith("/api/verify_brand"):
            self.handle_verify_brand()
            return

        # === 普通 API 代理 ===
        path_map = {
            "/api/search": "https://apis.map.qq.com/ws/place/v1/search",
            "/api/suggestion": "https://apis.map.qq.com/ws/place/v1/suggestion",
            "/api/geocoder": "https://apis.map.qq.com/ws/geocoder/v1/",
            "/api/weather": "https://apis.map.qq.com/ws/weather/v1",
        }

        api_type = self.path.split("?")[0]
        base_url = path_map.get(api_type)

        if not base_url:
            self._send_json({"error": "unknown api"}, 404)
            return

        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        flat_params = {}
        for k, v in params.items():
            flat_params[k] = v[0] if isinstance(v, list) else v
        if (not flat_params.get("key")) and API_KEY:
            flat_params["key"] = API_KEY

        target_url = base_url + "?" + urllib.parse.urlencode(flat_params)
        print(f"  → {api_type} | {flat_params.get('keyword', '')[:20]} | {flat_params.get('boundary', '')[:40]}")

        try:
            req = urllib.request.Request(target_url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                self._send_raw(data, "application/json; charset=utf-8")
        except Exception as e:
            print(f"  ❌ 代理失败: {e}")
            self._send_json({"status": -1, "message": str(e)}, 502)

    def _serve_static(self):
        """提供前端静态文件（app.html / data / 等），与 API 同源部署。"""
        rel = self.path.split("?", 1)[0]
        if rel in ("", "/"):
            rel = "/app.html"
        # 防目录穿越
        rel = rel.lstrip("/")
        file_path = os.path.normpath(os.path.join(BASE_DIR, rel))
        if not file_path.startswith(BASE_DIR):
            self._send_json({"error": "forbidden"}, 403)
            return
        if not os.path.isfile(file_path):
            self._send_json({"error": "not found", "path": rel}, 404)
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".ico": "image/x-icon",
        }.get(os.path.splitext(file_path)[1], "application/octet-stream")
        try:
            with open(file_path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def handle_verify_brand(self):
        """AI 品牌验证: /api/verify_brand?brand=XXX&city=YYY&store_count=N"""
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        brand = params.get("brand", [""])[0]
        city = params.get("city", [""])[0]
        store_count = int(params.get("store_count", ["1"])[0])

        if not brand or not city:
            self._send_json({"error": "缺少 brand 或 city 参数"})
            return

        print(f"\n  🤖 AI验证: [{brand}] 在 [{city}] (附近{store_count}家, ", end="")
        found, matched, reason = verify_brand_in_city(brand, city, store_count)

        result = {
            "brand": brand,
            "city": city,
            "found": found,
            "matched_count": len(matched),
            "matched_shops": [m["title"] for m in matched],
            "reason": reason,
        }
        print(f"     → {'✅ 找到' if found else '❌ 未找到'}: {reason}")
        self._send_json(result)

    def do_POST(self):
        """支持 POST 方式的 AI 验证"""
        if self.path.startswith("/api/verify_brand"):
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len) if content_len > 0 else b"{}"
            try:
                data = json.loads(body.decode("utf-8"))
            except:
                self._send_json({"error": "invalid json"}, 400)
                return
            brand = data.get("brand", "")
            city = data.get("city", "")
            store_count = int(data.get("store_count", 1))
            in_known_list = bool(data.get("in_known_list", False))
            if not brand or not city:
                self._send_json({"error": "缺少 brand 或 city"})
                return
            print(f"\n  🤖 AI验证: [{brand}] 在 [{city}] (附近{store_count}家, {'名单内' if in_known_list else '名单外'})")
            found, matched, reason = verify_brand_in_city(brand, city, store_count, in_known_list)
            self._send_json({
                "brand": brand, "city": city, "found": found,
                "matched_count": len(matched),
                "matched_shops": [m["title"] for m in matched],
                "reason": reason,
            })
            return
        if self.path.startswith("/api/capital_check"):
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len) if content_len > 0 else b"{}"
            try:
                data = json.loads(body.decode("utf-8"))
            except:
                self._send_json({"error": "invalid json"}, 400)
                return
            brand = data.get("brand", "")
            lat = data.get("lat")
            lng = data.get("lng")
            store_count = int(data.get("store_count", 1))
            in_known_list = bool(data.get("in_known_list", False))
            if not brand or lat is None or lng is None:
                self._send_json({"error": "缺少 brand 或 lat/lng"})
                return
            capital, current_city = find_provincial_capital(lat, lng)
            if not capital:
                self._send_json({"brand": brand, "found": False, "capital": "",
                                 "matched_count": 0, "reason": "无法确定省会城市"})
                return
            # 如果当前地点就在省会城市，不需要和自己比，直接跳过
            if current_city and (capital in current_city or current_city in capital):
                self._send_json({"brand": brand, "found": False, "capital": capital,
                                 "matched_count": 0, "reason": f"当前地点({current_city})即省会，跳过省会检查"})
                return
            print(f"\n  🏛️ 省会检查: [{brand}] 在 [{capital}] (附近{store_count}家)")
            found, matched, reason = verify_brand_in_city(brand, capital, store_count, in_known_list)
            self._send_json({
                "brand": brand, "capital": capital, "found": found,
                "matched_count": len(matched),
                "matched_shops": [m["title"] for m in matched],
                "reason": reason,
            })
            return
        self._send_json({"error": "not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_raw(self, data, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    if not load_api_key():
        sys.exit(1)
    server = http.server.HTTPServer(("0.0.0.0", PORT), ProxyHandler)
    print(f"🚀 API 代理服务器启动: http://0.0.0.0:{PORT}")
    print(f"   健康检查: /health")
    print(f"   AI验证: POST /api/verify_brand")
    print(f"   前端: /app.html")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 代理服务器已停止")
