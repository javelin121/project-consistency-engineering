---
name: project-consistency-engineering
description: 一个 agent 友好型 skill：agent 在仓库里干活时不会弄坏你的目录——文件始终放在该放的地方，导航跟着一起改；下一个 agent 接手，也能一眼看清整个项目结构。用在新建仓库、初始化项目、搭脚手架、整理目录、判断某个文件该放哪、规范文件命名、写 AGENTS.md、加一个模块、归档旧文件、检查目录规范，或者接手一个已经很乱的项目。规则和脚本都放在仓库里，换哪个 agent 都能用。
---

# 项目一致性工程

仓库乱，通常不是因为谁偷懒：没人规定过“这个文件该放哪”，也没有一条命令能查出放错了。这个 skill 把这件事变成三样东西——一份写下来的契约、一层一层的导航、一个能跑的检查。

它只管**东西放对没放对、导航跟上没跟上**，不管文档写得对不对、代码跑不跑得起来。

## 什么时候用

- 用户要新建仓库、初始化项目、搭脚手架
- 用户问“这个文件该放哪”“目录该怎么分”
- 用户说项目太乱、要整理、要归档旧文件
- 用户让你加一个模块、加一批文件
- 你接手一个没见过的仓库，得先搞清楚它长什么样
- 用户提到导航、AGENTS.md、目录规范、文件该放哪

## 六步

1. **查图**：看这一层的 `navigation.md`，哪个子目录管什么。
2. **查归属**：要放的地方，按 `structure.yaml` 里那句 `what` 说得通吗。说不通就先扩契约，别硬塞。
3. **出计划**：要建、要移、要删什么，放哪，哪些导航要跟着改。一次说完。
4. **确认**：人点头才动手。新建文件可以整批确认；新建目录、删除、移动逐个确认。
5. **落盘**：用 `python tools/pce.py new ...` 建，别直接用编辑器写。
6. **收尾**：`pce map` 补导航行，`pce check` 复查；有 error 就回到第 2 步。

## 四条纪律

（纪律是“你怎么干活”，底线是“仓库必须满足什么”——底线见 `references/philosophy.md`。）

1. 不确认不写盘。只读命令（`check`、`audit`、`explain`）除外。
2. 缺信息就问，别猜。目录“负责什么”必须由人给。
3. 动了结构就动导航。位置、名字、层级任何一样变了，导航同一次改完。
4. 结构错误不许放过。`check` 还有 error，就是没做完。

## 去哪看

| 想知道 | 看 |
|---|---|
| 为什么这么设计、五条底线 | `references/philosophy.md` |
| `structure.yaml` 每个字段怎么写 | `references/contract.md` |
| 第一次进一个仓库，先看什么 | `references/discovery.md` |
| 新增、移动、改名、删除怎么判断 | `references/placement.md` |
| 各层 `navigation.md` 的格式与更新规矩 | `references/navigation-protocol.md` |
| 12 条检查分别查什么 | `references/validation.md` |
| 老仓库怎么迁移 | `references/migration.md` |

命令与参数：`python tools/pce.py check`、`audit`、`map`、`new`、`archive`、`explain`、`init`、`upgrade`、`upgrade-repo`、`hook install|uninstall`。

下文的 `pce` 都是在仓库根执行的那条命令：仓库里有 `tools/pce.py` 就写 `python3 tools/pce.py`，没有就写 `python3 ~/.agents/skills/project-consistency-engineering/tools/pce.py`。
