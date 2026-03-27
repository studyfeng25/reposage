# RepoSage — 傻瓜式安装文档

> 把这个文件扔给 Claude，它会自动完成所有安装、注册、索引工作。

---

## 你是 Claude，请严格按照以下步骤执行

### 环境信息（固定值，不要修改）

```
项目目录:    /Users/fengfan/Desktop/github/codelens
Python venv: /Users/fengfan/Desktop/github/codelens/.venv/bin/python
uv 路径:     /Users/fengfan/.local/bin/uv
默认仓库:    /Users/fengfan/Desktop/projects/pfbwxsearch
```

---

### Step 0：清理旧的安装

执行以下操作，清除所有旧注册：

1. 列出所有已注册的 MCP server：
   ```bash
   claude mcp list
   ```

2. 删除所有名称包含 `reposage` 或 `codelens` 的 MCP 注册：
   ```bash
   claude mcp remove codelens-pfbwxsearch
   claude mcp remove reposage
   claude mcp remove reposage-pfbwxsearch
   ```
   （不存在的条目删除时会报错，忽略即可）

3. 删除旧的索引数据：
   ```bash
   rm -rf /Users/fengfan/Desktop/projects/pfbwxsearch/.reposage
   rm -rf /Users/fengfan/Desktop/projects/pfbwxsearch/.codelens
   rm -rf /Users/fengfan/Desktop/projects/pfbwxsearch/docs
   ```

---

### Step 1：确认依赖已安装

运行以下命令验证：

```bash
/Users/fengfan/Desktop/github/codelens/.venv/bin/python -c "
import tree_sitter, tree_sitter_languages, tree_sitter_swift
import mcp, anthropic, chromadb, watchdog, click, rich, yaml
print('✅ 所有依赖已就绪')
"
```

**如果报错**，执行安装：

```bash
/Users/fengfan/.local/bin/uv pip install \
    tree-sitter==0.21.3 \
    tree-sitter-languages \
    tree-sitter-swift \
    mcp \
    anthropic \
    chromadb \
    watchdog \
    click \
    rich \
    pyyaml \
    fastapi \
    uvicorn
```

然后重新安装 reposage 包：

```bash
/Users/fengfan/.local/bin/uv pip install -e /Users/fengfan/Desktop/github/codelens
```

---

### Step 2：索引默认仓库（pfbwxsearch）

```bash
/Users/fengfan/Desktop/github/codelens/.venv/bin/python -m reposage analyze \
    /Users/fengfan/Desktop/projects/pfbwxsearch \
    --skip-wiki \
    --skip-embed
```

**预期输出：**
```
RepoSage Indexer
  Repo: /Users/fengfan/Desktop/projects/pfbwxsearch
  Parsing ... ████████████████████ 100%
  Parsed N files → N symbols, N relations
  Resolved N cross-file relations
  Clustered into N modules
  Agent index written to .reposage/

Done!  Symbols: XXXXX  Relations: XXXXX  Modules: X
```

索引完成后，以下文件会出现在仓库中：
```
/Users/fengfan/Desktop/projects/pfbwxsearch/
└── .reposage/
    ├── index.db        ← SQLite 知识图谱
    ├── index.json      ← 符号名快查表
    ├── symbols.json    ← 所有符号（精简格式）
    ├── relations.json  ← 调用/继承关系
    └── modules.yaml    ← 模块拓扑
```

---

### Step 3：注册 MCP Server 到 Claude Code（全局）

```bash
claude mcp add --scope user reposage-pfbwxsearch -- \
    /Users/fengfan/Desktop/github/codelens/.venv/bin/python \
    -m reposage mcp \
    --repo /Users/fengfan/Desktop/projects/pfbwxsearch
```

---

### Step 4：验证注册成功

```bash
claude mcp list
```

**预期输出中应包含：**
```
reposage-pfbwxsearch: /Users/fengfan/Desktop/github/codelens/.venv/bin/python -m reposage mcp --repo /Users/fengfan/Desktop/projects/pfbwxsearch
```

---

### Step 5：验证工具可用性

运行以下 Python 脚本做端到端测试：

```bash
/Users/fengfan/Desktop/github/codelens/.venv/bin/python -c "
import sys
sys.path.insert(0, '/Users/fengfan/Desktop/github/codelens')
from pathlib import Path
from reposage.storage.db import RepoSageDB
from reposage.storage.vector_store import VectorStore
from reposage.mcp.server import _tool_search, _tool_find_callers, _tool_module_overview

repo = Path('/Users/fengfan/Desktop/projects/pfbwxsearch')
db = RepoSageDB(repo / '.reposage' / 'index.db')
vs = VectorStore(repo / '.reposage' / 'vectors', repo.name)

stats = db.get_stats()
print(f'📊 索引统计:')
print(f'   符号数:   {stats[\"symbols\"]}')
print(f'   关系数:   {stats[\"relations\"]}')
print(f'   模块数:   {stats[\"modules\"]}')
print(f'   文件数:   {stats[\"files\"]}')
print(f'   索引时间: {stats[\"last_indexed\"]}')
print()

result = _tool_search({'query': 'voice search', 'limit': 3}, db, vs)
print('🔍 搜索测试 (voice search):')
for line in result.split('\n')[:6]:
    print(f'   {line}')
print()

result = _tool_find_callers({'name': 'viewDidLoad', 'depth': 1}, db)
lines = result.split('\n')
print(f'📞 调用者测试 (viewDidLoad): {lines[0]}')
print()

result = _tool_module_overview({'name': 'PFBWXSearch'}, db)
print('📦 模块测试 (PFBWXSearch):')
for line in result.split('\n')[:4]:
    print(f'   {line}')
print()
print('✅ 所有工具验证通过！')
print()
print('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
print('🎉 RepoSage 安装完成！')
print()
print('重启 Claude Code 后，以下 MCP 工具即可使用：')
print('  search(\"关键词\")                         搜索符号')
print('  find_callers(\"方法名\")                   查找调用者')
print('  impact(\"类名\", direction=\"upstream\")    影响范围分析')
print('  symbol_context(\"符号名\")                360° 符号视图')
print('  module_overview(\"模块名\")               模块概览')
print('  execution_flow(\"入口方法\")              执行流追踪')
print('  ask(\"你的问题\")                          RAG 问答')
print('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
" 2>&1 | grep -v FutureWarning | grep -v "ChromaDB init"
```

---

### 完成后告诉用户

安装验证通过后，输出以下信息：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ RepoSage 安装注册成功！

📁 生成的文件目录：
   /Users/fengfan/Desktop/projects/pfbwxsearch/.reposage/
   ├── index.db        （SQLite 知识图谱，约 8MB）
   ├── index.json      （符号快查表）
   ├── symbols.json    （所有符号）
   ├── relations.json  （调用关系）
   └── modules.yaml    （模块拓扑）

🔌 MCP 注册名称：reposage-pfbwxsearch

⚡ 下一步：重启 Claude Code，然后直接提问即可
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

### 附：为其他仓库安装

如果需要为其他仓库（如 `pfbwxsearchbox`、`mtaisearch`）安装，重复 Step 2-4，替换仓库路径：

```bash
# 索引
/Users/fengfan/Desktop/github/codelens/.venv/bin/python -m reposage analyze \
    /Users/fengfan/Desktop/projects/pfbwxsearchbox \
    --skip-wiki --skip-embed

# 注册（全局）
claude mcp add --scope user reposage-pfbwxsearchbox -- \
    /Users/fengfan/Desktop/github/codelens/.venv/bin/python \
    -m reposage mcp \
    --repo /Users/fengfan/Desktop/projects/pfbwxsearchbox
```

可用仓库列表：
- `pfbwxsearch` ← 默认（核心仓库）
- `pfbwxsearchbox`
- `pfbsearchrecommendcore`
- `mtaisearch`

---

### 附：生成 Wiki 文档（需要 API Key）

```bash
export ANTHROPIC_API_KEY=你的key

/Users/fengfan/Desktop/github/codelens/.venv/bin/python -m reposage wiki \
    /Users/fengfan/Desktop/projects/pfbwxsearch
```

Wiki 生成后的目录：
```
/Users/fengfan/Desktop/projects/pfbwxsearch/docs/
├── ARCHITECTURE.md     ← 全局架构概览
└── modules/
    ├── PFBWXSearch.md  ← 核心模块文档
    └── Example.md
```
