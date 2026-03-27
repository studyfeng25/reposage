# RepoSage — 傻瓜式安装文档

> 把这个文件扔给 Claude，它会自动完成所有安装、注册、索引工作。

---

## 你是 Claude，请严格按照以下步骤执行

### 环境信息（固定值，不要修改）

```
项目目录:    /Users/fengfan/Desktop/github/codelens
Python venv: /Users/fengfan/Desktop/github/codelens/.venv/bin/python
uv 路径:     /Users/fengfan/.local/bin/uv
仓库根目录:  /Users/fengfan/Desktop/projects
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

3. 删除旧的索引数据（旧版放在仓库内，新版放在仓库外）：
   ```bash
   rm -rf /Users/fengfan/Desktop/projects/pfbwxsearch/.reposage
   rm -rf /Users/fengfan/Desktop/projects/pfbwxsearch/.codelens
   rm -rf /Users/fengfan/Desktop/projects/pfbwxsearch/docs
   rm -rf /Users/fengfan/Desktop/projects/RepoSage-pfbwxsearch
   ```

---

### Step 1：确认依赖已安装

运行以下命令验证：

```bash
/Users/fengfan/Desktop/github/codelens/.venv/bin/python -c "
import tree_sitter, tree_sitter_languages, tree_sitter_swift
import mcp, chromadb, watchdog, click, rich, yaml
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

### Step 2：索引仓库

**单个仓库：**
```bash
/Users/fengfan/Desktop/github/codelens/.venv/bin/python -m reposage analyze \
    /Users/fengfan/Desktop/projects/pfbwxsearch \
    --skip-embed
```

**多个仓库（一次性）：**
```bash
/Users/fengfan/Desktop/github/codelens/.venv/bin/python -m reposage analyze \
    /Users/fengfan/Desktop/projects/pfbwxsearch \
    /Users/fengfan/Desktop/projects/pfbwxsearchbox \
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
  Agent index written to RepoSage-pfbwxsearch/

Done!  Symbols: XXXXX  Relations: XXXXX  Modules: X

LLM tasks pending
  Symbols without summary : XXXXX
  Modules without wiki    : X
  ARCHITECTURE.md missing : yes

  Ask Claude to complete these tasks:
  "请调用 get_pending_summaries 和 get_pending_wiki 工具完成 RepoSage 的 LLM 生成阶段"
```

索引完成后，文件生成在**仓库同级目录**，仓库本身不会有任何改动：
```
/Users/fengfan/Desktop/projects/
├── pfbwxsearch/               ← 仓库，完全不动
└── RepoSage-pfbwxsearch/      ← 新建，所有生成内容在这里
    ├── index.db               ← SQLite 知识图谱
    ├── index.json             ← 符号名快查表
    ├── symbols.json           ← 所有符号（精简格式）
    ├── relations.json         ← 调用/继承关系
    ├── modules.yaml           ← 模块拓扑
    ├── pending_llm.json       ← 待 LLM 处理的任务状态
    ├── vectors/               ← 向量索引
    └── docs/                  ← Wiki 文档（LLM 生成阶段产出）
        ├── ARCHITECTURE.md
        └── modules/
            └── *.md
```

---

### Step 3：注册 MCP Server 到 Claude Code（全局，只需一次）

**推荐：指定目录，自动发现所有已索引仓库**
```bash
claude mcp add --scope user reposage -- \
    /Users/fengfan/Desktop/github/codelens/.venv/bin/python \
    -m reposage mcp \
    --repos-dir /Users/fengfan/Desktop/projects
```

**或明确指定仓库：**
```bash
claude mcp add --scope user reposage -- \
    /Users/fengfan/Desktop/github/codelens/.venv/bin/python \
    -m reposage mcp \
    --repo /Users/fengfan/Desktop/projects/pfbwxsearch \
    --repo /Users/fengfan/Desktop/projects/pfbwxsearchbox
```

---

### Step 4：验证注册成功

```bash
claude mcp list
```

**预期输出中应包含：**
```
reposage: /Users/fengfan/Desktop/github/codelens/.venv/bin/python -m reposage mcp --repos-dir /Users/fengfan/Desktop/projects
```

---

### Step 5：验证工具可用性

```bash
/Users/fengfan/Desktop/github/codelens/.venv/bin/python -c "
import sys
sys.path.insert(0, '/Users/fengfan/Desktop/github/codelens')
from pathlib import Path
from reposage.storage.db import RepoSageDB
from reposage.storage.vector_store import VectorStore
from reposage.indexer.pipeline import get_reposage_dir
from reposage.mcp.server import _tool_search, _tool_find_callers, _tool_module_overview, _tool_list_repos

repo = Path('/Users/fengfan/Desktop/projects/pfbwxsearch')
reposage_dir = get_reposage_dir(repo)
db = RepoSageDB(reposage_dir / 'index.db')
vs = VectorStore(reposage_dir / 'vectors', repo.name)

stats = db.get_stats()
print(f'📊 索引统计:')
print(f'   索引目录: {reposage_dir}')
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

print('✅ 所有工具验证通过！')
print()
print('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
print('🎉 RepoSage 安装完成！')
print()
print('重启 Claude Code 后，以下 MCP 工具即可使用：')
print('  list_repos()                              列出所有已加载仓库')
print('  search(\"关键词\", repo=\"pfbwxsearch\")      搜索符号')
print('  find_callers(\"方法名\")                    查找调用者')
print('  impact(\"类名\", direction=\"upstream\")     影响范围分析')
print('  symbol_context(\"符号名\")                 360° 符号视图')
print('  module_overview(\"模块名\")                模块概览')
print('  execution_flow(\"入口方法\")               执行流追踪')
print('  ask(\"你的问题\")                           检索上下文（由 Claude 回答）')
print('  get_pending_summaries()                   获取待生成 summary 的符号批次')
print('  write_summaries([{id, summary}])          写入生成的 summary')
print('  get_pending_wiki()                        获取待生成 wiki 的模块')
print('  write_wiki(modules, architecture)         写入生成的 wiki 文档')
print('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
" 2>&1 | grep -v FutureWarning | grep -v "ChromaDB init"
```

---

### Step 6：生成 Summary 和 Wiki（LLM 阶段）

索引建完后，告诉 Claude：

> "请调用 get_pending_summaries 和 get_pending_wiki 工具完成 pfbwxsearch 的 LLM 生成阶段"

Claude 会自动：
1. 批量拉取没有 summary 的符号 → 生成一句话描述 → 写回索引
2. 拉取没有 wiki 的模块 → 生成 Markdown 文档 → 写入 `RepoSage-pfbwxsearch/docs/`
3. 生成 `ARCHITECTURE.md`

完成后语义搜索质量会显著提升。

---

### 完成后告诉用户

安装验证通过后，输出以下信息：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ RepoSage 安装注册成功！

📁 索引目录：
   /Users/fengfan/Desktop/projects/RepoSage-pfbwxsearch/
   ├── index.db        （SQLite 知识图谱）
   ├── index.json      （符号快查表）
   ├── symbols.json    （所有符号）
   ├── relations.json  （调用关系）
   ├── modules.yaml    （模块拓扑）
   └── docs/           （Wiki 文档，LLM 生成后出现）

🔌 MCP 注册名称：reposage
⚡ 下一步：重启 Claude Code，然后直接提问即可
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

### 附：新增仓库

新仓库只需建索引，MCP server 无需重新注册（`--repos-dir` 会自动发现）：

```bash
# 建索引
/Users/fengfan/Desktop/github/codelens/.venv/bin/python -m reposage analyze \
    /Users/fengfan/Desktop/projects/新仓库名 \
    --skip-embed

# 重启 Claude Code 后即可使用
```

可用仓库列表：
- `pfbwxsearch` ← 默认（核心仓库）
- `pfbwxsearchbox`
- `pfbsearchrecommendcore`
- `mtaisearch`

---

### 附：实时监听文件变更

```bash
# 单个仓库
/Users/fengfan/Desktop/github/codelens/.venv/bin/python -m reposage watch \
    /Users/fengfan/Desktop/projects/pfbwxsearch

# 多个仓库
/Users/fengfan/Desktop/github/codelens/.venv/bin/python -m reposage watch \
    /Users/fengfan/Desktop/projects/pfbwxsearch \
    /Users/fengfan/Desktop/projects/pfbwxsearchbox
```
