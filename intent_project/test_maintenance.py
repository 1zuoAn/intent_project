import requests
import json
import os
import time

# 配置
BASE_URL = "http://localhost:8000"
WORKSPACE_ID = "intent_router_v2_test"

# 颜色输出
def print_pass(msg): print(f"\033[92m[PASS] {msg}\033[0m")
def print_fail(msg): print(f"\033[91m[FAIL] {msg}\033[0m")
def print_info(msg): print(f"\033[94m[INFO] {msg}\033[0m")

def test_clear():
    print_info("--- 1. Testing Clear ---")
    url = f"{BASE_URL}/maintenance/clear?workspace_id={WORKSPACE_ID}"
    resp = requests.post(url)
    if resp.status_code == 200:
        print_pass(f"Workspace cleared: {resp.json()}")
    else:
        print_fail(f"Clear failed: {resp.text}")

def test_import():
    print_info("--- 2. Testing Import JSONL ---")
    
    # 构造我们刚才修正过的记忆 (图搜 vs 选品)
    memories = [
        # 1. 图搜定义 (修正后)
        {
            "unique_id": "39b5e88cf51b44508bb963ecd8b88b59",
            "workspace_id": WORKSPACE_ID,
            "content": "When queries request finding 'similar styles', 'variants' (改款), 'same style' (同款), or 'search by image'.",
            "metadata": {
                "memory_type": "task",
                "content": "Classify as 'Image Search' (图搜).\nCore Intent: **Visual/Style Similarity Retrieval**.\n\nRULES:\n1. 'Find similar styles to this' / 'Recommend variants' (改款/相似款) -> **Image Search**.\n2. 'Do you have the same style?' (有没有同款) -> **Image Search**.\n\nBOUNDARY:\n- If the user asks to 'Design/Draw' a new variant, that is 'Image Design' (生图).\n- If the user filters by text attributes (e.g. 'Red coats under 500 yuan') WITHOUT mentioning similarity/same style, that is 'Product Selection'.",
                "score": 1.0,
                "tags": ["image-search", "find-similar", "variants", "same-style"]
            }
        },
        # 2. 综合仲裁 (修正后)
        {
            "unique_id": "composite_ag_merged_001",
            "workspace_id": WORKSPACE_ID,
            "content": "General arbitrator for queries involving 'Product Search', 'Similar Styles', 'Rankings', vs 'Analysis'.",
            "metadata": {
                "memory_type": "task",
                "content": "CORE RULE: Distinguish based on **Search Mode** (Text vs. Visual) and **Output** (List vs. Insight).\n\n1. **Image Search (图搜)**\n   - **Keywords**: 'Similar' (相似), 'Same Style' (同款), 'This Image' (这张图).\n   - **Intent**: Find items visually resembling a target.\n\n2. **Product Selection (选品)**\n   - **Keywords**: 'Top 10', 'Ranking', 'High Sales', 'New Arrivals'.\n   - **Intent**: Filter items by database attributes (Price, Sales, Date).\n   - **Exclusion**: If query mentions 'Similar/Same', it moves to Image Search.\n\n3. **Trend & Report**\n   - **Keywords**: 'Analyze', 'Why', 'Summary', 'Keywords'.\n   - **Intent**: Insight generation.",
                "score": 1.0,
                "tags": ["intent-arbitration", "image-search-vs-selection"]
            }
        }
    ]
    
    # 写入临时文件
    filename = "test_memories.jsonl"
    with open(filename, "w", encoding="utf-8") as f:
        for m in memories:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
            
    # 上传
    files = {'file': open("/mnt/disk/lzj/agent/reme/data/reme_storage_production/intent_router_v2.jsonl", 'rb')}
    url = f"{BASE_URL}/maintenance/import_jsonl?workspace_id_override={WORKSPACE_ID}"
    resp = requests.post(url, files=files)
    
    if resp.status_code == 200:
        print_pass(f"Import success: {resp.json()}")
    else:
        print_fail(f"Import failed: {resp.text}")
    
    # 清理文件
    os.remove(filename)

def test_list():
    print_info("--- 3. Testing List Memories ---")
    url = f"{BASE_URL}/maintenance/list?workspace_id={WORKSPACE_ID}&limit=10"
    resp = requests.get(url)
    if resp.status_code == 200:
        data = resp.json()
        count = data.get("total", 0)
        print_pass(f"Retrieved {count} memories.")
        if count == 0:
            print_fail("Warning: No memories found! Import might have failed silently.")
    else:
        print_fail(f"List failed: {resp.text}")

def test_classify(query, expected_category, history=None):
    print_info(f"--- Testing Inference: '{query}' ---")
    url = f"{BASE_URL}/classify"
    payload = {
        "query": query,
        "history": history,
        "preferred_entity": None
    }
    
    start = time.time()
    resp = requests.post(url, json=payload)
    duration = time.time() - start
    
    if resp.status_code == 200:
        result = resp.json()
        cat = result.get("category")
        reason = result.get("reasoning")
        used_memory = result.get("memory_used")
        
        if cat == expected_category:
            print_pass(f"Category: {cat} (Expected: {expected_category})")
            print(f"      Reason: {reason}")
            print(f"      Memory Used: {used_memory}")
            print(f"      Time: {duration:.2f}s")
        else:
            print_fail(f"Category: {cat} (Expected: {expected_category})")
            print(f"      Reason: {reason}")
    else:
        print_fail(f"Request failed: {resp.text}")

def test_export():
    print_info("--- 6. Testing Export ---")
    url = f"{BASE_URL}/maintenance/export?workspace_id={WORKSPACE_ID}"
    resp = requests.get(url, stream=True)
    if resp.status_code == 200:
        line_count = 0
        for line in resp.iter_lines():
            if line: line_count += 1
        print_pass(f"Exported file contains {line_count} lines.")
    else:
        print_fail(f"Export failed: {resp.text}")

if __name__ == "__main__":
    try:
        # 1. 清空旧数据
        # test_clear()
        
        # 2. 导入新规则 (包含图搜)
        test_import()
        # print("⏳ Waiting 2 seconds for Elasticsearch refresh...")
        # time.sleep(2)
        # 3. 验证列表
        test_list()
        
        # # 4. 推理测试 (等待几秒确保 ES 索引刷新)
        # print("Waiting for ES refresh...")
        # time.sleep(2) 
        
        # # Case A: 典型的图搜
        # test_classify("帮我找一下图片上这个款", "图搜")
        # test_classify("有没有类似的款式推荐？", "图搜")
        # test_classify("搜同款", "图搜")
        
        # # Case B: 典型的选品 (不应被误判为图搜)
        # test_classify("帮我找一下销量最高的羽绒服", "选品")
        # test_classify("最近上新的连衣裙有哪些", "选品")
        
        # # Case C: 趋势报告
        # test_classify("分析一下为什么这款卖得好", "趋势报告")
        
        # # 5. 导出测试
        test_export()
        
    except Exception as e:
        print_fail(f"Script Error: {e}")