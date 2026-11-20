# 项目一致性工程（Project Consistency Engineering）

给 AI agent 用的一个 skill：让仓库里的文件一直放在该放的地方，让导航跟着每次改动一起更新。

## 它解决什么

项目跟 agent 一起长大时，目录会烂在四个地方：

- 东西随手丢在根上，谁也不知道该不该在那儿；
- 新建的目录没人说得清是干什么的；
- 文件挪了位置，引用它的文档和代码没跟着改；
- agent 每次进仓库，都得重新猜一遍结构。

它用三样东西把这几件事钉住：一份**契约**（`structure.yaml`，机器读）、一套**导航**（每层一份 `navigation.md`，人和 agent 读）、一个**检查**（`tools/pce.py`，12 条规则，跑一次出结果）。

## 要求

- Python 3.9+，只用标准库，不需要装任何依赖。
- 不依赖某个特定 CLI：规则和脚本都在你的仓库里，换哪个 agent 都能用。

## 装

```sh
git clone https://github.com/<你>/project-consistency-engineering.git \
  ~/.agents/skills/project-consistency-engineering
```

Claude Code 之类读 `~/.claude/skills/` 的工具，把它放到对应目录即可。

## 在任意一个仓库里开始

```sh
cd your-repo
python3 ~/.agents/skills/project-consistency-engineering/tools/pce.py init
python3 tools/pce.py check
```

`init` 会把 `tools/pce.py` 复制进你的仓库。之后不依赖这个 skill 装没装——`python3 tools/pce.py check` 永远能跑。

老仓库先只读审计，不动文件：

```sh
python3 tools/pce.py audit
```

## 命令

| 命令 | 做什么 | 会改文件吗 |
|---|---|---|
| `init` | 建契约、入口、导航，装 `tools/pce.py` | 会，逐个确认 |
| `audit` | 只读体检：多大、多乱、缺什么 | 不会 |
| `check` | 跑 12 条规则，出 error / warn | 不会 |
| `map` | 让导航表和磁盘对齐 | 会，只增删行 |
| `new` | 在契约允许的位置建文件或目录 | 会 |
| `archive` | 把不再用的文件挪进归档区并登记 | 会 |
| `explain` | 解释某个路径为什么被判成这样 | 不会 |
| `upgrade` | 更新仓库里的 `tools/pce.py` | 会，本地改过就停手 |
| `hook install/uninstall` | 装/卸 pre-commit 钩子 | 会 |

## 它不做什么

- 不管代码写得好不好（不替代 lint、格式化、类型检查）；
- 不管依赖、构建、CI、文档站；
- 不判断文档内容对不对（只标出哪一层很久没动过）；
- 不规定 git 分支和提交规范；
- 不自动搬你的文件：老仓库只出审计报告，改动逐条确认。

## 文档在哪

- `SKILL.md`：agent 的入口，什么时候用、六步怎么走。
- `references/`：契约字段、导航格式、12 条规则、放置判断、老仓库迁移。
- 想改这个包本身：看 `AGENTS.md`。

## 许可

MIT，见 `LICENSE`。
