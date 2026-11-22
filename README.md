# 星露谷中文 MOD 商店 / Stardew Mod Hub

手机优先的 PWA + FastAPI + SQLite。**这是可运行的第一版，不是已部署的在线商店。**

## 当前已实现
- 中文手机商店界面、搜索、分类、排序、分页、收藏（保存在本机浏览器）
- 安卓兼容性标记（默认 `untested`，不能把“可收录”误当“可运行”）
- SQLite 索引和 API
- CurseForge 官方 API 的分页元数据同步（需自行申请 API Key）
- 可安装 PWA 的 manifest、离线页面缓存（MOD 列表仍需后端）
- 初始示例目录 10 款，GMCM 标记为用户设备上已验证；其他均待测试

## 运行（电脑或云服务器）

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。同一 Wi-Fi 下手机可通过电脑局域网 IP 访问，但 PWA 的“安装到桌面”与 Service Worker 通常需要 HTTPS（localhost 例外）。部署到 HTTPS 域名后可正常安装。

## 自动收录 CurseForge

在服务端设置环境变量 `CURSEFORGE_API_KEY` 和 `ADMIN_TOKEN`（可参考 `.env.example`，**不会自动读取 .env**）。在本机或服务器上运行：

```bash
curl -X POST 'http://127.0.0.1:8000/api/sync/curseforge?pages=5' -H 'x-admin-token: YOUR_ADMIN_TOKEN'
```

每页最多 50 项。可通过服务器 cron / 定时任务每天调用一次。**同步是否成功取决于 API Key 权限、平台接口和正确的游戏 ID；未申请密钥时不会自动变成海量目录。** 本程序只存 MOD 标题、简介、链接等元数据，不镜像文件，不绕过登录/授权或平台下载限制。

## 需要进一步开发
- 官方 Nexus Mods GraphQL v2 数据源：须先核实当前可用认证、查询和使用条款，再实现；本版不冒充已接通
- 中文翻译：目前只对种子条目提供中文描述，自动同步条目可能仍是英文
- 安卓依赖检测、版本对照、测试报告及下载文件校验
- 直接导入 Launcher：当前仍需手动通过 `Mods → ＋` 选择 ZIP
- 正式部署需 HTTPS、管理员访问保护、限流、监控、备份与合规审查

## API
- `GET /api/mods?q=...&category=...&status=...&page=1&size=24`
- `GET /api/stats`
- `POST /api/sync/curseforge?pages=5`（需 `x-admin-token`）

项目不隶属于 ConcernedApe、SMAPI、Nexus Mods 或 CurseForge。尊重 MOD 作者版权与分发条款。
