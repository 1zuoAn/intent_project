


```

---

### 2. 更新后的 `接口文档.md`

增加了新增的缓存接口，并更新了维护接口的说明。

```markdown
# 意图识别与缓存服务 API 文档

**基本信息**
* **Base URL**: `http://<server_ip>:8000`
* **Content-Type**: `application/json`

---

## 1. 意图识别模块 (Intent)

### 1.1 意图分类 (Classify)
结合历史记忆分析用户意图。

* **URL**: `/classify`
* **Method**: `POST`

**请求参数**
```json
{
  "query": "最近30天销量最好的红色连衣裙",
  "preferred_entity": "知衣", // 可选，用户勾选的偏好
  "history": "上一轮对话内容..." // 可选
}

```

**响应示例**

```json
{
  "category": "选品",
  "reasoning": "用户明确查询销量排序的商品...",
  "memory_used": true,
  "retrieved_context": "记忆片段..."
}

```

### 1.2 意图反馈 (Feedback)

纠正分类错误并触发后台学习。

* **URL**: `/feedback`
* **Method**: `POST`

**请求参数**

```json
{
  "query": "找同款",
  "correct_category": "图搜",
  "reason": "这是视觉搜索需求"
}

```

---

## 2. 智能缓存模块 (Cache)

### 2.1 检查缓存 (Check Cache)

在调用昂贵的业务 Agent 前，先检查是否有可复用的参数。

* **URL**: `/cache/check`
* **Method**: `POST`

**请求参数**

```json
{
  "query": "找款连衣裙",
  "history": "",
  "preferred_entity": "知衣"
}

```

**响应示例 (命中)**

```json
{
  "hit": true,
  "agent_type": "zhiyi",
  "score": 0.9998,
  "reason": "Tier 1: Exact Match",
  "final_params": {
    "keywords": "连衣裙",
    "startTime": "2024-01-01", // 已自动校准为当前时间
    "endTime": "2024-01-31"
  }
}

```

### 2.2 保存缓存 (Save Cache)

业务 Agent 执行成功后，将结果保存到向量库。

* **URL**: `/cache/save`
* **Method**: `POST`

**请求参数**

```json
{
  "query": "找款连衣裙",
  "agent_type": "zhiyi",
  "final_json": { "keywords": "连衣裙", "sort": "sales_desc" },
  "history": "",
  "preferred_entity": "知衣"
}

```

---

## 3. 记忆维护模块 (Maintenance)

所有维护接口均针对 `EsVectorStore` 进行操作。

### 3.1 批量导入 (Import)

* **URL**: `/maintenance/import_jsonl`
* **Method**: `POST`
* **参数**: `file` (Multipart/Form-Data)
* **说明**: 支持标准 ReMe 格式或简化版 JSONL。会自动进行向量化处理。

### 3.2 列表查询 (List)

* **URL**: `/maintenance/list`
* **Method**: `GET`
* **参数**: `workspace_id` (可选), `limit` (可选)

### 3.3 手动新增 (Upsert)

* **URL**: `/maintenance/memory`
* **Method**: `POST`
* **Body**:

```json
{
  "workspace_id": "intent_router_v2",
  "when_to_use": "测试触发词",
  "content": "这是一条测试记忆",
  "tags": ["test"]
}

```

### 3.4 导出备份 (Export)

* **URL**: `/maintenance/export`
* **Method**: `GET`
* **说明**: 返回 `.jsonl` 文件流下载。

### 3.5 清空工作区 (Clear)

* **URL**: `/maintenance/clear`
* **Method**: `POST`
* **说明**: 🔥 **高危操作**。删除索引并重建，数据不可恢复。

---

## 附录：意图枚举 (IntentEnum)

| 枚举值 (Value) | 说明 |
| --- | --- |
| `选品` | 查价格、销量排序、看上新等数据查询 |
| `图搜` | 找同款、搜相似、基于图片搜款 |
| `生图改图` | 生成/修改图片、换模特/背景 |
| `趋势报告` | 生成风格报告、市场总结 |
| `媒体` | 搜索小红书/Ins帖子 |
| `店铺` | 查询店铺级大盘数据 |
| `定时任务` | 设置推送、定时提醒 |
| `聊天机器人` | 闲聊、意图不明 |
