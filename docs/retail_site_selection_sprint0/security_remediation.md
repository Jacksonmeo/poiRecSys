# GeoAgent Sprint 0 安全整改说明

## 整改结论

本轮已移除仓库代码中的非空 API Key、数据库密码和默认连接凭据。应用与旧数据导入脚本统一从环境变量读取敏感配置；示例文件只保留空值，不包含可用凭据。本轮没有在日志、测试输出或文档中复述任何真实密钥。

## 变更明细

| 文件 | 整改内容 |
|---|---|
| `backend/app/core/config.py` | `DATABASE_URL` 改为必填环境配置；LLM 默认切换为 `mock`；LLM endpoint、API Key 和模型默认值置空；固定从 `backend/.env` 加载本地配置。 |
| `backend/.env.example` | 新增安全模板；`DATABASE_URL`、`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 均为空。 |
| `Utils/seperate.py` | 删除硬编码数据库主机、端口、库名、用户名和密码；只接受进程环境中的 `DATABASE_URL`，缺失时明确失败。 |
| `backend/tests/conftest.py` | 删除带用户名和密码的测试数据库兜底连接；要求 `TEST_DATABASE_URL` 或 `backend/.env` 中的 `DATABASE_URL`。测试运行时构造的 DSN 只来自环境，不写入日志。 |
| `README.md`、`backend/README.md`、`docs/poi_database_migration.md` | 数据库连接示例改为空值，避免把连接凭据写成可复制默认配置。 |
| `.gitignore` | 继续忽略本地 `.env`；只放行 `Utils/seperate.py`，原始大体量 CSV 仍被忽略。 |

## 核验方式

- 扫描受版本控制范围内的代码和文档中的 API Key、带密码 DSN、密码赋值等高风险模式；排除 `.git`、依赖目录、本地 `.env` 和原始 CSV。
- 扫描后只剩测试夹具中“从环境 URL 拆分后构造测试库 DSN”的运行时代码；不存在非空凭据默认值，也不会输出 DSN。
- 完整后端测试与前端 lint/build 均通过。

## 必须人工处理

本轮没有重写 Git 历史。曾经提交到 `backend/app/core/config.py` 的 LLM 密钥以及硬编码数据库凭据应视为已经暴露，必须由具备供应商和数据库权限的人员执行：

1. 立即撤销并轮换已暴露的 LLM 密钥。
2. 若硬编码数据库密码曾在任何真实环境复用，立即轮换对应账户密码，并检查异常访问记录。
3. 在团队协调和备份完成后，使用 `git filter-repo` 或等效工具清理历史，再强制更新远端分支和所有克隆。
4. 在 CI/CD 或密钥管理系统中注入运行时变量，不把生产值放入 `.env.example`、日志、测试快照或文档。

仅删除当前工作树中的密钥不能使历史提交中的值失效，因此“轮换”是必要动作，不应等待历史清理完成。
