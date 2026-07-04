# MemAgent v0.3 Codex Integration Design

v0.3 的目标不是继续扩展 memory schema，而是把 MemAgent 放回真实使用场景：

> 用户在 Codex 里用自然语言说“召回一下相关记忆”或“沉淀一下”，Codex 能知道如何调用 MemAgent。

## 1. 背景

v0.1 验证了最小闭环：

```text
remember -> local memory card -> recall -> codex prompt prefix
```

v0.2 增加了轻量类型字段：

```yaml
domain: coding
kind: tool_recipe
```

但现在仍然有一个关键缺口：

> 用户必须记住 `memagent recall` / `memagent remember` 命令，Codex 不会自然触发 MemAgent。

v0.3 就解决这个入口问题。

## 2. 设计目标

v0.3 做三件事：

```text
1. 提供可复制到 AGENTS.md 的 MemAgent 触发规则
2. 提供命令生成这段规则，避免用户手写
3. 明确 Codex 触发 recall / remember 的工作流
```

最终用户体验应该是：

```text
用户：召回一下相关记忆，看看之前有没有 bytedcli 的坑
Codex：调用 memagent recall，并把结果作为当前任务参考

用户：沉淀一下，下次不要再走这个 RDS 全表 JSON group 的坑
Codex：总结一条短 memory，调用 memagent remember
```

## 3. 非目标

v0.3 不做：

- MCP server。
- Codex Hook 自动监听。
- 自动读取所有 Codex 历史线程。
- LLM extraction。
- 多轮交互式记忆编辑。
- 大规模 recall 排序优化。
- 自动修改用户仓库 `AGENTS.md`。

这版只做“让 Codex 知道怎么调用 MemAgent”的最小集成。

## 4. 为什么不用模板路线

v0.3 不做 copy-and-fill YAML templates。

原因：

- 模板要求用户离开 Codex 语境去手工维护文件。
- 当前最重要的是 Codex 内容流里的 recall 和 remember。
- 复杂字段应等 Codex/AI extraction 能自动填时再扩展。

因此 v0.3 的核心资产不是 YAML 模板，而是 **Codex instruction snippet**。

## 5. 用户触发语义

### 5.1 Recall 触发

用户说这些话时，Codex 应调用 recall：

```text
召回一下相关记忆
先看看之前有没有相关经验
有没有以前踩过类似坑
用 MemAgent 看看
查一下 MemAgent memory
```

Codex 执行：

```bash
PYTHONPATH=<memagent-src> python -m memagent.cli recall "<user task>" --show-sources --show-reasons
```

然后：

- 把召回结果作为 hints。
- 用 `--show-sources` 和 `--show-reasons` 显示来源与命中原因，方便调试和演示。
- 不把 memory 当作 source of truth。
- 继续检查真实代码、命令输出、数据库 schema、文档。

### 5.2 Remember 触发

用户说这些话时，Codex 应调用 remember：

```text
记住这个
沉淀一下
下次别再踩这个坑
把这次排查做成 memory
保存为 MemAgent 记忆
```

Codex 先总结一条短 memory，再执行：

```bash
PYTHONPATH=<memagent-src> python -m memagent.cli remember \
  --domain coding \
  --kind <kind> \
  --topic "<short topic>" \
  --trigger "<keyword>" \
  "<short actionable memory>"
```

`kind` 选择规则：

```text
tool_recipe      可复用命令、CLI、MCP、bytedcli 调用
skill_route      遇到某类任务应优先使用某个 skill
data_entrypoint  某类任务应先查某个库、表、API、配置或文档
pitfall          失败路径、不要再做什么
verification     如何验证改动或排查结论
workflow         多步骤排查流程
note             暂时无法分类
```

## 6. Snippet 命令设计

新增命令：

```bash
memagent agents-snippet
```

输出一段可复制到 `AGENTS.md` 的 Markdown 指令。

开发阶段也支持：

```bash
PYTHONPATH=src python -m memagent.cli agents-snippet
```

输出里的命令应使用当前项目绝对路径，例如：

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli recall "<query>" --show-sources --show-reasons
```

原因：

- 用户不一定安装了 `memagent` console script。
- Codex 在任意项目里都可以用绝对路径调用 MemAgent。

## 7. 输出内容结构

`agents-snippet` 输出应包含：

```text
<!-- memagent:start -->
## MemAgent Natural Language Triggers

### Recall
...

### Remember
...

### Safety
...
<!-- memagent:end -->
```

`memagent:start` / `memagent:end` 是 v0.5 后加入的 managed markers，用于让 `agents-install` 安全替换 MemAgent 自己的区块。

Safety 必须强调：

- recalled memory 是提示，不是事实来源。
- 查代码、schema、命令输出时仍以实时结果为准。
- 本地私有 memory 可以保留必要工程入口。
- 不保存 token、cookie、密码、私钥、原始敏感样本、大段请求响应。
- 公开 demo 前要泛化。

## 8. v0.3 代码改动范围

### 8.1 `cli.py`

新增子命令：

```text
agents-snippet
```

并在 `recall` / `codex` 上提供：

```bash
--show-reasons
```

用于输出当前简单召回分数和命中的 query terms。这是为了让 AGENTS.md 集成更容易演示和调试，不绑定最终检索算法。

可选参数：

```bash
--memagent-root <path>
```

默认从当前包位置推导项目根目录。

### 8.2 新模块 `agents.py`

建议新增：

```text
src/memagent/agents.py
```

负责：

- 生成 AGENTS.md snippet。
- 推导 MemAgent src 路径。
- 保持文本和 CLI 分离，方便测试。

核心函数：

```python
def build_agents_snippet(memagent_root: Path) -> str:
```

### 8.3 测试

新增测试：

```text
tests/test_agents_snippet.py
```

覆盖：

- snippet 包含 recall 触发语。
- snippet 包含 remember 触发语。
- snippet 包含绝对 `PYTHONPATH=.../src python -m memagent.cli`。
- snippet 包含安全边界。

## 9. 手动自测

生成 snippet：

```bash
PYTHONPATH=src python -m memagent.cli agents-snippet
```

检查输出里是否包含：

```text
召回一下相关记忆
沉淀一下
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli recall
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli remember
--show-sources --show-reasons
```

把输出复制到某个测试项目的 `AGENTS.md`。

新 Codex 线程里测试：

```text
召回一下相关记忆：我要查 RDS 大表统计
```

以及：

```text
沉淀一下：RDS 大表统计先跑小样本，不要直接全表 group。
```

## 10. v0.3 完成标准

- `memagent agents-snippet` 可运行。
- snippet 能复制到任意项目 `AGENTS.md`。
- Codex 能根据自然语言规则调用 recall。
- Codex 能根据自然语言规则调用 remember。
- 不要求自动修改 AGENTS.md。
- 不要求 MCP/Hook。
- 测试通过。

## 11. 后续延伸

v0.3 完成后再考虑：

- `memagent install-agents --target <AGENTS.md>` 自动插入 snippet。
- `memagent recall --json` 让 Codex 更稳定解析。
- `memagent remember --from-file` 或 `ingest`。
- MCP server。
- Hook-based session start recall。
