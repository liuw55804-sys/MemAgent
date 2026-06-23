# MemAgent v2 Plan

这是一份版本方向快照，不作为日常迭代草稿反复覆盖。后续如果产品判断发生明显变化，新增 `plan_v3.md`，不要直接把这份文档改成另一个方向。

## 1. 当前判断

MemAgent 的产品主线先做 **coding 导向**：

> 面向 Codex / coding agent 的跨会话工程工作流记忆层，优先解决开发、排查、工具调用、验证流程在不同线程间丢失的问题。

但底层设计不要把自己锁死：

> 底层 memory card 应该是通用 memory substrate，可以表达 coding、learning、life、career 等不同 domain；只是第一阶段只把 coding 场景打透。

一句话：

```text
MemAgent = generic memory substrate
First vertical = coding-agent workflow memory
```

## 2. 为什么主线先做 Coding

先做 coding，不是因为生活记忆不重要，而是因为 coding 场景更容易验证价值。

Coding 场景的收益很明确：

- 新 Codex 线程少找一次 bytedcli / RDS / BAM 入口。
- 少重复一次错误 SQL、错误接口、错误目录。
- 能复用已有 skill，比如覆盖插桩行、任务中心负责人排查。
- 能把上次验证过的工具 recipe、失败路径、数据入口带到新线程。
- 成功标准可衡量：是否少踩坑、是否少解释、是否更快进入有效操作。

通用生活记忆的问题是：

- 记录内容很散。
- 触发场景不明确。
- 评价标准模糊。
- 容易变成“什么都能记，什么都不够好用”的笔记系统。

所以 v2 不做泛化生活记忆产品。v2 做 coding-first，但 schema 留出通用扩展位。

## 3. 不把自己锁死的设计方式

核心是给 memory card 加两层分类：

```yaml
domain: coding | learning | life | career | generic
kind: tool_recipe | skill_route | data_entrypoint | pitfall | verification | checklist | preference | decision | note
```

`domain` 表示这条记忆属于哪个领域。

`kind` 表示这条记忆的结构类型。

这样 coding 场景可以有强结构，生活/学习场景也能先用通用类型承接。

### Coding Memory

```yaml
domain: coding
kind: tool_recipe
topic: RDS 小样本查询
```

### Life Memory

```yaml
domain: life
kind: preference
topic: 租房偏好
```

### Learning Memory

```yaml
domain: learning
kind: checklist
topic: 面试复盘流程
```

### Generic Memory

```yaml
domain: generic
kind: note
topic: 暂时无法分类的记忆
```

## 4. v2 的产品边界

v2 明确做：

- Codex / coding agent 场景。
- bytedcli / MCP / skill route / 数据入口 / 失败路径 / 验证流程记忆。
- 本地私有 memory card。
- 手动或半自动沉淀。
- 召回最有用的一小段上下文给 Codex。

v2 暂不做：

- 通用生活助手。
- 全量个人知识库。
- 自动读取所有聊天软件和浏览器历史。
- 多人同步协作。
- 大而全的 agent 平台。

但 v2 允许底层保存非 coding memory：

- `domain: life`
- `domain: learning`
- `domain: career`
- `domain: generic`

这些先作为兼容能力，不作为主产品卖点。

## 5. v2 Memory Schema

推荐 schema：

```yaml
id: mem_...
domain: coding | learning | life | career | generic
kind: tool_recipe | skill_route | data_entrypoint | pitfall | verification | checklist | preference | decision | note
topic: ...
scope:
  repo: ...
  module: ...
  project: ...
triggers:
  - ...
applies_when:
  - ...
recommended_action:
  type: use_skill | run_tool | inspect_code | query_data | avoid_path | remember_preference | follow_checklist
  target: ...
tool_recipes:
  - name: ...
    command_template: ...
entrypoints:
  - type: rds_table | api | doc | config | skill | file | url
    name: ...
    usage: ...
pitfalls:
  - ...
verification:
  - ...
checklist:
  - ...
preferences:
  - ...
decision:
  context: ...
  choice: ...
  reason: ...
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

实现时不需要一次支持全部字段。v2 最小实现建议只加：

- `domain`
- `kind`
- `recommended_action`
- `entrypoints`
- `verification`

其他字段可以先在 YAML 中保留，不参与逻辑。

## 6. Coding Domain 的 Memory 类型

### 6.1 Skill Route

用途：

> 告诉 Codex：遇到某类任务时，优先触发哪个已有 skill，而不是从零摸索。

例子：

```yaml
domain: coding
kind: skill_route
topic: 任务中心负责人排查
triggers:
  - 任务中心负责人
  - owner
  - col_owner
recommended_action:
  type: use_skill
  target: task-owner-diagnose
next_time_prompt:
  - 遇到任务中心负责人归属问题，先使用 task-owner-diagnose skill，输入 task_id 后再分析 TCC/RDS/历史 owner。
```

价值：

- 让 Codex 少走“重新理解工具生态”的路。
- 对面试也好讲：MemAgent 不只是存文本，还能做 skill routing memory。

### 6.2 Tool Recipe

用途：

> 记录某个 bytedcli / MCP / CLI 命令如何正确调用。

例子：

```yaml
domain: coding
kind: tool_recipe
topic: RDS 小样本查询
tool_recipes:
  - name: 先查小样本
    command_template: "bytedcli rds db query <db> \"<sql with limit>\""
pitfalls:
  - 不要直接全表 group 大 JSON 字段。
```

价值：

- 保存“上次到底怎么跑通的”。
- 对 Codex 最实用，因为它能直接照着 recipe 调工具。

### 6.3 Data Entrypoint

用途：

> 记录某类任务应该先查哪个库、表、接口、环境或文档入口。

例子：

```yaml
domain: coding
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

### 6.4 Pitfall

用途：

> 记录上次失败路径，避免 Codex 重复踩坑。

例子：

```yaml
domain: coding
kind: pitfall
topic: 大表 JSON 聚合超时
pitfalls:
  - 大表 JSON 字段不要直接全表 group。
next_time_prompt:
  - 先 limit 或按 id 范围分段验证，再扩大统计范围。
```

### 6.5 Verification

用途：

> 记录某个改动或排查应该如何验证。

例子：

```yaml
domain: coding
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

## 7. Non-Coding Domain 怎么兼容

非 coding 场景先不要做复杂产品化，只提供通用承接能力。

### Preference

```yaml
domain: life
kind: preference
topic: 租房偏好
preferences:
  - 通勤时间优先于面积。
  - 不接受隔音差的房间。
next_time_prompt:
  - 帮我做租房决策时，优先考虑通勤和隔音。
```

### Checklist

```yaml
domain: learning
kind: checklist
topic: 面试复盘流程
checklist:
  - 记录没答好的问题。
  - 归类成知识缺口、表达问题、项目经历问题。
  - 每类补一个可复述版本。
```

### Decision

```yaml
domain: career
kind: decision
topic: 项目方向选择
decision:
  context: "在 Self-Healing CI 和 MemAgent 之间选择。"
  choice: "先做 MemAgent。"
  reason: "更贴近个人真实痛点，也更有持续动力。"
```

这些类型可以先存在，但 v2 不围绕它们优化召回。

## 8. Codex 如何自动触发 MemAgent

自动触发仍然分阶段。

### 8.1 当前：用户手动触发

```bash
memagent recall "我要查任务中心负责人"
memagent codex "我要查任务中心负责人"
```

特点：

- 简单。
- 可调试。
- 用户要记命令。

### 8.2 近期：AGENTS.md 自然语言触发

在项目或全局 `AGENTS.md` 里写规则：

```text
当用户说“召回一下相关记忆”“之前有没有踩过坑”“用 MemAgent 看看”时，
运行 memagent recall，并把结果作为当前任务参考。

当用户说“记住这个”“沉淀一下”“下次别再踩这个坑”时，
把本轮成功路径、失败路径、工具 recipe 总结为 memagent remember。
```

特点：

- 用户不用记命令。
- Codex 仍然是执行者，MemAgent 是本地工具。
- 适合近期落地。

### 8.3 后续：任务开始前主动 recall

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

### 8.4 未来：MCP / Skill / Hook

更自然的形态：

```text
Codex task starts
  -> MemAgent MCP receives cwd + prompt + tool context
  -> returns top 3 memory patches
  -> Codex decides whether to use skill / tool / avoid pitfall
```

这时 MemAgent 才更像一个真正的 coding-agent memory service。

## 9. 召回“最有用内容”的策略

不能只靠关键词数量。后续要做排序策略。

建议排序信号：

- **Domain match**：当前任务是否是 coding；coding 任务优先召回 `domain: coding`。
- **Scope match**：当前 repo/module 是否匹配。
- **Intent match**：任务是查数据、修代码、跑覆盖率、找 owner，还是调接口。
- **Kind priority**：coding 场景里 `skill_route` 和 `tool_recipe` 通常比普通 `note` 更可执行。
- **Trigger match**：显式 trigger 命中比正文命中更重要。
- **Freshness**：最近验证过的 memory 更可信。
- **Maturity**：`verified` 高于 `draft`，`stale` 降权。
- **Sensitivity**：只在本地私有场景召回内部细节，公开导出时替换。

候选评分可以从简单规则开始：

```text
score =
  domain_match * 6
  + trigger_match * 5
  + scope_match * 4
  + kind_priority
  + body_keyword_match
  + verified_bonus
  - stale_penalty
```

## 10. v2 开发顺序

### Step 1：给 memory card 加 `domain` 和 `kind`

先支持命令：

```bash
memagent remember --domain coding --kind skill_route ...
memagent remember --domain coding --kind tool_recipe ...
memagent remember --domain coding --kind pitfall ...
memagent remember --domain life --kind preference ...
```

关键点：

- 默认 `domain=coding`，因为产品主线是 coding。
- 默认 `kind=note`，保证无法分类的内容也能存。

### Step 2：让 recall 输出按 domain/kind 更清晰

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
templates/coding.skill_route.memory.yaml
templates/coding.tool_recipe.memory.yaml
templates/coding.data_entrypoint.memory.yaml
templates/coding.pitfall.memory.yaml
templates/coding.verification.memory.yaml
templates/generic.note.memory.yaml
templates/life.preference.memory.yaml
templates/learning.checklist.memory.yaml
templates/career.decision.memory.yaml
```

这样你可以手动填真实私有内容，先不依赖 AI。

### Step 4：AGENTS.md 自然语言触发升级

把当前自然语言触发规则整理成一个可安装片段：

```bash
memagent agents-snippet
```

后续可以手动复制到项目 `AGENTS.md`。

### Step 5：再考虑 AI extraction

等 `domain/kind` 稳定后，再让 DeepSeek/Qwen/GLM 做：

- 从长线程抽取 memory。
- 判断 `domain` 和 `kind`。
- 填 `tool_recipes`、`entrypoints`、`pitfalls`、`verification`。
- 压缩 `next_time_prompt`。

这样 AI 会服务于明确 schema，而不是生成一段松散总结。

## 11. v2 成功标准

v2 不要求完全自动化。

只要做到：

- 能保存不同 `domain/kind` 的 memory。
- coding 场景下 bytedcli / skill route / data entrypoint / pitfall 能分开表达。
- recall 输出能优先展示最可执行的 coding 内容。
- generic/life/learning 内容可以存，但不会干扰 coding recall。
- 你能用一两条真实 bytedcli 经验验证“新线程少走弯路”。

就可以进入下一阶段。

## 12. 面试叙事

推荐表述：

> 我没有一开始做通用个人记忆助手，而是先选择 coding agent 作为第一垂直场景，因为它的触发场景、效果指标和用户痛点更清晰。但我在 memory schema 中保留了 domain/kind 两层抽象，使底层能够扩展到学习、生活、职业决策等非 coding 记忆。

这个说法比“我做了一个 RAG”更有区分度，也能解释为什么当前项目看起来 coding-first，但不是架构上只能做 coding。
