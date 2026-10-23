#!/usr/bin/env python3
"""
合并区域边界 + 奶茶统计数据 + 品牌logo颜色，生成前端可直接使用的完整数据。
"""
import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# 品牌logo代表色
BRAND_COLORS = {
    "蜜雪冰城": "#E60012",
    "书亦烧仙草": "#00873D",
    "霸王茶姬": "#D4A574",
    "吾饮良品水果茶": "#FF6B35",
    "益禾堂": "#00A859",
    "古茗": "#009A57",
    "柠季·手打柠檬茶": "#C8E62E",
    "茶百道": "#BA9F50",
    "1点点": "#5BAB56",
    "沪上阿姨": "#E60012",
    "CoCo都可": "#E2228B",
    "喜茶": "#000000",
    "奈雪的茶": "#00A862",
    "茶颜悦色": "#E60012",
    "7分甜": "#FFD700",
    "快乐柠檬": "#FFD700",
    "乐乐茶": "#FFC0CB",
    "鹿角巷": "#000000",
}

def hex_to_rgba(hex_color, alpha=0.7):
    """将 hex 颜色转为 rgba 字符串"""
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"

def main():
    # 加载区域边界
    with open(os.path.join(DATA_DIR, "wuhan_boundaries.json"), "r", encoding="utf-8") as f:
        boundaries = json.load(f)

    # 加载奶茶数据
    with open(os.path.join(DATA_DIR, "milktea_data.json"), "r", encoding="utf-8") as f:
        milktea = json.load(f)

    city_data = milktea["420100"]
    district_stats = city_data.get("district_stats", {})
    brand_stats = city_data.get("brand_stats", {})
    brand_list = city_data.get("brand_list", [])

    # 合并：每个区 -> 边界 + 统计
    areas = []
    for b in boundaries:
        name = b["name"]
        stats = district_stats.get(name, {})
        total = sum(stats.values())

        # 转换 polygon 为 Area API 需要的 path 格式
        # 区划API返回 [lng, lat, lng, lat, ...]（经度在前）
        # Area API 需要 [lat, lng, lat, lng, ...]（纬度在前），需要交换
        polygon = b.get("polygon", [])
        paths = []
        for part in polygon:
            if isinstance(part, list):
                flat = []
                # 原始格式是 [lng0, lat0, lng1, lat1, ...] 的平铺数组
                i = 0
                while i + 1 < len(part):
                    lng = part[i]
                    lat = part[i + 1]
                    flat.append(lat)
                    flat.append(lng)
                    i += 2
                if flat:
                    paths.append(flat)

        area = {
            "name": name,
            "adcode": b.get("adcode", ""),
            "center": b.get("center", {}),
            "path": paths,
            "total_shops": total,
            "brand_stats": stats,
        }
        areas.append(area)
        print(f"  {name}: {total} 家, {len(paths)} polygon parts")

    # 构建品牌颜色映射
    brand_colors = {}
    for item in brand_list:
        name = item["name"]
        color = BRAND_COLORS.get(name, "#5BA8E8")  # 默认蓝色
        brand_colors[name] = {
            "hex": color,
            "rgba_07": hex_to_rgba(color, 0.7),
            "rgba_03": hex_to_rgba(color, 0.3),
            "rgba_05": hex_to_rgba(color, 0.5),
            "rgba_02": hex_to_rgba(color, 0.2),
            "count": item["count"],
        }

    output = {
        "meta": {
            **city_data["meta"],
            "district_count": len(areas),
        },
        "areas": areas,
        "brand_list": brand_list,
        "brand_colors": brand_colors,
        "brand_stats": brand_stats,
        "district_stats": district_stats,
    }

    out_path = os.path.join(DATA_DIR, "milktea_area.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)

    size_kb = os.path.getsize(out_path) / 1024
    print(f"\n✅ 合并数据保存至: {out_path} ({size_kb:.0f}KB)")
    print(f"   区域数: {len(areas)}")
    print(f"   品牌数: {len(brand_colors)}")

if __name__ == "__main__":
    main()
