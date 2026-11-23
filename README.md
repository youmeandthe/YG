# 星露谷中文 MOD 商店 / Stardew Mod Hub

手机优先的 PWA + FastAPI + SQLite。**当前版本 v0.4。**

## 当前已实现
- 中文手机商店界面、搜索、分类、排序、分页、收藏（保存在本机浏览器）
- 安卓兼容性标记（默认 `untested`，不能把“可收录”误当“可运行”）
- SQLite 索引和 API
- CurseForge 官方 API 的全目录分页元数据同步（需自行申请 API Key）
- 可安装 PWA 的 manifest、离线页面缓存（MOD 列表仍需后端）
- 内置 10 款精选 MOD 和 CJB 物品生成器安卓版；兼容性按条目记录，新收录条目默认为待测试

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

GitHub Actions 读取 CurseForge 为星露谷物语返回的全部搜索分页。每页 50 条，遍历到 API 报告的总数，收录具有公开 HTTPS 项目地址的条目。若分页总数不一致、出现重复或超过 CurseForge 单次搜索的 10,000 条上限，任务会保留上次成功的快照。目录按源站更新时间排序。工作流每天运行，也可在 Actions 手动触发。

服务端还提供一次性的管理员接口，用于按页临时补充 SQLite 中的元数据。

在服务端设置环境变量 `CURSEFORGE_API_KEY` 和 `ADMIN_TOKEN`（可参考 `.env.example`，**不会自动读取 .env**）。在本机或服务器上运行：

```bash
curl -X POST 'http://127.0.0.1:8000/api/sync/curseforge?pages=5' -H 'x-admin-token: YOUR_ADMIN_TOKEN'
```

每页最多 50 项。站点只存 MOD 标题、简介、链接等元数据，文件由源站提供。

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

缓存默认写入 `data/zh_translations.json`，按 CurseForge MOD ID 和英文标题、简介的指纹匹配。每完成一条就原子写入缓存，可中断后续跑。同一目录一次运行一个翻译任务。原文变动后，旧缓存会失效，下一批可重新翻译。人工词库始终优先，标题与简介分别回退到原文。页面显示英文原名，并可展开查看简介原文。

GitHub Actions 的 **Sync Stardew MOD Catalog** 每天同步源目录，翻译新增或英文标题、简介有变更的条目，测试通过后把源目录和译文一起提交。**Test Chinese MOD catalog** 验证已提交的数据、API 和真实的 Argos 模型试译。Render 从部署提交读取缓存，应用启动时写入 SQLite。页面访问无需翻译引擎。

Render 若已使用已关联分支的 **On Commit** 自动部署，目录提交会触发更新。若设为 **After CI Checks Pass** 或关闭自动部署，请在 Render 确认发布方式。GitHub Actions 使用默认令牌推送数据提交时，该推送不会再次触发 GitHub Actions。

## 需要进一步开发
- 官方 Nexus Mods GraphQL v2 数据源：须先核实当前可用认证、查询和使用条款，再实现；本版不冒充已接通
- 安卓依赖检测、版本对照、测试报告及下载文件校验
- 直接导入 Launcher：当前仍需手动通过 `Mods → ＋` 选择 ZIP
- 正式部署需 HTTPS、管理员访问保护、限流、监控、备份与合规审查

## API
- `GET /api/mods?q=...&category=...&status=...&page=1&size=24`
- `GET /api/stats` 返回目录数量、标题和简介的翻译覆盖率、完整翻译数、完全未翻译数，以及版本和 Render 提供的部署分支、提交
- `POST /api/sync/curseforge?pages=5`（需 `x-admin-token`）

项目不隶属于 ConcernedApe、SMAPI、Nexus Mods 或 CurseForge。尊重 MOD 作者版权与分发条款。
