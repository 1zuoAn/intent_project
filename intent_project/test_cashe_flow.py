import requests
import json
import time
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8000"

# 颜色打印工具
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_step(title):
    print(f"\n{Colors.HEADER}{'='*60}\n▶️  {title}\n{'='*60}{Colors.ENDC}")

def log_result(test_name, success, duration, detail):
    # 成功用绿色，失败用红色
    status_icon = "✅" if success else "❌"
    status_color = Colors.OKGREEN if success else Colors.FAIL
    
    # 耗时高亮：超过 1秒 显示为黄色警告
    time_color = Colors.WARNING if duration > 1.0 else Colors.OKBLUE
    time_str = f"[{duration:.4f}s]"
    
    print(f"{status_color}{status_icon} {test_name:<25}{Colors.ENDC} {time_color}{time_str}{Colors.ENDC} {detail}")

def get_dates(days_ago):
    today = datetime.now()
    start = today - timedelta(days=days_ago)
    return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")

# ==========================================
# 1. 构造测试数据
# ==========================================
start_30, end_0 = get_dates(30)
start_7, end_0 = get_dates(7)

TEST_CASES = [
    {
        "name": "知衣-连衣裙",
        "agent_type": "zhiyi",
        "preferred_entity": "",
        "query": "帮我找最近30天销量最好的红色连衣裙",
        "params": {
            "keywords": "红色连衣裙",
            "sort": "sales_desc",
            "platform": "taobao",
            "filters": ["颜色:红色"],
            "startTime": start_30, 
            "endTime": end_0
        }
    },
    {
        "name": "抖衣-卫衣",
        "agent_type": "douyi",
        "preferred_entity": "",
        "query": "抖音最近7天卫衣，按销量排名",
        "params": {
            "keyword": "卫衣",
            "sortField": "live_sales",
            "sortType": "desc",
            "propertyList": [],
            "sortStartDate": start_7,
            "sortEndDate": end_0
        }
    },
    {
        "name": "海外-Shein",
        "agent_type": "abroad",
        "preferred_entity": "",
        "query": "Shein站点最近14天碎花裙上架情况，按照销量排名",
        "params": {
            "keyword": "碎花裙",
            "site": "shein",
            "platform": "shein",
            "minSaleVolumeTotal": 100
        }
    }
]

# ==========================================
# 2. 执行测试
# ==========================================

def run_tests():
    # --- Step 1: 存入缓存 (Save Cache) ---
    # print_step("Phase 1: 存入缓存 (Save Cache)")
    
    # for case in TEST_CASES:
    #     payload = {
    #         "query": case["query"],
    #         "agent_type": case["agent_type"],
    #         "preferred_entity": case["preferred_entity"],
    #         "history": "",
    #         "final_json": case["params"]
    #     }
    #     try:
    #         start_t = time.time()
    #         # resp = requests.post(f"{BASE_URL}/cache/save", json=payload)
    #         duration = time.time() - start_t
            
    #         if resp.status_code == 200:
    #             log_result(f"Save {case['name']}", True, duration, "Saved successfully")
    #         else:
    #             log_result(f"Save {case['name']}", False, duration, f"Failed: {resp.text}")
    #     except Exception as e:
    #         log_result(f"Save {case['name']}", False, 0, f"Error: {e}")

    # # 等待 ES 刷新
    # print(f"\n{Colors.OKCYAN}⏳ Waiting 2 seconds for ES refresh...{Colors.ENDC}")
    # time.sleep(2)

    # --- Step 2: 验证 Tier 1 (完全一致 - 极速) ---
    print_step("Phase 2: 测试 Tier 1 直接命中 (Expect Fast)")
    
    for case in TEST_CASES:
        payload = {
            "query": case["query"], 
            "preferred_entity": case["preferred_entity"]
        }
        
        start_t = time.time()
        resp = requests.post(f"{BASE_URL}/cache/check", json=payload).json()
        duration = time.time() - start_t
        
        is_hit = resp.get("hit") is True
        score = resp.get("score", 0)
        reason = resp.get("reason", "")
        
        success = is_hit and score > 0.99
        log_result(
            f"Tier 1 {case['name']}", 
            success, 
            duration,
            f"Hit={is_hit}, Score={score:.4f}, Reason={reason}"
        )

    # --- Step 3: 验证 Tier 2 (语义相似 - 较慢) ---
    print_step("Phase 3: 测试 Tier 2 高相似度 (Expect Slower)")
    
    tier2_scenarios = [
        {
            "target": "知衣-连衣裙",
            "new_query": "我想要知道最近30天上红色连衣裙的销量排行",
            "preferred_entity": ""
        },
        {
            "target": "抖衣-卫衣",
            "new_query": "能不能给我一份抖音的卫衣销量数据7天排名",
            "preferred_entity": ""
        }
    ]

    for case in tier2_scenarios:
        payload = {"query": case["new_query"], "preferred_entity": case["preferred_entity"]}
        
        start_t = time.time()
        resp = requests.post(f"{BASE_URL}/cache/check", json=payload).json()
        duration = time.time() - start_t
        
        is_hit = resp.get("hit") is True
        score = resp.get("score", 0)
        reason = resp.get("reason", "")
        
        success = is_hit and "Judge Approved" in reason
        log_result(
            f"Tier 2 {case['target']}", 
            success, 
            duration,
            f"Hit={is_hit}, Score={score:.4f}, Reason={reason}"
        )

    # --- Step 4: 验证 Miss (拒绝 - 较慢) ---
    print_step("Phase 4: 测试 拒绝/未命中 (Reject/Miss)")
    
    miss_scenarios = [
        {
            "name": "属性冲突-颜色不同",
            "new_query": "帮我找最近30天销量最好的黑色连衣裙", 
            "expect_reason": "Rejected"
        },
        {
            "name": "品类冲突",
            "new_query": "抖音最近7天羽绒服的销量排名", 
            "expect_reason": "Rejected"
        },
        {
            "name": "完全无关",
            "new_query": "今天天气怎么样",
            "expect_reason": "Tier 3"
        }
    ]

    for case in miss_scenarios:
        payload = {"query": case["new_query"], "preferred_entity": "知衣"}
        
        start_t = time.time()
        resp = requests.post(f"{BASE_URL}/cache/check", json=payload).json()
        duration = time.time() - start_t
        
        is_hit = resp.get("hit")
        score = resp.get("score", 0)
        reason = resp.get("reason", "")
        
        # 成功定义：没有命中，且理由符合预期
        success = (is_hit is False) and (case["expect_reason"] in reason or score < 0.90)
        
        log_result(
            f"MissTest {case['name']}", 
            success, 
            duration,
            f"Hit={is_hit}, Score={score:.4f}, Reason={reason}"
        )

if __name__ == "__main__":
    try:
        requests.get(f"{BASE_URL}/docs", timeout=1)
        print(f"{Colors.OKGREEN}Server is UP. Starting benchmark...{Colors.ENDC}")
        run_tests()
    except Exception as e:
        print(f"{Colors.FAIL}Server seems DOWN. Please run 'python -m intent_project.main' first.\nError: {e}{Colors.ENDC}")