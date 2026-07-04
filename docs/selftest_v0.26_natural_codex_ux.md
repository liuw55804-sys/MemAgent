# MemAgent v0.26 Natural Codex UX 自测 Playbook

这份自测验证的不是“命令能不能跑”，而是：

> 用户只说正常 Codex 任务语言时，MemAgent 能不能在后台自然发挥作用？

## 1. 自测前置

在 MemAgent 仓库里跑：

```bash
cd /Users/bytedance/Desktop/work/personal_agents/memagent
PYTHONPATH=src python -m unittest discover -s tests
PYTHONPATH=src python -m memagent.cli agents-doctor --cwd /Users/bytedance/Desktop/work/attribution
```

预期：

- 单测通过。
- `agents-doctor` 显示 `Status: ready`。

## 2. 建议测试方式

在 `/Users/bytedance/Desktop/work/attribution` 开一个 Codex 线程。

不要主动说 `recall`、`trace`、`eval`、`replay`、`candidate`。这次要观察 Codex 是否能从自然语言里判断 MemAgent 是否有用。

## 3. Step 1: 正常任务触发记忆

对 Codex 说：

```text
帮我排查 audit_rule_lib 里 governance task owner 相关问题，先按你觉得最省时间的方式来。
```

通过标准：

- Codex 可以先调用 MemAgent 查相关记忆，但不要求用户说 `recall`。
- 如果召回到 memory，Codex 只用一句话说明提醒点。
- Codex 仍然继续检查 live code、schema、文档或命令输出。

## 4. Step 2: 对话中沉淀经验

当 Codex 发现一个可复用入口或你主动指出一个坑时，说：

```text
这个 bytedcli 查 live schema 的入口下次别忘了。
```

通过标准：

- Codex 先预览一条短 memory。
- 预览里有 topic、kind、triggers、memory。
- 你确认后，Codex 才调用 `remember` 保存。
- 保存内容是 1-3 句话的可复用经验，不是整段聊天记录。

## 5. Step 3: 普通反馈标注

如果刚才召回的 memory 确实帮到了你，说：

```text
刚刚那条提醒有用。
```

如果没帮到，说：

```text
刚刚那条没帮上忙。
```

通过标准：

- Codex 能把这类普通反馈映射到 trace feedback。
- 用户不需要说 `trace label`。
- Codex 简短说明已记录反馈即可，不要生成 eval/replay 报告。

## 6. Step 4: 线程交接

对 Codex 说：

```text
先到这，下次继续时帮我接上。
```

通过标准：

- Codex 生成短 handoff。
- handoff 包含已完成、下一步、未验证风险。
- 再问 `上次做到哪` 时，Codex 能取回最近状态。

## 7. Step 5: 开发者质量报告

只有当你想评估 MemAgent 本身时，才说：

```text
给我生成 MemAgent 这轮自测的质量报告，包含 trace eval 和 replay，输出到 MemAgent 项目的 local_memory_demo/v0.26_selftest。
```

通过标准：

- Codex 使用绝对 `--workspace`，避免报告散落到当前业务 repo。
- 生成 `trace_eval/report.md` 和 `trace_replay/report.md`。
- 报告解释 useful traces 的稳定性，但不把它包装成用户日常流程。

## 8. 验收表

| 验收项 | 通过标准 | 你的结论 |
|---|---|---|
| 自然任务触发 | 用户不说 recall，Codex 也能判断是否查记忆 | 待填 |
| 沉淀体验 | 用户说“下次别忘了”，Codex 先预览再保存 | 待填 |
| 反馈体验 | 用户说“有用/没用”，Codex 能记录反馈 | 待填 |
| 交接体验 | 用户说“先到这”，Codex 能保存 handoff | 待填 |
| 开发者报告 | eval/replay 只作为质量报告出现 | 待填 |
| 产品感 | 用户不需要理解 recall/trace/candidate 术语 | 待填 |

## 9. 结论模板

```text
v0.26 自测结论：
- 自然任务触发：通过/不通过，例子是...
- memory 沉淀：自然/仍然像命令流程，原因是...
- 反馈标注：能/不能从“有用/没用”触发...
- handoff：当前会话/新会话能否接上...
- 下一版优先：LLM-assisted draft / 自动意图识别 / recall 准确率 / UI
```

