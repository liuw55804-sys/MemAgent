# MemAgent Next Iteration Plan

当前 `v0.1.0-mvp` 已经验证了最小闭环：

```text
remember -> local memory card -> recall -> codex prompt prefix
```

下一阶段不要急着做“大而全”的 AI agent。最重要的问题是：

> 当 Codex 面对一个真实任务时，MemAgent 如何判断该召回哪一类记忆，并把最有用的一小段交给 Codex？

## 1. v0.2 核心目标

`v0.2` 建议聚焦两个能力：

```text
1. 记忆类型分层
2. 召回结果更可执行
```

也就是说，先让 memory card 不只是“存一句话”，而是能表达：

- 这是一个 skill 路由建议。
- 这是一个 bytedcli 工具 recipe。
- 这是一个库表/API 入口提示。
- 这是一个失败路径。
- 这是一个验证方式。
- 这是一个可以升格到 AGENTS.md 的稳定规则。

## 2. 面向 bytedcli 的 Memory 类型

你最常用的是 bytedcli / MCP，因此 memory 类型要围绕真实使用方式设计。

### 2.1 Skill Route Memory

用途：

> 告诉 Codex：遇到某类任务时，优先触发某个已有 skill，而不是从零摸索。

例子：

```yaml
kind: skill_route
topic: 任务中心负责人排查
triggers:
  - 任务中心负责人
  - owner
  - col_owner
recommended_skill: task-owner-diagnose
next_time_prompt:
  - 遇到任务中心负责人归属问题，先使用 task-owner-diagnose skill，输入 task_id 后再分析 TCC/RDS/历史 owner。
```

价值：

- 让 Codex 少走“重新理解工具生态”的路。
- 对面试也好讲：MemAgent 不只是存文本，还能做 tool/skill routing memory。

### 2.2 Tool Recipe Memory

用途：

> 记录某个 bytedcli 命令如何正确调用。

例子：

```yaml
kind: tool_recipe
topic: RDS 小样本查询
tool: bytedcli
tool_recipes:
  - name: 先查小样本
    command_template: "bytedcli rds db query <db> \"<sql with limit>\""
pitfalls:
  - 不要直接全表 group 大 JSON 字段。
```

价值：

- 保存“上次到底怎么跑通的”。
- 对 Codex 最实用，因为它能直接照着 recipe 调工具。

### 2.3 Data Entrypoint Memory

用途：

> 记录某类任务应该先查哪个库、表、接口、环境或文档入口。

例子：

```yaml
kind: data_entrypoint
topic: 某类归因任务排查入口
entrypoints:
  - type: rds_table
    name: "<local-private-table-name>"
    usage: "先确认任务状态和人工提交标签。"
  - type: api
    name: "<local-private-api-path>"
    usage: "用于回放单条任务。"
sensitivity:
  level: internal
  exportable: false
```

价值：

- 解决“换个线程又要重新找库表/API”的痛点。
- 本地私有 memory 可以保留真实入口，但公开 demo 要替换成占位符。

### 2.4 Pitfall Memory

用途：

> 记录上次失败路径，避免 Codex 重复踩坑。

例子：

```yaml
kind: pitfall
topic: 大表 JSON 聚合超时
pitfalls:
  - 大表 JSON 字段不要直接全表 group。
next_time_prompt:
  - 先 limit 或按 id 范围分段验证，再扩大统计范围。
```

价值：

- 这类 memory 通常最容易立即见效。
- 召回后直接影响 Codex 的第一步行动。

### 2.5 Verification Memory

用途：

> 记录某个改动或排查应该如何验证。

例子：

```yaml
kind: verification
topic: 覆盖插桩行验证
triggers:
  - 覆盖率
  - 插桩行
  - 自测
verification:
  - 先定位未覆盖行。
  - 再设计最小请求体触发分支。
  - 最后跑对应 self-test 或覆盖率命令。
```

价值：

- 让 Codex 从“写代码”走到“证明改动有效”。
- 也适合和已有 coverage skill 配合。

## 3. v0.2 推荐 Memory Schema

当前 v0.1 的 card 是通用模板。v0.2 可以逐步演进成：

```yaml
id: mem_...
kind: tool_recipe | skill_route | data_entrypoint | pitfall | verification | workflow
topic: ...
scope:
  repo: ...
  module: ...
triggers:
  - ...
applies_when:
  - ...
recommended_action:
  type: use_skill | run_tool | inspect_code | query_data | avoid_path
  target: ...
tool_recipes:
  - name: ...
    command_template: ...
entrypoints:
  - type: rds_table | api | doc | config | skill
    name: ...
    usage: ...
pitfalls:
  - ...
verification:
  - ...
next_time_prompt:
  - ...
sensitivity:
  level: local | internal | exportable
  exportable: false
status:
  maturity: draft | verified | stale
  promotion_candidate: false
source_note: |
  ...
```

不需要一次实现全部字段。v0.2 可以先加：

- `kind`
- `recommended_action`
- `entrypoints`
- `verification`

## 4. Codex 如何自动触发 MemAgent

自动触发有几个阶段，不要一步到位。

### 4.1 现在：用户手动触发

用户直接运行：

```bash
memagent recall "我要查任务中心负责人"
memagent codex "我要查任务中心负责人"
```

特点：

- 简单。
- 可调试。
- 但用户要记命令。

### 4.2 下一步：AGENTS.md 自然语言触发

在项目或全局 `AGENTS.md` 里写规则：

```text
当用户说“召回一下相关记忆”“之前有没有踩过坑”“用 MemAgent 看看”时，
运行 memagent recall，并把结果作为当前任务参考。

当用户说“记住这个”“沉淀一下”“下次别再踩这个坑”时，
把本轮成功路径、失败路径、工具 recipe 总结为 memagent remember。
```

特点：

- 用户不用记命令。
- Codex 仍然是执行者，MemAgent 只是本地工具。
- 适合近期落地。

### 4.3 再下一步：任务开始前的主动 recall

当用户发起任务时，Codex 可以先判断：

```text
这个任务是否涉及已知工具、skill、repo、数据入口或历史坑？
```

如果是，再调用：

```bash
memagent recall "<user prompt>"
```

判断依据：

- prompt 中出现 `bytedcli`、RDS、BAM、覆盖率、任务中心负责人等关键词。
- 当前 cwd/repo 命中已有 memory scope。
- 最近修改文件命中某个模块。
- AGENTS.md 中声明当前项目适合使用 MemAgent。

### 4.4 未来：MCP / Skill / Hook

更自然的形态：

```text
Codex task starts
  -> MemAgent MCP receives cwd + prompt + tool context
  -> returns top 3 memory patches
  -> Codex decides whether to use skill / tool / avoid pitfall
```

这时 MemAgent 才更像一个真正的 coding-agent memory service。

## 5. 召回“最有用内容”的策略

不能只靠关键词数量。后续要做排序策略。

建议排序信号：

- **Scope match**：当前 repo/module 是否匹配。
- **Intent match**：任务是查数据、修代码、跑覆盖率、找 owner，还是调接口。
- **Kind priority**：skill_route 和 tool_recipe 通常比普通 note 更可执行。
- **Trigger match**：显式 trigger 命中比正文命中更重要。
- **Freshness**：最近验证过的 memory 更可信。
- **Maturity**：`verified` 高于 `draft`，`stale` 降权。
- **Sensitivity**：只在本地私有场景召回内部细节，公开导出时替换。

候选评分可以从简单规则开始：

```text
score =
  trigger_match * 5
  + scope_match * 4
  + kind_priority
  + body_keyword_match
  + verified_bonus
  - stale_penalty
```

## 6. 推荐 v0.2 开发顺序

### Step 1：给 memory card 加 `kind`

先支持命令：

```bash
memagent remember --kind skill_route ...
memagent remember --kind tool_recipe ...
memagent remember --kind pitfall ...
```

这是最小但很关键的一步。

### Step 2：让 recall 输出按 kind 更清晰

比如：

```text
[MemAgent recalled context]
- Skill route: 遇到任务中心负责人问题，优先使用 task-owner-diagnose。
- Tool recipe: bytedcli 查询前先确认库表和小样本。
- Pitfall: 不要直接全表 group 大 JSON 字段。
```

### Step 3：支持本地 demo memory 模板

提供几条可复制模板：

```text
skill_route.template.yaml
tool_recipe.template.yaml
data_entrypoint.template.yaml
pitfall.template.yaml
verification.template.yaml
```

这样你可以手动填真实私有内容，先不依赖 AI。

### Step 4：AGENTS.md 自然语言触发升级

把当前自然语言触发规则整理成一个可安装片段：

```bash
memagent agents-snippet
```

后续可以手动复制到项目 `AGENTS.md`。

### Step 5：再考虑 AI extraction

等 memory 类型稳定后，再让 DeepSeek/Qwen/GLM 做：

- 从长线程抽取 memory。
- 判断 `kind`。
- 填 `tool_recipes`、`entrypoints`、`pitfalls`。
- 压缩 `next_time_prompt`。

这样 AI 会服务于明确 schema，而不是生成一段松散总结。

## 7. 这一阶段的成功标准

v0.2 不要求完全自动化。

只要做到：

- 能保存不同 `kind` 的 memory。
- bytedcli / skill route / data entrypoint / pitfall 能分开表达。
- recall 输出能优先展示最可执行的内容。
- 你能用一两条真实 bytedcli 经验验证“新线程少走弯路”。

就可以进入下一阶段。

