<!-- pce:begin -->
<!-- pce:template 0.4.0 sha256:1a10d865a2323f5f -->
# 怎么在这个仓库里干活

这个仓库的目录结构由 PCE 管：文件放哪、导航怎么写都有规则，`pce check` 会告诉你哪儿不对。

1. 放东西之前，先看这一层的 `navigation.md`，表里写着每个子目录负责什么。
2. 新建走 `pce new <路径>`，不要直接在编辑器里丢文件；建目录要给它一句“负责什么”。
3. 移动、改名、删除、归档，先出计划等人确认；要留凭据的旧文件用 `pce archive <路径> --reason "为什么"`。
4. 改完跑 `pce check`，error 清零；导航和磁盘对不上时跑 `pce map`。
5. 没有 `pce` 命令时：仓库里有 `tools/pce.py` 就用它，没有就用 `python3 ~/.agents/skills/project-consistency-engineering/tools/pce.py`。
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
