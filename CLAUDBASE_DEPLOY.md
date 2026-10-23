# 他乡茶图 · CloudBase 部署

已为你备好可直接上传的云函数包：**`milktea-map/hechatu-func.zip`**（含 Flask 依赖 `third_party/` + `app.py` + `proxy_logic.py` + `scf_bootstrap` + `requirements.txt`）。

后端逻辑从 `scripts/api_proxy.py` 完整移植：`/api/search` `/api/suggestion` `/api/geocoder` `/api/weather` `/api/verify_brand` `/api/capital_check`，复用 `verify_brand_in_city` / `extract_core` / `find_provincial_capital`。监听 `0.0.0.0:9000`（CloudBase 强制端口）。

## 部署步骤（腾讯云开发 CloudBase）

### 1. 创建云函数（后端）
1. 打开 [CloudBase 控制台](https://tcb.cloud.tencent.com/) → 云函数 → 新建。
2. 选 **HTTP 云函数**，运行时 **Python 3.10**。
3. 上传代码：选 `milktea-map/hechatu-func.zip`。
4. 执行方法填 `app.app`（文件 `app.py`，Flask 实例 `app`），启动脚本 `scf_bootstrap`（已含）。
5. 环境变量：`TENCENT_MAP_KEY` = 你的腾讯位置服务 WebService Key（即本地 `~/.tencentmap/tempkey.json` 里那个 `M32BZ-...`）。
6. 保存部署。点"测试/访问"能打开 `/health` 返回 `{"status":"ok"}` 即成功。

### 2. 绑定云接入路由（让前端同源调 /api）
1. 控制台 → HTTP 网关 / 云接入 → 路由管理 → 新建。
2. 关联资源：选刚才的云函数；域名：默认域名；触发路径：`/api/{proxy+}`。
3. 这样 `https://<env-id>.tcloudbaseapp.com/api/search` 等都会进到函数，按内部路由分发。

### 3. 上传静态前端
1. 控制台 → 静态网站托管 → 上传文件。
2. 把 `milktea-map/app.html` 和 `milktea-map/data/` 整个目录传上去（`data/national_brands.json` 要在 `data/` 下）。
3. 访问 `https://<env-id>.tcloudbaseapp.com/app.html` → 应用首页。

### 4. 为什么不用改 app.html
`app.html` 的 `PROXY` 在 443 端口下自动走相对路径（同源）：`fetch('/api/search')` → 命中第 2 步绑定的函数路由。前端和后端共用 `<env-id>.tcloudbaseapp.com` 域名，无跨域、无需硬编码 URL。

## 提交用链接
部署成功后，"可访问链接" 填：
```
https://<env-id>.tcloudbaseapp.com/app.html
```

## 注意
- WebService Key 通过云函数环境变量注入，不进前端、不进代码仓库。
- JSAPI Key（地图渲染）仍在 `app.html` 的 `<script src>` 里（公网可见无妨），建议在腾讯位置服务控制台给它配域名白名单 `*.tcloudbaseapp.com`。
- `verify_brand_in_city` 走 POI 搜索+字符串匹配，不依赖本地 knot-cli，云端正常运行。
