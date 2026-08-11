# coomi-stats Worker

匿名打点接收 + 热度聚合。部署在 Cloudflare Workers（免费档，免备案，境外）。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/v1/t` | 接收打点 `{"event": "install_ok", "skill_id": "owner/repo"}`，返回 204 |
| GET | `/stats-app.json` | 聚合结果 `{"generated_at", "events": {event: {skill_id: {7d, 30d, total}}}}` |

- `event` 取值：`install_ok` / `install_fail` / `first_use`
- `skill_id`：catalog id 或 `owner/repo`，长度 ≤128，字符集 `[A-Za-z0-9._/-]`
- 每 IP 每日最多 500 条打点（超限返回 429）
- 所有响应带 `Access-Control-Allow-Origin: *`；`stats-app.json` 带 `Cache-Control: max-age=300`

## 部署

```bash
cd worker
npm install

# 1. 登录 Cloudflare
npx wrangler login

# 2. 创建 KV namespace，把输出的 id 填进 wrangler.toml
npx wrangler kv namespace create TELEMETRY

# 3. 部署（首次部署会生成 https://coomi-stats.<子域>.workers.dev）
npx wrangler deploy
```

## 验证

```bash
# 发三条测试打点
curl -X POST https://coomi-stats.<子域>.workers.dev/v1/t \
  -H "Content-Type: application/json" \
  -d '{"event":"install_ok","skill_id":"test/skill-a"}'
curl -X POST https://coomi-stats.<子域>.workers.dev/v1/t \
  -d '{"event":"install_fail","skill_id":"test/skill-a"}'
curl -X POST https://coomi-stats.<子域>.workers.dev/v1/t \
  -d '{"event":"first_use","skill_id":"test/skill-a"}'

# 查看聚合
curl https://coomi-stats.<子域>.workers.dev/stats-app.json
# 应看到 test/skill-a 的 install_ok.total == 1 等计数
```

## 扩展方向（v2）

- 规模上来后：`scheduled` 每日把 `day:*` 预聚合进 `agg:*`，避免 GET 时全量扫描 KV
- 结构性评分（1~5 星）：新增 `POST /v1/rate`，KV 只存数字不进文本
- 防刷加强：匿名 ID 维度去重（当前只做 IP 限频）
