<!-- pce:begin -->
# 怎么在这个仓库里干活

本项目的目录结构由 PCE 管。

1. 新建文件走 `pce new <路径>`，不要直接在编辑器里往仓库里丢。
2. 改完跑 `pce check`，error 清零才算完。
3. 导航在每一层的 `navigation.md`；不知道放哪，先看这一层的表。

放错地方时 `pce check` 会告诉你。
<!-- pce:end -->

# 这个包是什么

一个 agent skill：一套目录一致性规则 + 一个校验脚本 `tools/pce.py`。它被装进 `~/.agents/skills/`，agent 调用它，去用户的仓库里干活。

上面标记段里的三条是通用规则，`pce init` 只替换段内；下面这些是这个包自己的事，放在段外，不会被覆盖。

## 改这个包时怎么干活

1. 先读 `references/philosophy.md`：为什么是这套规则、五条底线各防什么。
2. 改规则要三处同步：`references/`（说给人看）、`assets/templates/`（给新仓库看）、`tools/pce.py`（机器执行）。只改一处就是新的一处不一致。
3. 改模板：`assets/templates/` 与 `pce.py` 里的 `*_TPL` 必须一起改。
4. 改完跑 `python tools/pce.py check`，零 error 才算完。

## 另外两条硬规则

1. 这个包自己也要守这套规则：`structure.yaml`、每层 `navigation.md` 齐全，自己跑 `check` 零 error。
2. 不往本文件写日志、台账、进度。它每次对话都会被整篇加载，多一行都是成本。

## 去哪看

- 规则细节：`references/`
- 设计取舍：`references/philosophy.md`、`references/contract.md`
