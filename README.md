# 星露谷中文 MOD 商店 / Stardew Mod Hub

手机优先的 PWA + FastAPI + SQLite。**当前版本 v0.4。**

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

## v0.4 批量中文翻译

人工词库优先。其余 CurseForge 条目可用 Argos Translate 在本机批量翻译成简体中文，无需 API 密钥。首次安装模型需要联网，安装后翻译在本机完成。翻译范围为目录标题和简介。

```bash
# 仅应用人工词库，无额外依赖
python scripts/translate_catalog.py

# 安装免费翻译引擎并下载英译中模型
python -m pip install 'argostranslate==1.11.0'
python scripts/translate_catalog.py --engine argos --install-model --limit 30

# 后续批次复用已安装的模型和缓存
python scripts/translate_catalog.py --engine argos --limit 30
```

缓存默认写入 `data/zh_translations.json`。同一目录一次只运行一个翻译任务。每完成一条就写入缓存，可中断后续跑。标题或简介修改后，服务端会忽略旧译文，下一批可重新翻译。更新缓存后重启服务，中文搜索会覆盖译文和原有别名。

GitHub Actions 的 **Translate MOD catalog to Chinese** 工作流会在 `upgrade-v0.4-zh` 分支的翻译代码更新时试跑 3 条。工作流进入默认分支后可在 Actions 页手动选择分支和批量上限。后续运行复用该分支的 Actions 缓存。每次运行可下载 `modhub-zh-translations`，审阅后将其中的 `zh_translations.json` 放到应用的 `data/` 目录或经提交纳入版本控制。Actions 缓存和产物受平台保留规则限制，长期保留请保存该 JSON。翻译工作流只读取仓库。

## 需要进一步开发
- 官方 Nexus Mods GraphQL v2 数据源：须先核实当前可用认证、查询和使用条款，再实现；本版不冒充已接通
- 安卓依赖检测、版本对照、测试报告及下载文件校验
- 直接导入 Launcher：当前仍需手动通过 `Mods → ＋` 选择 ZIP
- 正式部署需 HTTPS、管理员访问保护、限流、监控、备份与合规审查

## API
- `GET /api/mods?q=...&category=...&status=...&page=1&size=24`
- `GET /api/stats`
- `POST /api/sync/curseforge?pages=5`（需 `x-admin-token`）

项目不隶属于 ConcernedApe、SMAPI、Nexus Mods 或 CurseForge。尊重 MOD 作者版权与分发条款。
