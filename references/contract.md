# `structure.yaml`：这份契约怎么写

它放在仓库根目录，是这套规则唯一的事实源。`AGENTS.md`、`navigation.md` 都是它的投影；手改导航不影响判定，`check` 只认它。

## 六个字段

```yaml
version: 1

zones:
  src:
    what: 程序源码
  tests:
    what: 测试

root:
  allow:
    - README.md
    - pyproject.toml

naming:
  default: snake
  zones:
    docs: kebab

archive:
  path: archive/

ignore:
  - .venv/
  - dist/
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `version` | 是 | 目前只有 `1`；不认的值直接报错 |
| `zones` | 是 | 分区表，键是目录名，值含 `what`（必填） |
| `root.allow` | 否 | 追加到内建 41 项之后，用于放行这个项目特有的根文件 |
| `naming` | 否 | `default` 全局风格，`zones` 按分区覆盖，`files` 按文件名模式覆盖 |
| `archive.path` | 否 | 归档区位置，默认 `archive/`；写空字符串表示没有归档区 |
| `ignore` | 否 | 整棵子树不参与检查，`pce new` 也拒绝往里建 |

## 分区是什么

分区 = 仓库顶层按职责切出的一块。名字只能是根目录下的一级目录名，不能是多层路径。

`what` 是给人和 agent 看的一句话：这一块装什么。它是判断“这个文件放这儿说不说得通”的唯一依据，所以别写“其他”“杂项”“暂存”。

分区不规定文件类型。代码目录里出现 `.md`、`.json`、`.sql` 是正常的；这个 skill 只管归属，不管格式。

## 命名

| 风格 | 样子 | 适合 |
|---|---|---|
| `snake` | `user_profile.py` | Python |
| `kebab` | `user-profile.md` | 文档、目录 |
| `pascal` | `UserProfile.tsx` | React 组件 |
| `camel` | `userProfile.ts` | 部分 JS/TS |

只写风格名，不写正则。不写 `naming` 或对应分区没写，就不检查命名——不猜。

## 格式限制

只支持 YAML 的一个子集：注释、`键: 值`、两格缩进嵌套、`- ` 列表、行内列表、字符串、布尔、整数。

不支持锚点、块标量（`|`、`>`）、行内映射、多文档。解析器只认这一个文件，写错了会报“第几行”。

## 默认值

内建 41 项（常见单文件配置、锁文件、入口文件）永远生效；你写的 `root.allow` 是**追加**，不是替换。`init` 会扫一遍根目录，把内建清单里没有的文件写进 `root.allow`。

`ignore` 内建 `.git/`、`.venv/`、`node_modules/`，这三类直接拒绝，不给选项。
