# -*- coding: utf-8 -*-
"""他乡茶图 — CloudBase HTTP 云函数（Flask）
复用 scripts/api_proxy.py 的验证逻辑，把后端搬上腾讯云开发。
监听 0.0.0.0:9000（CloudBase 强制端口）。
"""
import os
import urllib.request
import urllib.parse
from flask import Flask, request, jsonify, Response

import proxy_logic as P  # scripts/api_proxy.py 的逻辑（同目录 vendored 副本）

app = Flask(__name__)

# 启动时从环境变量 TENCENT_MAP_KEY 加载 WebService Key
P.load_api_key()

# 通用腾讯位置服务 WebService 代理（key 不暴露给前端）
PROXY_MAP = {
    "/api/search": "https://apis.map.qq.com/ws/place/v1/search",
    "/api/suggestion": "https://apis.map.qq.com/ws/place/v1/suggestion",
    "/api/geocoder": "https://apis.map.qq.com/ws/geocoder/v1/",
    "/api/weather": "https://apis.map.qq.com/ws/weather/v1",
}


@app.after_request
def add_cors(res):
    res.headers["Access-Control-Allow-Origin"] = "*"
    res.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    res.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return res


def _proxy_tencent(path_key):
    base = PROXY_MAP[path_key]
    params = dict(request.args)
    if "key" not in params and P.API_KEY:
        params["key"] = P.API_KEY
    url = base + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        return Response(data, mimetype="application/json; charset=utf-8")
    except Exception as e:
        return jsonify({"status": -1, "message": str(e)}), 502


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/search")
def search():
    return _proxy_tencent("/api/search")


@app.route("/api/suggestion")
def suggestion():
    return _proxy_tencent("/api/suggestion")


@app.route("/api/geocoder")
def geocoder():
    return _proxy_tencent("/api/geocoder")


@app.route("/api/weather")
def weather():
    return _proxy_tencent("/api/weather")


@app.route("/api/verify_brand", methods=["GET", "POST", "OPTIONS"])
def verify_brand():
    if request.method == "OPTIONS":
        return ("", 204)
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        brand = data.get("brand", "")
        city = data.get("city", "")
        store_count = int(data.get("store_count", 1))
        in_known_list = bool(data.get("in_known_list", False))
    else:
        brand = request.args.get("brand", "")
        city = request.args.get("city", "")
        store_count = int(request.args.get("store_count", 1))
        in_known_list = False
    if not brand or not city:
        return jsonify({"error": "缺少 brand 或 city"}), 400
    found, matched, reason = P.verify_brand_in_city(brand, city, store_count, in_known_list)
    return jsonify({
        "brand": brand, "city": city, "found": found,
        "matched_count": len(matched),
        "matched_shops": [m["title"] for m in matched],
        "reason": reason,
    })


@app.route("/api/capital_check", methods=["POST", "OPTIONS"])
def capital_check():
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(silent=True) or {}
    brand = data.get("brand", "")
    lat = data.get("lat")
    lng = data.get("lng")
    store_count = int(data.get("store_count", 1))
    in_known_list = bool(data.get("in_known_list", False))
    if not brand or lat is None or lng is None:
        return jsonify({"error": "缺少 brand 或 lat/lng"}), 400
    capital, current_city = P.find_provincial_capital(lat, lng)
    if not capital:
        return jsonify({"brand": brand, "found": False, "capital": "",
                         "matched_count": 0, "reason": "无法确定省会城市"})
    if current_city and (capital in current_city or current_city in capital):
        return jsonify({"brand": brand, "found": False, "capital": capital,
                         "matched_count": 0, "reason": f"当前地点({current_city})即省会，跳过省会检查"})
    found, matched, reason = P.verify_brand_in_city(brand, capital, store_count, in_known_list)
    return jsonify({
        "brand": brand, "capital": capital, "found": found,
        "matched_count": len(matched),
        "matched_shops": [m["title"] for m in matched],
        "reason": reason,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9000)
