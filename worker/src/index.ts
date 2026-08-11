/**
 * coomi-stats — 匿名打点接收 + 聚合（Cloudflare Worker）
 *
 * 路由：
 *   POST /v1/t            接收一条事件 {event, skill_id, ts}
 *   GET  /stats-app.json  返回聚合计数（近7天 / 近30天 / 累计）
 *
 * 存储（Cloudflare KV）：
 *   day:{YYYY-MM-DD}:{event}:{skill_id}  -> 当日计数
 *   total:{event}:{skill_id}             -> 累计计数
 *   rl:{ip}:{YYYY-MM-DD}                 -> 每 IP 每日打点数（限频）
 *
 * 隐私说明：KV 中不存任何身份信息。事件中的匿名客户端 ID 仅用于本地去重，
 * 不会写入 KV；计数完全按 skill_id 聚合。
 *
 * 注意：KV 读-改-写是最终一致模型，极端并发下可能漏记少量计数。
 * 对社区体量（每天几百到几千次打点）影响可忽略；规模上来后
 * 可迁移到 D1 或加 scheduled 预聚合（见下方 scheduled 钩子）。
 */

interface Env {
  TELEMETRY: KVNamespace;
}

const ALLOWED_EVENTS = new Set(["install_ok", "install_fail", "first_use"]);
// catalog id（如 frontend-design）或 owner/repo（如 owner/repo-b）。
// 必须以字母数字开头，最多一段斜杠，拒绝 .. 穿越类输入。
const SKILL_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*(?:\/[A-Za-z0-9][A-Za-z0-9._-]*)?$/;
const DAY_CAP = 500; // 每 IP 每日最多 500 条打点
const CACHE_SECONDS = 300;

function dayKey(date = new Date()): string {
  return date.toISOString().slice(0, 10);
}

function cors(response: Response): Response {
  const headers = new Headers(response.headers);
  headers.set("Access-Control-Allow-Origin", "*");
  headers.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  headers.set("Access-Control-Allow-Headers", "Content-Type");
  return new Response(response.body, { status: response.status, headers });
}

async function increment(kv: KVNamespace, key: string): Promise<void> {
  const current = Number((await kv.get(key, "text")) ?? "0");
  await kv.put(key, String(current + 1));
}

async function ingest(request: Request, env: Env): Promise<Response> {
  if (request.method === "OPTIONS") return cors(new Response(null, { status: 204 }));

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return cors(new Response("invalid json", { status: 400 }));
  }

  // 兼容三种格式：批量 `{events: [...]}`、裸数组、单事件对象 `{event, skill_id}`。
  // 批量格式由 App 端缓冲后合并上报（减少请求数）；单对象格式方便 curl 手动测试。
  const container = body as { events?: unknown };
  let rawEvents: unknown[];
  if (Array.isArray(container.events)) {
    rawEvents = container.events;
  } else if (Array.isArray(body)) {
    rawEvents = body;
  } else {
    rawEvents = [body];
  }
  if (rawEvents.length === 0 || rawEvents.length > 100) {
    return cors(new Response("expected 1-100 events", { status: 400 }));
  }

  // 先整体校验，再写入：避免批量中途失败导致部分计数（客户端会整批重试，可能重复计数）。
  const events: Array<{ event: string; skillId: string }> = [];
  for (const raw of rawEvents) {
    const ev = raw as { event?: unknown; skill_id?: unknown };
    const event = ev.event;
    const skillId = ev.skill_id;
    if (typeof event !== "string" || !ALLOWED_EVENTS.has(event)) {
      return cors(new Response("unknown event", { status: 400 }));
    }
    if (typeof skillId !== "string" || !SKILL_ID_RE.test(skillId)) {
      return cors(new Response("invalid skill_id", { status: 400 }));
    }
    events.push({ event, skillId });
  }

  const ip = (request.headers.get("CF-Connecting-IP") ?? "unknown").slice(0, 64);
  const today = dayKey();
  const rlKey = `rl:${ip}:${today}`;
  const used = Number((await env.TELEMETRY.get(rlKey, "text")) ?? "0");
  if (used + events.length > DAY_CAP) {
    return cors(new Response("rate limited", { status: 429 }));
  }
  await env.TELEMETRY.put(rlKey, String(used + events.length));

  for (const { event, skillId } of events) {
    await increment(env.TELEMETRY, `day:${today}:${event}:${skillId}`);
    await increment(env.TELEMETRY, `total:${event}:${skillId}`);
  }
  return cors(new Response(null, { status: 204 }));
}

async function listAll(kv: KVNamespace, prefix: string): Promise<string[]> {
  const keys: string[] = [];
  let cursor: string | undefined;
  do {
    const page = await kv.list({ prefix, cursor });
    keys.push(...page.keys.map((k) => k.name));
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  return keys;
}

async function aggregateStats(env: Env): Promise<Response> {
  const totals: Record<string, Record<string, number>> = {};
  const recent: Record<string, Record<string, { d7: number; d30: number }>> = {};

  // 累计：total:{event}:{skill_id}
  for (const key of await listAll(env.TELEMETRY, "total:")) {
    const [, event, skillId] = key.split(":");
    const n = Number((await env.TELEMETRY.get(key, "text")) ?? "0");
    (totals[event] ??= {})[skillId] = n;
  }

  // 近 7 / 30 天：day:{YYYY-MM-DD}:{event}:{skill_id}
  const now = new Date();
  const cutoff7 = new Date(now.getTime() - 7 * 86400_000).toISOString().slice(0, 10);
  const cutoff30 = new Date(now.getTime() - 30 * 86400_000).toISOString().slice(0, 10);
  for (const key of await listAll(env.TELEMETRY, "day:")) {
    const [, day, event, skillId] = key.split(":");
    if (day < cutoff30) continue;
    const n = Number((await env.TELEMETRY.get(key, "text")) ?? "0");
    const slot = (recent[event] ??= {});
    const agg = (slot[skillId] ??= { d7: 0, d30: 0 });
    agg.d30 += n;
    if (day >= cutoff7) agg.d7 += n;
  }

  // 合并成单一结构，按 event -> skill_id 输出
  const events: Record<
    string,
    Record<string, { "7d": number; "30d": number; total: number }>
  > = {};
  const allEvents = new Set([...Object.keys(totals), ...Object.keys(recent)]);
  for (const event of allEvents) {
    const ids = new Set([...Object.keys(totals[event] ?? {}), ...Object.keys(recent[event] ?? {})]);
    events[event] = {};
    for (const skillId of ids) {
      events[event][skillId] = {
        "7d": recent[event]?.[skillId]?.d7 ?? 0,
        "30d": recent[event]?.[skillId]?.d30 ?? 0,
        total: totals[event]?.[skillId] ?? 0,
      };
    }
  }

  const payload = JSON.stringify({
    generated_at: now.toISOString(),
    events,
  });

  return cors(
    new Response(payload, {
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": `public, max-age=${CACHE_SECONDS}`,
      },
    })
  );
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === "/v1/t") {
      return ingest(request, env);
    }
    if (request.method === "GET" && url.pathname === "/stats-app.json") {
      return aggregateStats(env);
    }
    if (request.method === "OPTIONS") {
      return cors(new Response(null, { status: 204 }));
    }
    return cors(new Response("not found", { status: 404 }));
  },

  // 预留：规模上来后可在此每日预聚合 day:* 键，避免 GET 时全量扫描。
  async scheduled(_controller: ScheduledController, env: Env): Promise<void> {
    void env; // 暂无预聚合，见 README「扩展方向」
  },
};
