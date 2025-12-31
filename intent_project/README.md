# Intent Project (智能意图与缓存服务)

这是一个基于 **FastAPI**、**Elasticsearch** 和 **LLM** 构建的生产级意图识别与参数缓存微服务。
它不仅能将用户自然语言精准分类（如“图搜”、“选品”），还具备**语义级参数缓存**（Tier 1/2 命中机制），能够显著降低 LLM 调用成本并提升响应速度。

---

## 📂 项目结构说明

本项目采用领域驱动设计（DDD）风格的分层架构：

```text
intent_project/
├── main.py                ## 应用入口：负责 App 组装、生命周期管理 (Lifespan) 和 ReMe 初始化
├── api/
│   └── routes.py          ## 路由层：定义所有 API 接口 (Classify, Cache, Maintenance)
├── local_vector_store/intent_router_v2.json ## 记忆模块本地示例数据
├── core/
│   ├── config.py          ## 配置中心：加载环境变量 (.env) 和系统常量
│   ├── deps.py            ## 依赖注入：管理全局单例资源 (ES 连接池, LLM Client)
│   ├── patches.py         ## 补丁模块：修复 flowllm 在 Serverless ES 下的兼容性问题
│   └── prompts.py         ## 提示词库：存放系统级 Prompt 模板
├── services/
│   ├── cache_service.py   ## 缓存服务：实现语义检索、Tier 1/2 分级判定及时间校准逻辑
│   ├── llm_service.py     ## 推理服务：封装 LLM 意图分类逻辑与重试机制
│   └── memory_service.py  ## 记忆服务：处理长期记忆的 CRUD 和批量导入导出
└── schemas/
    └── base.py            ## 数据模型：定义 Pydantic Request/Response 和枚举类型

```

---

## ⚡ 快速启动 (Quick Start)

### 1. 环境准备

推荐使用 Conda 管理环境（Python 3.10+）。

```bash
# 创建并激活环境
conda create -n intent_project python=3.13
conda activate intent_project

# 安装依赖
pip install -r requirements.txt

```

### 2. 配置环境变量

在项目根目录（`intent_project/` 同级）创建 `.env` 文件（已配置）：

```dotenv
# === LLM 设置 ===
OPENROUTER_API_KEY=sk-xxxx
REAL_LLM_URL=[https://openrouter.ai/api/v1](https://openrouter.ai/api/v1)
REAL_LLM_MODEL=google/gemini-2.0-flash-001

# === Embedding 设置 (DashScope) ===
DASHSCOPE_API_KEY=sk-xxxx
DASHSCOPE_BASE_URL=[https://dashscope.aliyuncs.com/compatible-mode/v1](https://dashscope.aliyuncs.com/compatible-mode/v1)
DASHSCOPE_EMBEDDING_MODEL=text-embedding-v3

# === Elasticsearch 设置 ===
ES_USER=your_username
ES_PASS=your_password
ES_HOST=your-es-endpoint.aliyuncs.com:9200

```

### 3. 启动服务

**注意**：由于项目是一个 Python Package，请在 `intent_project` 文件夹的**上一级目录**运行：

```bash
# 推荐启动方式
python -m intent_project.main
```

服务启动后，默认监听在 `http://0.0.0.0:8000`。
API 文档地址：`http://0.0.0.0:8000/docs`

---

## ✨ 核心特性

1. **意图识别 (RAG Enhanced)**
* 结合短期对话历史 + 长期记忆（ReMe）进行意图判断。
* 支持“图搜”、“选品”、“趋势报告”等多种复杂业务场景。


2. **智能缓存 (Semantic Cache)**
* **Tier 1 (Exact Match)**: 评分 > 0.99，直接复用参数并校准时间。
* **Tier 2 (Semantic Match)**: 评分 > 0.95，引入轻量级 LLM 裁判（Judge）判断是否可复用。
* **Time Calibration**: 自动将缓存中的“上个月”转换为当前的具体日期范围。


3. **记忆运维 (Maintenance)**
* 支持 `.jsonl` 格式的批量导入/导出。
* 支持 Serverless ES 环境（通过 Monkey Patch 适配）。
