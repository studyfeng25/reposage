# RepoSage — 一键安装文档

> 把这个文件扔给 Claude，它会自动完成所有安装和注册工作。

---

## 你是 Claude，请严格按照以下步骤执行

### 环境信息（执行前先询问用户确认以下路径）

如果用户没有提供，先问清楚再执行：

```
RepoSage 项目目录:   <reposage 克隆到的本地路径，如 ~/Desktop/github/codelens>
Python venv:         <项目目录>/.venv/bin/python
uv 路径（可选）:     ~/.local/bin/uv
仓库根目录:          <用户存放代码仓库的目录，如 ~/Desktop/projects>
```

以下步骤中的 `<reposage>` 代表 RepoSage 项目目录，`<projects>` 代表仓库根目录。

---

### Step 0：清理旧的安装

1. 列出所有已注册的 MCP server：
   ```bash
   claude mcp list
   ```

2. 删除所有名称包含 `reposage` 或 `codelens` 的 MCP 注册（不存在时报错忽略即可）：
   ```bash
   claude mcp remove reposage
   claude mcp remove reposage -s local
   claude mcp remove reposage -s user
   ```

3. 清理旧版遗留的仓库内索引数据（新版索引在仓库外，若无旧版跳过）：
   ```bash
   # 把 <repo> 替换为实际仓库名，有几个清几个
   rm -rf <projects>/<repo>/.reposage
   rm -rf <projects>/<repo>/.codelens
   rm -rf <projects>/<repo>/docs
   ```

---

### Step 1：确认依赖已安装

```bash
<reposage>/.venv/bin/python -c "
import tree_sitter, tree_sitter_languages, tree_sitter_swift
import mcp, chromadb, watchdog, click, rich, yaml
print('✅ 所有依赖已就绪')
"
```

**如果报错**，执行安装：

```bash
# 推荐使用 uv（更快）
uv pip install \
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

# 或使用 pip
<reposage>/.venv/bin/pip install \
    tree-sitter==0.21.3 \
    tree-sitter-languages \
    tree-sitter-swift \
    mcp chromadb watchdog click rich pyyaml fastapi uvicorn
```

然后重新安装 reposage 包：

```bash
<reposage>/.venv/bin/pip install -e <reposage>
```

---

### Step 2：注册 MCP Server 到 Claude Code（全局，只需一次）

**推荐：指定目录，自动发现所有已索引仓库**
```bash
claude mcp add --scope user reposage -- \
    <reposage>/.venv/bin/python \
    -m reposage mcp \
    --repos-dir <projects>
```

**或明确指定仓库（可重复 --repo）：**
```bash
claude mcp add --scope user reposage -- \
    <reposage>/.venv/bin/python \
    -m reposage mcp \
    --repo <projects>/<repo1> \
    --repo <projects>/<repo2>
```

---

### Step 3：验证注册成功

```bash
claude mcp list
```

**预期输出中应包含：**
```
reposage: <reposage>/.venv/bin/python -m reposage mcp --repos-dir <projects> - ✓ Connected
```

---

### Step 4：验证工具可用性（需要先有至少一个已索引的仓库）

如果还没有索引任何仓库，先参考 README 的使用教程建索引，再回来执行此步骤。

```bash
<reposage>/.venv/bin/python -c "
import sys
sys.path.insert(0, '<reposage>')
from pathlib import Path
from reposage.storage.db import RepoSageDB

projects_dir = Path('<projects>')
found = []
for d in sorted(projects_dir.iterdir()):
    if d.is_dir() and d.name.startswith('RepoSage-'):
        db_path = d / 'index.db'
        if db_path.exists():
            found.append((d.name[len('RepoSage-'):], d))

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
📂 仓库根目录：<projects>

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
<reposage>/.venv/bin/python -m reposage watch <projects>/<repo>

# 多个仓库
<reposage>/.venv/bin/python -m reposage watch \
    <projects>/<repo1> \
    <projects>/<repo2>
```
