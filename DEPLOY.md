# 他乡茶图 · 部署说明

## 架构（已改造为单服务）
一个 Python 进程 `scripts/api_proxy.py` 同时提供：
- **API**：`/api/search` `/api/suggestion` `/api/geocoder` `/api/weather` `/api/verify_brand` `/api/capital_check`（代理腾讯位置服务 WebService + AI 品牌验证）
- **静态前端**：`/app.html`、`/index.html`、`/data/*` 等

前端 `app.html` 的 `PROXY` 已做同源自动检测：部署到该服务同源时走相对路径，本地用 8000 端口开发时回退到 `localhost:8766`。

## 需要的密钥（两把）
1. **JSAPI Key**（地图渲染）：已写在 `app.html` 的 `<script src="...key=OB4BZ-...">`，公网可见无妨（JSAPI key 本就前端用，建议在腾讯位置服务控制台给它配"域名白名单"防盗用）。
2. **WebService Key**（搜索/逆地理/验证）：必须保密，通过环境变量或配置文件给后端，**不要写进前端**。

## 本地运行（已验证）
```bash
# 方式 A：环境变量（推荐，云上也好用）
export TENCENT_MAP_KEY="你的WebServiceKey"
cd milktea-map && python3 scripts/api_proxy.py

# 方式 B：本地配置文件 ~/.tencentmap/tempkey.json
# {"13800000000": {"key": "你的WebServiceKey"}}
cd milktea-map && python3 scripts/api_proxy.py
```
打开 http://localhost:8766/app.html 即可（API + 页面同源）。

## 部署到公网（拿到"可访问链接"）

### 方案零：CodeBuddy IDE 桌面客户端（拿 workbuddy.host 链接）
`https://<app>.app-tencent.workbuddy.host/?sharecode=XXX` 这种链接来自 **CodeBuddy IDE 桌面客户端**的"一键部署（Publish Cloud Studio）"：
1. 从 codebuddy.cn 下载/打开 **CodeBuddy IDE 桌面应用**（不是 VS Code 插件、不是 CLI——那两者没有 🚀 入口）。
2. 打开本项目，切到 **Craft 模式**，点右上角 🚀 小火箭，或说"部署当前项目到云端环境"。
3. 首次弹 Cloud Studio 授权，授权后填：启动命令 `python3 scripts/api_proxy.py`、端口 `8766`、环境变量 `TENCENT_MAP_KEY`。
4. 部署成功 → 生成 `*.workbuddy.host` 链接 + 二维码（临时/有有效期，评审期保持运行）。

### 方案一：Render（已配好，最省事，持久 HTTPS）
本目录已含 `render.yaml` / `Procfile` / `requirements.txt`，代理已支持读 `PORT` 环境变量并绑 `0.0.0.0`。
1. 把 `milktea-map/` 推到 GitHub 仓库。
2. Render → New → **Blueprint** → 连接该仓库（自动读 `render.yaml`）。
3. 在 Render 后台把 `TENCENT_MAP_KEY` 填为你的腾讯位置服务 WebService Key。
4. 部署完成 → `https://taxiang-chatu.onrender.com`，访问 `/app.html` 即应用。
   - 免费版 15 分钟无访问会休眠，首次唤醒约 30s；评审期可定时 ping 保活。

### 方案二：任意 Python 主机（fly.io / Railway / 自建）
同方案一，设环境变量 `TENCENT_MAP_KEY`、启动命令 `python3 scripts/api_proxy.py`、暴露 `PORT` 指定端口即可。

### 方案三：CloudBase 云开发（腾讯原生，需小改造）
- 前端 → CloudBase 静态网站托管；后端 → 云函数（需把 `api_proxy.py` 的 handler 改写为云函数入口）。
- 适合长期正式运营，改造量中等。

## 提交时怎么填
- **可访问链接**：填部署后的 `https://<域名>/app.html`（不是 PPT、不是设计稿，点开就能用）。
- 先本地 `http://localhost:8766/app.html` 验证功能正常，再部署，部署内容与本地预览一致。
