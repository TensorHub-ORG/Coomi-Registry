# Coomi 社区注册表

TensorHub 开源组织的社区内容注册表：收录社区用户提交的 **SKILL / MCP / Workflow** 元数据与链接。

**本仓库不托管任何用户内容**——条目只包含名称、描述与仓库链接，内容始终托管在贡献者自己的公开 GitHub 仓库中。Coomi App「市场」页读取本注册表展示条目，App 内安装时直接从贡献者仓库拉取。

## 仓库结构

```
coomi-registry/
├─ registry.json            # 注册表数据（唯一事实来源）
├─ stats-github.json        # 自动生成：GitHub 公开指标（stars/下载量），勿手改
├─ .github/
│  ├─ ISSUE_TEMPLATE/
│  │  └─ submission.yml     # 提交表单（Issues → New Issue）
│  └─ workflows/
│     ├─ validate.yml       # PR 校验：JSON 格式 / 仓库可达 / SKILL.md 存在
│     └─ stats.yml          # 每日拉取 GitHub 公开指标（stars/forks/下载量）
└─ scripts/
   ├─ validate_registry.py  # 校验脚本（本地可跑：python3 scripts/validate_registry.py）
   └─ fetch_stats.py        # 统计脚本（Actions 定时运行）
```

## 数据格式

```json
{
  "version": 1,
  "updated_at": "2026-08-12",
  "skills": [ /* SkillEntry[] */ ],
  "mcps": [ /* MetadataEntry[] */ ],
  "workflows": [ /* MetadataEntry[] */ ]
}
```

条目结构见 [CONTRIBUTING.md](CONTRIBUTING.md#条目字段说明-registryjson)。

## 提交流程

1. 在 [Issues](issues) 用提交表单填写你的技能信息
2. 维护者评估后合入注册表（PR 自动校验 + 人工审核）
3. 合入后 App「市场」页可见，安装量/使用量自动统计

详细要求与审核标准见 [CONTRIBUTING.md](CONTRIBUTING.md)。举报违规条目请联系 `septemc.lhc@gmail.com` 或在 Issues 中提交（标题注明「举报」）。

## 相关项目

- [Coomi-Android](https://github.com/TensorHub-ORG/Coomi-Android)：本地优先 Android 智能体工作环境（SKILL / MCP 工具链）
- [TensorHub](https://github.com/TensorHub-ORG)：开源组织主页

## 许可证

本注册表仓库采用 [Apache-2.0](LICENSE)。注意：条目所链接的第三方仓库遵循其各自的许可证。
