# RepoSage — 傻瓜式安装文档

> 把这个文件扔给 Claude，它会自动完成所有安装和注册工作。

---

## 你是 Claude，请严格按照以下步骤执行

### 环境信息（固定值，不要修改）

```
项目目录:    /Users/fengfan/Desktop/github/codelens
Python venv: /Users/fengfan/Desktop/github/codelens/.venv/bin/python
uv 路径:     /Users/fengfan/.local/bin/uv
仓库根目录:  /Users/fengfan/Desktop/projects
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

3. 清理旧版遗留的仓库内索引数据（新版索引在仓库外，不需要手动清）：
   ```bash
   # 如有旧版遗留，逐个清理（把 <repo> 替换为实际仓库名）
   rm -rf /Users/fengfan/Desktop/projects/<repo>/.reposage
   rm -rf /Users/fengfan/Desktop/projects/<repo>/.codelens
   rm -rf /Users/fengfan/Desktop/projects/<repo>/docs
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

### Step 2：注册 MCP Server 到 Claude Code（全局，只需一次）

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

### Step 3：验证注册成功

```bash
claude mcp list
```

**预期输出中应包含：**
```
reposage: /Users/fengfan/Desktop/github/codelens/.venv/bin/python -m reposage mcp --repos-dir /Users/fengfan/Desktop/projects
```

---

### Step 4：验证工具可用性（需要先有至少一个已索引的仓库）

如果还没有索引任何仓库，先参考 README 的使用教程建索引，再回来执行此步骤。

```bash
/Users/fengfan/Desktop/github/codelens/.venv/bin/python -c "
import sys
sys.path.insert(0, '/Users/fengfan/Desktop/github/codelens')
from reposage.mcp.server import _tool_list_repos
from reposage.indexer.pipeline import get_reposage_dir
from reposage.storage.db import RepoSageDB
from reposage.storage.vector_store import VectorStore
import os
from pathlib import Path

projects_dir = Path('/Users/fengfan/Desktop/projects')
found = []
for d in sorted(projects_dir.iterdir()):
    if d.is_dir() and d.name.startswith('RepoSage-'):
        repo_name = d.name[len('RepoSage-'):]
        db_path = d / 'index.db'
        if db_path.exists():
            found.append((repo_name, d))

if not found:
    print('⚠️  还没有已索引的仓库，请先运行 reposage analyze')
else:
    for repo_name, reposage_dir in found:
        db = RepoSageDB(reposage_dir / 'index.db')
        stats = db.get_stats()
        print(f'📊 {repo_name}:')
        print(f'   索引目录: {reposage_dir}')
        print(f'   符号数:   {stats[\"symbols\"]}  关系数: {stats[\"relations\"]}  模块数: {stats[\"modules\"]}')
        print(f'   索引时间: {stats[\"last_indexed\"]}')
        print()
    print('✅ 工具验证通过！')
" 2>&1 | grep -v FutureWarning | grep -v "ChromaDB init"
```

---

### 完成后告诉用户

安装验证通过后，输出以下信息：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ RepoSage 安装注册成功！

🔌 MCP 注册名称：reposage
📂 仓库根目录：/Users/fengfan/Desktop/projects

⚡ 下一步：
  1. 重启 Claude Code
  2. 用 reposage analyze 为仓库建索引（参考 README 使用教程）
  3. 建完索引后直接在对话中提问即可
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

### 附：实时监听文件变更

```bash
# 单个仓库
/Users/fengfan/Desktop/github/codelens/.venv/bin/python -m reposage watch \
    /Users/fengfan/Desktop/projects/<repo>

# 多个仓库
/Users/fengfan/Desktop/github/codelens/.venv/bin/python -m reposage watch \
    /Users/fengfan/Desktop/projects/<repo1> \
    /Users/fengfan/Desktop/projects/<repo2>
```
