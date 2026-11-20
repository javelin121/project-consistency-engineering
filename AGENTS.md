# 这个仓库是什么

一个 agent skill：一套目录一致性规则 + 一个校验脚本 `tools/pce.py`。它被装进 `~/.agents/skills/`，agent 调用它，去用户的仓库里干活。

## 改这个包时怎么干活

1. 先读 `../docs/00-brief.md`（工作区根，不随包分发）：规则为什么是现在这样。
2. 改规则要三处同步：先 `../docs/00-brief.md`，再 `references/`，最后 `tools/pce.py` 的实现。只改一处就是新的一处不一致。
3. 改模板：`assets/templates/` 与 `pce.py` 里的 `*_TPL` 必须一起改。
4. 改完跑 `python tools/pce.py check`，零 error 才算完。

## 三条硬规则

1. 这个包自己也要守这套规则：`structure.yaml`、每层 `navigation.md` 齐全，自己跑 `check` 零 error。
2. 不往本文件写日志、台账、进度。它每次对话都会被整篇加载，多一行都是成本。
3. 新增文件前先确认它落在哪个分区，不在根上乱放。

## 去哪看

- 规则细节：`references/`
- 设计取舍：`../docs/00-brief.md`、`../docs/02-design.md`
