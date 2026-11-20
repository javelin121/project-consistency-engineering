# 项目一致性工程（Project Consistency Engineering）

给 AI agent 用的一个 skill：让仓库里的文件一直放在该放的地方，让目录导航跟着每次改动一起更新。

## 它解决什么

项目和 agent 一起长大时，目录会烂在四个地方：东西随手放在根上；新建的目录没人说得清是干什么的；文件挪了位置，引用它的文档和代码没跟着改；agent 每次进仓库，都得重新猜一遍结构。这个 skill 用一份契约、一套导航、一个检查把这几件事钉住。

## 装

```sh
cp -r project-consistency-engineering ~/.agents/skills/
```

## 在一个仓库里开始

```sh
cd your-repo
python ~/.agents/skills/project-consistency-engineering/tools/pce.py init
python tools/pce.py check
```

`init` 会把 `tools/pce.py` 复制进你的仓库。之后不需要再依赖这个 skill 装没装。

## 它不做什么

- 不管代码写得好不好（不替代 lint、格式化、类型检查）
- 不管依赖、构建、CI、文档站
- 不判断文档内容对不对
- 不规定 git 分支和提交规范
- 不自动搬你的文件：老仓库只出审计报告，改动逐条确认

## 规则

五条底线、12 条检查、9 个命令，见 `SKILL.md` 与 `references/`。
