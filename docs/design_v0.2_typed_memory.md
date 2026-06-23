# MemAgent v0.2 Typed Memory Design

本文档是 v0.2 的实现设计，不是长期产品愿景。长期方向见 [plan_v2.md](plan_v2.md)。

v0.2 只做一件小而关键的事：

> 给 memory card 增加 `domain` 和 `kind`，让 MemAgent 从“存一句话”走向“可分类的 workflow memory”。

## 1. 设计目标

当前 v0.1 的 memory card 只有通用字段，`remember` 会把用户输入直接塞进 `pitfalls` 和 `source_note`。这能验证最小闭环，但无法区分：

- bytedcli 命令 recipe
- skill 路由建议
- 数据入口提示
- 失败路径
- 验证流程
- 日常生活偏好

v0.2 的目标是引入最小分类能力：

```yaml
domain: coding
kind: note
```

并让用户可以手动指定：

```bash
memagent remember --domain coding --kind tool_recipe "..."
memagent remember --domain coding --kind skill_route "..."
memagent remember --domain life --kind preference "..."
```

## 2. 非目标

v0.2 不做：

- LLM API 接入。
- 自动从 Codex 长线程抽取 memory。
- 完整 YAML 解析器。
- BM25 / 向量召回。
- MCP server。
- 自动写 AGENTS.md。
- 完整生活记忆产品。

这版先把结构埋进去，让后续召回排序和 AI extraction 有稳定目标。

## 3. 字段定义

### 3.1 `domain`

表示 memory 属于哪个领域。

允许值：

```text
coding
learning
life
career
generic
```

默认值：

```text
coding
```

原因：

- 当前产品主线是 coding agent。
- 用户不传参数时，最可能是在 Codex 工程场景里记忆。
- 仍然允许 `life/learning/career/generic` 承接非 coding 内容。

### 3.2 `kind`

表示 memory 的结构类型。

允许值：

```text
note
tool_recipe
skill_route
data_entrypoint
pitfall
verification
checklist
preference
decision
workflow
```

默认值：

```text
note
```

原因：

- 默认 `note` 不会强迫用户一开始就分类。
- coding 场景可以逐步使用 `tool_recipe/skill_route/data_entrypoint/pitfall/verification`。
- 非 coding 场景可以使用 `checklist/preference/decision`。

## 4. Memory Card 输出格式

v0.2 写出的 memory card 应该从：

```yaml
id: "mem_..."
created_at: "..."
topic: "..."
scope:
  repo: "..."
```

变成：

```yaml
id: "mem_..."
created_at: "..."
domain: "coding"
kind: "note"
topic: "..."
scope:
  repo: "..."
```

先只新增 `domain/kind` 两个顶层字段。

暂时不调整已有字段：

- `stable_facts`
- `tool_recipes`
- `pitfalls`
- `next_time_prompt`
- `agents_md_suggestion`
- `sensitivity`
- `source_note`

这样可以最大限度减少 v0.2 的代码风险。

## 5. CLI 设计

### 5.1 `remember`

新增参数：

```bash
--domain
--kind
```

示例：

```bash
memagent remember \
  --domain coding \
  --kind tool_recipe \
  --topic "RDS 小样本查询" \
  --trigger "RDS" \
  --trigger "bytedcli" \
  "RDS 大表统计先跑小样本，不要直接全表 group。"
```

默认行为：

```bash
memagent remember "some note"
```

等价于：

```bash
memagent remember --domain coding --kind note "some note"
```

### 5.2 `recall`

v0.2 暂不新增筛选参数。

原因：

- 第一版先验证 memory card 能写出 domain/kind。
- recall 仍然用关键词 baseline。
- 后续再考虑 `--domain coding`、`--kind tool_recipe` 或自动 intent 检测。

但 recall 输出中应该展示分类：

```text
- Memory: RDS 小样本查询 [coding/tool_recipe]
```

这样用户一眼能看出召回的是什么类型。

同时收紧一个 v0.1 的噪声点：召回必须先命中用户 query，再给 repo scope 加分。不能只因为 memory 属于当前 repo 就被召回，否则 `life/preference` 和 `coding/tool_recipe` 很容易在同一个项目目录里互相干扰。

中文 query 先用轻量 n-gram 兜底：对中文连续片段生成 2-4 字短语，避免 `帮我判断租房偏好` 不能命中 `租房偏好`。这不是最终语义检索，只是 v0.2 的可解释 baseline。

### 5.3 `codex`

`codex` 使用 `compose_context()` 的输出，因此会自然继承 recall 中的 `[domain/kind]` 展示。

不新增 CLI 参数。

## 6. 代码改动范围

### 6.1 `src/memagent/cli.py`

改动：

- 给 `remember` parser 增加 `--domain`。
- 给 `remember` parser 增加 `--kind`。
- 调用 `store.remember(...)` 时传入 `domain=args.domain` 和 `kind=args.kind`。

不改：

- `recall` 参数。
- `codex` 参数。
- `normalize_remainder()`。

### 6.2 `src/memagent/memory.py`

改动：

- `MemoryMatch` 增加 `domain` 和 `kind` 字段。
- `MemoryStore.remember(...)` 增加 `domain` 和 `kind` 参数。
- `_render_memory_card(...)` 写出 `domain` 和 `kind`。
- `recall(...)` 从 raw YAML 中抽取 `domain` 和 `kind`。
- `compose_context(...)` 展示 `Memory: title [domain/kind]`。

新增 helper：

```python
def _normalize_domain(value: str | None) -> str
def _normalize_kind(value: str | None) -> str
```

行为：

- `None` 或空字符串使用默认值。
- 不在允许集合内的值报错，或先保守降级为默认值。

v0.2 建议选择“报错”：

```text
invalid domain: xxx
```

原因：

- 手动输入阶段，错误越早暴露越好。
- 否则 memory card 会出现拼写不同的 kind，后续排序很痛苦。

### 6.3 `tests/`

改动：

- 更新 `test_memory_store.py`，验证默认写出 `domain: "coding"` 和 `kind: "note"`。
- 新增测试：指定 `domain=life`、`kind=preference` 能写入并召回。
- 新增测试：召回输出包含 `[coding/tool_recipe]`。
- 新增测试：非法 `domain/kind` 报错。

## 7. Validation 规则

允许的 domain：

```python
ALLOWED_DOMAINS = {
    "coding",
    "learning",
    "life",
    "career",
    "generic",
}
```

允许的 kind：

```python
ALLOWED_KINDS = {
    "note",
    "tool_recipe",
    "skill_route",
    "data_entrypoint",
    "pitfall",
    "verification",
    "checklist",
    "preference",
    "decision",
    "workflow",
}
```

Normalization：

- 去掉首尾空格。
- 转小写。
- 把 `-` 替换成 `_`。

例如：

```text
Tool-Recipe -> tool_recipe
```

## 8. 向后兼容

v0.1 已有 memory card 没有 `domain/kind`。

v0.2 recall 读取旧 card 时：

```text
domain = coding
kind = note
```

原因：

- 不破坏旧 memory。
- 产品主线默认 coding。
- 旧 card 本质上就是自由文本 note。

## 9. 手动自测脚本

写入 coding memory：

```bash
PYTHONPATH=src python -m memagent.cli --home ./local_memory_demo remember \
  --domain coding \
  --kind tool_recipe \
  --topic "RDS 小样本查询" \
  --trigger "RDS" \
  --trigger "bytedcli" \
  "RDS 大表统计先跑小样本，不要直接全表 group。"
```

写入 life memory：

```bash
PYTHONPATH=src python -m memagent.cli --home ./local_memory_demo remember \
  --domain life \
  --kind preference \
  --topic "租房偏好" \
  --trigger "租房" \
  "租房决策里通勤和隔音优先级高于面积。"
```

召回：

```bash
PYTHONPATH=src python -m memagent.cli --home ./local_memory_demo recall \
  "我要查 RDS 大表统计"
```

期望输出包含：

```text
- Memory: RDS 小样本查询 [coding/tool_recipe]
```

## 10. v0.2 完成标准

完成标准：

- `remember` 支持 `--domain` 和 `--kind`。
- 新 memory card 写出 `domain/kind`。
- 旧 memory card 不带 `domain/kind` 时仍可 recall。
- recall / codex 输出展示 `[domain/kind]`。
- 非法 domain/kind 有测试保护。
- README 和 technical walkthrough 更新。
- `compileall` 和 `unittest` 通过。

## 11. 后续延伸

v0.2 完成后，再考虑：

- `--domain` / `--kind` 作为 recall 筛选条件。
- 对不同 kind 采用不同 context composer。
- 给 `tool_recipe`、`skill_route`、`data_entrypoint` 做专门模板。当前已先提供 `templates/` 下的 copy-and-fill YAML 模板，后续可再接 CLI 生成。
- 让 LLM extraction 判断 domain/kind。
- AGENTS.md 自然语言触发调用 `remember --domain coding --kind pitfall`。
