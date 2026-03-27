# RepoSage

[English](./README.md) | [简体中文](./README.zh.md)

**面向 ObjC / Swift / Android Java 仓库的代码智能工具 — 双层文档 + MCP 服务**

RepoSage 将你的移动端代码库索引为知识图谱，并通过以下方式暴露出来：

- **人类可读的 Markdown Wiki** — 架构概览、模块文档、Mermaid 图表（由 Claude 生成）
- **Agent 优化的 JSON 索引** — 压缩符号表、调用图、模块拓扑（无需 LLM，极低 token 消耗）
- **MCP 服务器** — 7 个工具，让 Claude Code、Cursor 等 AI Agent 直接查询知识图谱

> 融合了 [GitNexus](https://github.com/abhigyanpatwari/GitNexus)（知识图谱 + MCP）和 [DeepWiki](https://github.com/AsyncFuncAI/deepwiki-open)（LLM 文档生成 + RAG 问答）的优点，并针对 Objective-C、Swift 和 Android Java 提供原生支持。

---

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| **ObjC / Swift / Java 解析** | tree-sitter AST — 提取类、方法、协议、属性、调用链、继承关系 |
| **知识图谱** | SQLite 图数据库 — 符号节点 + CALLS / EXTENDS / IMPLEMENTS / CONFORMS_TO 关系边 |
| **双层输出** | 人类 Wiki（Markdown）+ Agent 索引（JSON/YAML）共存于同一仓库 |
| **MCP 服务器** | 7 个工具：`search`、`symbol_context`、`find_callers`、`impact`、`module_overview`、`execution_flow`、`ask` |
| **语义搜索** | ChromaDB + all-MiniLM-L6-v2 向量搜索，与全文搜索混合 |
| **实时更新** | watchdog 文件监听，300ms 防抖增量更新 |
| **Claude 生成 Wiki** | 每个模块的文档 + ARCHITECTURE.md 由 Claude API 生成 |
| **RAG 问答** | 用自然语言提问，基于代码库内容回答 |

---

## 🚀 快速开始

### 一键安装（推荐）

最简单的方式：把安装文档直接扔给 Claude Code，让它自动完成所有操作。

1. 打开 Claude Code
2. 说：**"读取这个文件并按照里面的步骤操作: /Users/fengfan/Desktop/github/codelens/SETUP.md"**
3. Claude 会自动清理旧安装、重新索引、注册 MCP Server、验证工具可用性，最后汇报文件目录和安装结果

`SETUP.md` 是一个自包含的指令文档，Claude 读取后会端到端执行所有步骤，无需你手动操作任何命令。

---

### 手动安装

### 前置条件

- Python ≥ 3.10（推荐 3.11）
- `ANTHROPIC_API_KEY` — Wiki 生成和 `ask` 工具需要

### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/your-org/reposage.git
cd reposage

# 2. 创建虚拟环境（推荐使用 uv + Python 3.11）
curl -LsSf https://astral.sh/uv/install.sh | sh
~/.local/bin/uv venv --python 3.11
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. 安装依赖
uv pip install tree-sitter==0.21.3 tree-sitter-languages tree-sitter-swift \
    mcp anthropic chromadb watchdog click rich pyyaml fastapi uvicorn

# 4. 安装 reposage 本身
pip install -e .
```

### 索引你的仓库

```bash
# 完整索引（解析 + 向量化 + 生成 Wiki）
reposage analyze /path/to/your/repo

# 跳过 Wiki 生成（更快，无需 API Key）
reposage analyze /path/to/your/repo --skip-wiki

# 跳过 Embedding（最快，搜索仅用全文）
reposage analyze /path/to/your/repo --skip-wiki --skip-embed
```

### 接入 Claude Code

```bash
claude mcp add reposage -- /path/to/.venv/bin/python -m reposage mcp --repo /path/to/your/repo
```

重启 Claude Code，以下工具即可在对话中直接使用：

```
search("语音搜索按钮")
find_callers("viewDidLoad")
impact("UserService", direction="upstream")
symbol_context("PFBSearchHomeVC")
module_overview("Authentication")
execution_flow("loginButtonTapped")
ask("键盘动画是怎么实现的？")
```

---

## 🛠️ CLI 命令

```bash
reposage analyze <仓库路径>                # 完整索引（解析+解析+聚类+向量化+Wiki）
reposage analyze <仓库路径> --force        # 强制全量重新索引
reposage analyze <仓库路径> --skip-wiki    # 跳过 Wiki 生成
reposage analyze <仓库路径> --skip-embed   # 跳过向量化

reposage watch <仓库路径>                  # 监听文件变化，增量更新索引
reposage wiki <仓库路径>                   # 仅生成/刷新 Markdown Wiki
reposage wiki <仓库路径> --force           # 强制重新生成所有 Wiki 页面

reposage mcp --repo <仓库路径>             # 启动 MCP 服务器（stdio，供 Claude Code / Cursor 使用）
reposage status <仓库路径>                 # 显示索引统计（符号数、关系数、模块数）
```

---

## 🤖 MCP 工具详解

通过 `claude mcp add reposage -- python -m reposage mcp --repo <路径>` 接入后，可使用以下工具：

### `search` — 混合搜索

全文搜索 + 语义搜索，查找符号。

```
search(query="键盘动画", limit=10, language="objc")
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `query` | string | 必填 | 自然语言或关键词 |
| `limit` | int | 15 | 最大结果数 |
| `language` | string | — | 过滤语言：`objc`、`swift`、`java` |

---

### `symbol_context` — 符号 360° 视图

查看一个符号的完整上下文：调用者、被调用者、所属类、模块、文档注释。

```
symbol_context(name="keyboardWillChangeFrame:", file="SearchHome/PFBSearchHomeVC.m")
symbol_context(id="5b01b21959040503")   # 用 search 返回的 ID 精确查找
```

---

### `find_callers` — 查找调用者

找出所有调用某方法/函数的代码位置。

```
find_callers(name="viewDidLoad", depth=2)
```

---

### `impact` — 影响范围分析

修改某个符号之前，分析会影响哪些地方。

```
impact(target="PFBSearchHomeVC", direction="upstream", depth=3)
```

| `direction` | 含义 |
|-------------|------|
| `upstream` | 谁依赖这个？（改了会影响谁） |
| `downstream` | 这个调用了什么？ |
| `both` | 两个方向都分析 |

---

### `module_overview` — 模块概览

查看某个模块（顶层目录）的文件列表、导出符号和描述。

```
module_overview(name="PFBWXSearch")
```

---

### `execution_flow` — 执行流追踪

从入口点出发，沿 CALLS 边 BFS 追踪执行流程。

```
execution_flow(entry_point="loginButtonTapped", depth=5)
```

---

### `ask` — RAG 问答

基于代码库内容的自然语言问答，结合符号索引 + Wiki 文档，由 Claude 回答。

```
ask(question="语音搜索功能从头到尾是怎么工作的？")
ask(question="哪些类负责处理键盘帧变化？")
```

> 需要设置 `ANTHROPIC_API_KEY`。

---

## 📁 输出文件说明

运行 `reposage analyze` 后，以下文件会写入你的仓库：

```
your-repo/
├── .reposage/
│   ├── index.db          # SQLite：符号、关系、模块（支持全文搜索）
│   ├── index.json        # 符号名 → ID 映射、文件索引、统计信息
│   ├── symbols.json      # 所有符号（精简：id/name/type/file/line/sig/doc）
│   ├── relations.json    # 所有调用/继承/导入关系
│   ├── modules.yaml      # 模块拓扑与导出符号
│   └── vectors/          # ChromaDB 向量索引
└── docs/
    ├── ARCHITECTURE.md   # 全局架构概览 + Mermaid 图
    └── modules/
        ├── PFBWXSearch.md
        ├── Example.md
        └── ...
```

### Agent 层设计原则

`.reposage/` JSON 文件专为**最小化 token 消耗**设计：

- 每个符号条目约 `80 字节`（id、name、type、file、line、签名截断至 120 字符）
- 关系：source_id → target_name + 类型 + 置信度
- 模块：名称、文件列表、导出符号列表
- 750 个文件的 ObjC 仓库产生约 `1.2MB` 总索引（压缩后约 200KB）

---

## 🔧 模型配置与切换

### Wiki 生成和 `ask` 工具使用的 LLM

默认使用 **Claude**（Anthropic API）。

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

**切换 Wiki 生成模型** — 编辑 `reposage/generator/wiki.py`：

```python
# 约第 100 行 — 模块文档生成（调用次数多，推荐用快速模型）
message = self.client.messages.create(
    model="claude-haiku-4-5-20251001",   # ← 在这里修改
    max_tokens=1500,
    ...
)

# 约第 130 行 — 架构文档生成
message = self.client.messages.create(
    model="claude-haiku-4-5-20251001",   # ← 在这里修改
    max_tokens=2000,
    ...
)
```

**切换 `ask` 工具模型** — 编辑 `reposage/mcp/server.py`：

```python
# 约第 290 行
message = client.messages.create(
    model="claude-opus-4-6",   # ← 在这里修改
    max_tokens=1024,
    ...
)
```

**可用的 Claude 模型：**

| 模型 ID | 速度 | 费用 | 推荐用途 |
|---------|------|------|---------|
| `claude-haiku-4-5-20251001` | 最快 | 最低 | Wiki 生成（调用次数多） |
| `claude-sonnet-4-6` | 较快 | 中等 | 平衡质量与速度 |
| `claude-opus-4-6` | 较慢 | 较高 | `ask` 工具、复杂问答 |

---

### 向量化模型

RepoSage 默认使用 **ChromaDB 内置的 `all-MiniLM-L6-v2`**（本地运行，无需 API Key，首次使用时自动下载约 80MB）。

**切换为 OpenAI Embedding** — 编辑 `reposage/storage/vector_store.py`：

```python
import chromadb.utils.embedding_functions as ef

self._collection = self._client.get_or_create_collection(
    name=self.collection_name,
    embedding_function=ef.OpenAIEmbeddingFunction(
        api_key=os.environ["OPENAI_API_KEY"],
        model_name="text-embedding-3-small",
    ),
    metadata={"hnsw:space": "cosine"},
)
```

---

### 切换为其他 LLM 提供商

**OpenAI：**

在 `reposage/generator/wiki.py` 和 `reposage/mcp/server.py` 中替换 Anthropic 客户端：

```python
from openai import OpenAI
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": prompt}],
)
content = response.choices[0].message.content
```

**Google Gemini：**

```python
import google.generativeai as genai
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
model = genai.GenerativeModel("gemini-2.5-flash")
response = model.generate_content(prompt)
content = response.text
```

---

## 🔍 工作原理

```
源码文件（.m / .h / .swift / .java）
  │
  ▼ tree-sitter AST 解析
  │  ├─ ObjC：@interface、@implementation、方法选择器、消息发送
  │  ├─ Swift：class/struct/protocol/func、call_expression 链式调用
  │  └─ Java：class/interface/method、method_invocation
  │
  ▼ 符号提取 → SQLite（symbols + relations 表）
  │  ├─ 符号：id、name、type、file、line、signature、doc_comment
  │  └─ 关系：CALLS / EXTENDS / IMPLEMENTS / CONFORMS_TO / HAS_METHOD
  │
  ▼ 关系解析（target_name → target_id 跨文件匹配）
  │
  ▼ 模块聚类（按顶层目录分组）
  │
  ▼ 向量化（ChromaDB + all-MiniLM-L6-v2，本地运行，无需 API Key）
  │
  ▼ Agent 索引生成（.reposage/*.json / .yaml）
  │
  ▼ Wiki 生成（Claude API → docs/ARCHITECTURE.md + docs/modules/*.md）
  │
  ▼ MCP 服务器（stdio JSON-RPC）
       └─ Claude Code / Cursor / Codex 查询知识图谱
```

### 支持的语言

| 语言 | 扩展名 | 类 | 方法 | 协议/接口 | 继承 | 调用链 |
|------|-------|----|------|----------|------|--------|
| Objective-C | `.m` `.h` `.mm` | ✓ | ✓（selector） | ✓（@protocol） | ✓ | ✓（消息发送） |
| Swift | `.swift` | ✓（class/struct/enum） | ✓ | ✓（protocol） | ✓ | ✓（链式调用） |
| Java | `.java` | ✓ | ✓ | ✓（interface） | ✓ | ✓ |

---

## 📊 性能基准

在真实 ObjC iOS 搜索 SDK（`pfbwxsearch`）上测试：

| 指标 | 数值 |
|------|------|
| 索引文件数 | 750 |
| 提取符号数 | 18,533 |
| 解析关系数 | 31,728 |
| 索引耗时（无向量化） | ~25 秒 |
| 索引耗时（含向量化） | ~90 秒 |
| SQLite 数据库大小 | 8.2 MB |
| `.reposage/` 总大小 | ~2.1 MB |

---

## 🔌 编辑器接入

### Claude Code（完整支持）

```bash
claude mcp add reposage -- /path/to/.venv/bin/python -m reposage mcp --repo /path/to/repo
```

### Cursor

在 `~/.cursor/mcp.json` 中添加：

```json
{
  "mcpServers": {
    "reposage": {
      "command": "/path/to/.venv/bin/python",
      "args": ["-m", "reposage", "mcp", "--repo", "/path/to/repo"]
    }
  }
}
```

### 接入多个仓库

每个仓库启动独立的 MCP server 实例，使用不同名称：

```bash
claude mcp add reposage-search  -- python -m reposage mcp --repo /path/to/search-repo
claude mcp add reposage-payment -- python -m reposage mcp --repo /path/to/payment-repo
```

---

## ❓ 常见问题

**`No module named 'tree_sitter'`**
```bash
pip install tree-sitter==0.21.3 tree-sitter-languages tree-sitter-swift
```

**`Repository not indexed yet`（仓库未索引）**
```bash
reposage analyze /path/to/repo --skip-wiki
```

**`ANTHROPIC_API_KEY not set`，Wiki 被跳过**

运行前设置环境变量：
```bash
export ANTHROPIC_API_KEY=sk-ant-...
reposage wiki /path/to/repo
```

**方法名显示为 `unknown`**

部分 ObjC 无参数方法在边缘情况下可能出现此问题，使用 `--force` 重新索引：
```bash
reposage analyze /path/to/repo --force --skip-wiki
```

**ChromaDB 向量模型下载很慢**

`all-MiniLM-L6-v2` 模型（约 80MB）在首次使用时下载到 `~/.cache/chroma/`，后续运行直接使用缓存。

---

## 🤝 贡献指南

1. Fork 本仓库
2. 创建功能分支：`git checkout -b feature/add-kotlin-support`
3. 参照现有语言实现，在 `reposage/indexer/languages/` 中添加新语言
4. 用真实仓库测试：`reposage analyze /path/to/test-repo --skip-wiki`
5. 提交 PR

---

## 📄 许可证

MIT License — 详见 [LICENSE](LICENSE)

---

## 致谢

- [tree-sitter](https://tree-sitter.github.io/) — 多语言 AST 解析
- [GitNexus](https://github.com/abhigyanpatwari/GitNexus) — 知识图谱 + MCP 架构灵感
- [DeepWiki](https://github.com/AsyncFuncAI/deepwiki-open) — LLM 文档生成 + RAG 灵感
- [ChromaDB](https://www.trychroma.com/) — 本地向量存储
- [MCP](https://modelcontextprotocol.io/) — Model Context Protocol
- [Anthropic Claude](https://www.anthropic.com/) — Wiki 生成与问答
