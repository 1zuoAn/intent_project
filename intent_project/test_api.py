import pytest
import httpx
import json
import time
from uuid import uuid4

# ================= 配置区域 =================
BASE_URL = "http://127.0.0.1:8000"
WORKSPACE_ID = "intent_router_v2_test"  # 使用新的测试工作区
TEST_MEMORY_ID = f"mem_{uuid4().hex[:8]}"

# 定义测试数据
TEST_TRIGGER = "当用户询问测试脚本怎么写时"  #这是 When to use (存入 Content)
TEST_ANSWER = "告诉用户使用 pytest 编写自动化测试" # 这是 Experience (存入 Metadata)

@pytest.fixture(scope="module")
def client():
    """创建一个全局 HTTP 客户端"""
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as c:
        yield c

# ================= 基础检查 =================

# def test_health_check(client):
#     """0. 确保服务已启动"""
#     try:
#         response = client.get("/docs")
#         assert response.status_code == 200, "无法访问 /docs，服务可能未启动"
#     except httpx.ConnectError:
#         pytest.fail("无法连接到服务器，请确保 main.py 已运行在 localhost:8000")

# # ================= 业务接口测试 =================

def test_classify_intent_selection(client):
    """1. 测试意图分类 - 基础选品"""
    payload = {
        "query": "帮我把这周连衣裙的销量排一下序",
        "preferred_entity": "选品",
        "history": ""
    }
    response = client.post("/classify", json=payload)
    assert response.status_code == 200
    data = response.json()
    
    assert data["category"] == "选品"
    assert len(data["reasoning"]) > 0
    print(f"\n[选品测试] 推理: {data['reasoning']}")

# def test_classify_conflict_resolution(client):
#     """2. 测试冲突处理 (Query优先原则)"""
#     payload = {
#         "query": "帮我找一下这张图的同款", # 明确的图搜意图
#         "preferred_entity": "选品",      # 错误的勾选
#         "history": ""
#     }
#     response = client.post("/classify", json=payload)
#     assert response.status_code == 200
#     data = response.json()
    
#     # 预期：系统应忽略 '选品' 勾选，根据 Query 判为 '图搜'
#     assert data["category"] == "图搜"
#     print(f"\n[冲突测试] 修正分类: {data['category']}")

# def test_feedback_submission(client):
#     """3. 测试反馈提交"""
#     payload = {
#         "query": "测试查询",
#         "correct_category": "图搜",
#         "reason": "Pytest 自动化测试反馈"
#     }
#     response = client.post("/feedback", json=payload)
#     assert response.status_code == 200
#     assert response.json()["status"] == "processing"

# # ================= 维护接口测试 (CRUD) =================

def test_maintenance_01_clear(client):
    """4. 清空测试工作区"""
    response = client.post(f"/maintenance/clear?workspace_id={WORKSPACE_ID}")
    assert response.status_code == 200
    print(f"\n[清理] {response.json()['message']}")

# def test_maintenance_02_upsert(client):
#     """5. 手动插入记忆 (此时 Server 应自动将其转为复杂结构)"""
#     payload = {
#         "workspace_id": WORKSPACE_ID,
#         "unique_id": TEST_MEMORY_ID,
#         "when_to_use": TEST_TRIGGER,  # Trigger
#         "content": TEST_ANSWER,       # Answer
#         "category": "task",
#         "score": 0.95,
#         "tags": ["test", "automation"]
#     }
#     response = client.post("/maintenance/memory", json=payload)
#     assert response.status_code == 200
#     data = response.json()
#     assert data["status"] == "success"
#     assert data["id"] == TEST_MEMORY_ID

# def test_maintenance_03_list_and_verify(client):
#     """6. 查询并验证数据结构 (重点修复部分)"""
#     # 等待 ES 索引刷新
#     time.sleep(1.5)
    
#     response = client.get(f"/maintenance/list?workspace_id={WORKSPACE_ID}")
#     assert response.status_code == 200
#     data = response.json()
    
#     assert data["workspace_id"] == WORKSPACE_ID
#     assert data["total_retrieved"] >= 1
    
#     target_item = None
#     for item in data["items"]:
#         if item["unique_id"] == TEST_MEMORY_ID:
#             target_item = item
#             break
            
#     assert target_item is not None, "未找到刚插入的记忆 ID"
    
#     # === [核心修复] 验证逻辑 ===
#     print(f"\n[数据结构调试] Content: {target_item.get('content')}")
#     print(f"[数据结构调试] Metadata Keys: {target_item.get('metadata', {}).keys()}")

#     # 1. 验证 Trigger (应存储在 vector_node.content)
#     #    之前的报错是因为在这里找 "pytest" (Answer)，但这里其实是 Trigger
#     assert "测试脚本" in target_item["content"], \
#         f"Trigger 匹配失败。期望 '测试脚本' 在 '{target_item['content']}' 中"

#     # 2. 验证 Answer (应存储在 metadata 中)
#     #    根据最新的 _construct_standard_node 逻辑，Answer 存在 metadata.content 或 metadata.metadata(json)
#     meta = target_item.get("metadata", {})
    
#     # 尝试从 metadata.content 找 (ReMe 标准)
#     if "content" in meta:
#         assert "pytest" in meta["content"], \
#             f"Answer 匹配失败 (Metadata)。期望 'pytest' 在 '{meta['content']}' 中"
#     else:
#         # 如果 server 端没存 metadata.content，打印警告
#         print("⚠️ Warning: metadata 中未找到 content 字段，无法验证 Answer")

# def test_maintenance_04_import_jsonl(client, tmp_path):
#     """7. 批量导入 (测试自动升级逻辑)"""
#     # 构造 "简单格式" 的 JSONL，测试 Server 是否能自动转为标准格式
#     simple_jsonl = json.dumps({
#         "unique_id": "batch_01",
#         "content": "当用户问批量导入时", # Trigger
#         "answer": "告诉他这是为了测试兼容性", # Answer (非标准字段，测试 server 能否提取)
#         "workspace_id": WORKSPACE_ID,
#         "metadata": {"tags": ["batch"]}
#     }) + "\n"
    
#     d = tmp_path / "data"
#     d.mkdir()
#     p = d / "test.jsonl"
#     p.write_text(simple_jsonl, encoding="utf-8")
    
#     with open(p, "rb") as f:
#         files = {"file": ("test.jsonl", f, "application/json")}
#         response = client.post(
#             f"/maintenance/import_jsonl?workspace_id_override={WORKSPACE_ID}", 
#             files=files
#         )
    
#     assert response.status_code == 200
#     assert response.json()["imported"] >= 1

# def test_maintenance_05_export(client):
#     """8. 导出验证"""
#     response = client.get(f"/maintenance/export?workspace_id={WORKSPACE_ID}")
#     assert response.status_code == 200
    
#     lines = response.text.strip().split("\n")
#     assert len(lines) >= 2 # 手动插入1条 + 批量导入1条
    
#     # 验证导出的第一条是不是 JSON
#     first = json.loads(lines[0])
#     assert "unique_id" in first
#     assert first.get("vector") == [], "导出时应清空 Vector 以减小体积"

if __name__ == "__main__":
    print("🚀 启动测试 (pytest)...")
    pytest.main(["-v", "test_api.py"])