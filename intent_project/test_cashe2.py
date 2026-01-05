import requests
import json
import time

# 颜色配置，让输出更直观
class Colors:
    OKGREEN = '\033[92m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

BASE_URL = "http://localhost:8000"

def log(msg, success=None):
    if success is True:
        print(f"{Colors.OKGREEN}✅ {msg}{Colors.ENDC}")
    elif success is False:
        print(f"{Colors.FAIL}❌ {msg}{Colors.ENDC}")
    else:
        print(f"\n{Colors.BOLD}▶️  {msg}{Colors.ENDC}")

def test_maintenance_lifecycle():
    # ==========================================
    # 1. 初始清空 (Flush)
    # ==========================================
    log("Step 1: 正在清空所有缓存 (Flush All)...")
    try:
        resp = requests.delete(f"{BASE_URL}/cache/flush/all")
        if resp.status_code == 200:
            log("缓存清空成功", True)
        else:
            log(f"清空失败: {resp.text}", False)
            return
    except Exception as e:
        log(f"请求异常: {e}", False)
        return

    # 等待 ES 刷新索引
    time.sleep(1)

    # ==========================================
    # 2. 验证清空结果 (List Should be Empty)
    # ==========================================
    log("Step 2: 验证列表是否为空...")
    resp = requests.get(f"{BASE_URL}/cache/list")
    data = resp.json()
    if data['total'] == 0:
        log("列表已空 (Total=0)", True)
    else:
        log(f"列表未空 (Total={data['total']})", False)
        return

    # ==========================================
    # 3. 写入测试数据 (Save)
    # ==========================================
    log("Step 3: 写入一条测试缓存...")
    payload = {
        "query": "测试维护接口专用Query",
        "agent_type": "zhiyi",
        "preferred_entity": "知衣",
        "final_json": {
            "keywords": "测试连衣裙", 
            "sort": "sales_desc",
            "platform": "taobao"
        }
    }
    requests.post(f"{BASE_URL}/cache/save", json=payload)
    
    # 再次等待 ES 刷新
    print("   ⏳ 等待 ES 索引刷新 (1.5s)...")
    time.sleep(1.5)

    # ==========================================
    # 4. 验证写入结果与解析 (List & Check Parsing)
    # ==========================================
    log("Step 4: 查询列表并检查 JSON 解析...")
    resp = requests.get(f"{BASE_URL}/cache/list")
    data = resp.json()
    
    if data['total'] == 1:
        item = data['items'][0]
        log(f"查到 1 条记录 (ID: {item})", True)
        
        # 检查是否展开了 metadata 中的 JSON 字符串
        # 如果展开成功，item 里应该直接有 'keywords' 字段，而不是藏在 metadata 字符串里
        # 检查 api_params 是否存在，且其中包含 keywords
        if "api_params" in item and item["api_params"].get("keywords") == "测试连衣裙":
            log("JSON Metadata 解析成功 (字段已展开)", True)
        else:
            log("JSON Metadata 解析失败 (字段未展开)", False)
            print("   Raw Item:", json.dumps(item, ensure_ascii=False))
            
        target_id = item['id']
    else:
        log(f"写入后查询数量不对: {data['total']}", False)
        return

    # ==========================================
    # 5. 删除指定条目 (Delete One)
    # ==========================================
    log(f"Step 5: 删除指定条目 ({target_id})...")
    resp = requests.delete(f"{BASE_URL}/cache/{target_id}")
    if resp.status_code == 200:
        log("删除请求成功", True)
    else:
        log(f"删除请求失败: {resp.text}", False)

    # 等待 ES 刷新
    time.sleep(1)

    # ==========================================
    # 6. 最终验证 (Final Check)
    # ==========================================
    log("Step 6: 最终验证列表是否为空...")
    resp = requests.get(f"{BASE_URL}/cache/list")
    data = resp.json()
    if data['total'] == 0:
        log("最终验证通过 (Total=0)", True)
        print(f"\n{Colors.OKGREEN}🎉 所有维护接口测试通过！{Colors.ENDC}")
    else:
        log(f"最终验证失败，仍有 {data['total']} 条数据", False)

if __name__ == "__main__":
    try:
        # 简单的服务存活检查
        requests.get(f"{BASE_URL}/docs", timeout=1)
        test_maintenance_lifecycle()
    except requests.exceptions.ConnectionError:
        print(f"{Colors.FAIL}❌ 无法连接服务器，请先运行 'python -m intent_project.main'{Colors.ENDC}")
    except Exception as e:
        print(f"{Colors.FAIL}❌ 测试脚本出错: {e}{Colors.ENDC}")