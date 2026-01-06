import requests
import json
import time
from datetime import datetime

# ================= 配置区 =================
BASE_URL = "http://localhost:8000"
HEADERS = {"Content-Type": "application/json"}

class Colors:
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def log_section(title):
    print(f"\n{Colors.CYAN}{Colors.BOLD}{'='*60}\n👉 正在测试接口: {title}\n{'='*60}{Colors.RESET}")

def pretty_json(data):
    return json.dumps(data, indent=2, ensure_ascii=False)

def run_test_case(desc, cache_data, new_query, expected_checks):
    """
    通用测试执行器
    :param desc: 测试描述
    :param cache_data: 存入缓存的完整 Payload (包含 agent_type, route_key, final_json 等)
    :param new_query: 新的用户查询 (用于撞库)
    :param expected_checks: 一个回调函数，用于验证结果
    """
    print(f"\n{Colors.YELLOW}>>> [Step 1] 正在写入缓存 (模拟历史查询)...{Colors.RESET}")
    print(f"   🔹 缓存Query: {cache_data['query']}")
    print(f"   🔹 路由 Key : {cache_data.get('route_key')}")
    print(f"   🔹 原始参数 (Payload): \n{Colors.CYAN}{pretty_json(cache_data['final_json'])}{Colors.RESET}")
    
    # 1. 存入
    try:
        resp = requests.post(f"{BASE_URL}/cache/save", json=cache_data, headers=HEADERS)
        if resp.status_code != 200:
            print(f"{Colors.RED}❌ 缓存写入失败: {resp.text}{Colors.RESET}")
            return
        print(f"{Colors.GREEN}✅ 缓存写入成功{Colors.RESET}")
    except Exception as e:
        print(f"{Colors.RED}❌ 请求异常: {e}{Colors.RESET}")
        return

    # 2. 查询
    print(f"\n{Colors.YELLOW}>>> [Step 2] 发起新查询 (模拟用户当前意图)...{Colors.RESET}")
    print(f"   🔸 当前Query: {new_query}")
    
    try:
        check_payload = {
            "query": new_query,
            "preferred_entity": cache_data.get("preferred_entity")
        }
        start_t = time.time()
        resp = requests.post(f"{BASE_URL}/cache/check", json=check_payload, headers=HEADERS)
        duration = time.time() - start_t
        result = resp.json()
        
        print(f"   ⏱️ 耗时: {duration:.4f}s")
        
        if result.get("hit"):
            print(f"{Colors.GREEN}✅ 命中缓存! Score: {result.get('score')}{Colors.RESET}")
            print(f"   🔹 返回路由: {result.get('route_key')}")
            print(f"   🔹 最终参数 (已校准): \n{Colors.GREEN}{pretty_json(result.get('final_params'))}{Colors.RESET}")
            
            # 执行自定义校验
            expected_checks(result["final_params"])
        else:
            print(f"{Colors.RED}❌ 未命中缓存. Reason: {result.get('reason')} | Score: {result.get('score')}{Colors.RESET}")

    except Exception as e:
        print(f"{Colors.RED}❌ 查询异常: {e}{Colors.RESET}")


# ==============================================================================
# 测试用例 1: 抖衣 - 综合查数接口 (覆盖 params1/params2, 季节, 上架时间)
# 来源: v1.0.1-抖衣查数agent.json -> "params" 节点
# ==============================================================================
def test_douyi_main():
    log_section("抖衣 - 商品列表主接口 (含 params1/params2)")
    
    # 模拟真实 Payload
    payload = {
        "query": "2024年夏季连衣裙销量排行",
        "agent_type": "douyi",
        "preferred_entity": "抖音",
        "route_key": "douyi_goods_list",  # 对应后端 /goods-zone-list
        "final_json": {
            "params1": {
                "rootCategoryId": 20005,
                "categoryIdList": [20169],
                "minPrice": 5000,
                "maxPrice": 10000,
                "yearSeason": "2024年夏季",        # [关键] 旧季节
                "minFirstRecordDate": "2024-05-01", # [关键] 旧上架时间
                "maxFirstRecordDate": "2024-08-01",
                "sortStartDate": "2024-05-01",      # [关键] 旧统计时间
                "sortEndDate": "2024-05-07",
                "sortField": "saleVolumeDaily",
                "hotProperties": [["风格:甜美"]],
                "isMonitorShop": 0
            },
            "params2": {
                "keyword": "连衣裙",
                "sortStartDate": "2024-05-01",
                "limit": 50
            }
        }
    }
    
    def checks(params):
        p1 = params["params1"]
        # 验证 2025年 跨年更新
        if "2025" in p1["sortStartDate"]:
            print(f"   ✨ 校验通过: 统计时间已更新至 2025 ({p1['sortStartDate']})")
        else:
            print(f"{Colors.RED}   💀 校验失败: 统计时间未更新{Colors.RESET}")
            
        if p1.get("yearSeason") == "2025年夏季":
             print(f"   ✨ 校验通过: 年份季节已更新至 2025年夏季")
        else:
             print(f"{Colors.RED}   💀 校验失败: 季节字段未更新 (Got: {p1.get('yearSeason')}){Colors.RESET}")

    run_test_case("抖衣跨年测试", payload, "2025年夏季连衣裙销量排行", checks)


# ==============================================================================
# 测试用例 2: 知衣 - 全网选品接口 (覆盖 startDate/endDate)
# 来源: v1.0.1-知衣查数agent.json -> "params" 节点 (Flag=2, 普通选品)
# ==============================================================================
def test_zhiyi_general():
    log_section("知衣 - 全网选品通用接口")
    
    payload = {
        "query": "最近30天全网热销卫衣",
        "agent_type": "zhiyi",
        "preferred_entity": "知衣",
        "route_key": "zhiyi_general_search", # 对应 /item/simple-item-list
        "final_json": {
            "params1": {
                "categoryIdList": ["5001"],
                "minVolume": 100,
                "startDate": "2024-01-01", # 旧时间
                "endDate": "2024-01-31",
                "sortField": "sale_volume_desc",
                "limit": 6000
            }
        }
    }
    
    def checks(params):
        p1 = params["params1"]
        # 验证是否更新到当前时间 (假设当前是 2026年)
        current_year = datetime.now().strftime("%Y")
        if current_year in p1["endDate"]:
            print(f"   ✨ 校验通过: 结束时间已更新至当前 ({p1['endDate']})")
        else:
            print(f"{Colors.RED}   💀 校验失败: 时间未更新{Colors.RESET}")

    run_test_case("知衣全网搜", payload, "最近30天全网热销卫衣", checks)


# ==============================================================================
# 测试用例 3: 知衣 - 店铺详情接口 (覆盖 shopId, Scope拦截)
# 来源: v1.0.1-知衣查数agent.json -> "params4" 节点
# ==============================================================================
def test_zhiyi_shop():
    log_section("知衣 - 店铺详情接口 (含 shopId)")
    
    payload = {
        "query": "查询 ZARA 店铺的销量",
        "agent_type": "zhiyi",
        "preferred_entity": "知衣",
        "route_key": "zhiyi_shop_detail", # 对应 /item/shop/all-item-list
        "final_json": {
            "params1": {
                "shopId": 12345678,  # [关键] 店铺ID
                "keyword": "",
                "startDate": "2024-01-01",
                "endDate": "2024-01-31"
            }
        }
    }
    
    def checks(params):
        p1 = params["params1"]
        if p1.get("shopId") == 12345678:
            print(f"   ✨ 校验通过: 店铺ID (12345678) 保持一致")
        else:
             print(f"{Colors.RED}   💀 校验失败: 店铺ID丢失{Colors.RESET}")

    # Case A: 正常复用 (同店铺，不同时间)
    run_test_case("知衣店铺搜-正常复用", payload, "查询 ZARA 店铺最近7天销量", checks)
    
    # Case B: 冲突复用 (搜全网，期望拦截)
    # 这里我们不用 run_test_case，因为期望是 Fail
    print(f"\n{Colors.YELLOW}>>> [特殊测试] 用'全网'意图去撞'店铺'缓存 (期望拦截)...{Colors.RESET}")
    resp = requests.post(f"{BASE_URL}/cache/check", json={"query": "全网销量最高的", "preferred_entity": "知衣"}, headers=HEADERS)
    res = resp.json()
    if res['hit'] is False:
        print(f"{Colors.GREEN}✅ 成功拦截! Reason: {res.get('reason')}{Colors.RESET}")
    else:
        print(f"{Colors.RED}❌ 拦截失败! 居然命中了?{Colors.RESET}")


# ==============================================================================
# 测试用例 4: 知衣 - 热销/榜单接口 (覆盖 dateRange 数组, saleStartDate)
# 来源: v1.0.1-知衣查数agent.json -> "params1"/"params3" 节点
# ==============================================================================
def test_zhiyi_hot():
    log_section("知衣 - 热销榜单接口 (含 dateRange 数组)")
    
    payload = {
        "query": "最近7天新品榜单",
        "agent_type": "zhiyi",
        "preferred_entity": "知衣",
        "route_key": "zhiyi_hot_list", # 对应 /item/list
        "final_json": {
            "params1": {
                "dateRange": ["2024-01-01", "2024-01-07"], # [关键] 数组时间
                "saleStartDate": "2024-01-01",             # [关键] 上架时间
                "saleEndDate": "2024-01-07",
                "type": "new"
            }
        }
    }
    
    def checks(params):
        p1 = params["params1"]
        dr = p1.get("dateRange")
        # 验证数组是否被更新为当前时间
        current_year = datetime.now().strftime("%Y")
        if dr[0] != "2024-01-01":
            print(f"   ✨ 校验通过: DateRange数组已更新 ({dr})")
        else:
            print(f"{Colors.RED}   💀 校验失败: DateRange未更新{Colors.RESET}")
            
        if current_year in p1.get("saleStartDate", ""):
            print(f"   ✨ 校验通过: saleStartDate已更新")

    run_test_case("知衣热销榜单", payload, "最近7天新品榜单", checks)


# ==============================================================================
# 测试用例 5: 海外 - 文本搜索 (覆盖 putOnSaleStartDate)
# 来源: v2.0.2-海外探款查数agent-v2.json -> "params" 节点
# ==============================================================================
def test_abroad_text():
    log_section("海外 - 文本搜索接口")
    
    payload = {
        "query": "Tiktok dress sales last month",
        "agent_type": "abroad",
        "preferred_entity": "海外",
        "route_key": "abroad_text_search", # 对应 /overseas/goods/search
        "final_json": {
            "params1": {
                "site": "tiktok",
                "keyword": "dress",
                "putOnSaleStartDate": "2024-01-01", # [关键] 海外特有字段
                "putOnSaleEndDate": "2024-01-31",
                "sort": "volume_desc"
            },
            "params2": {
                "site": "tiktok",
                "startTime": "2024-01-01"
            }
        }
    }
    
    def checks(params):
        p1 = params["params1"]
        current_year = datetime.now().strftime("%Y")
        if current_year in p1["putOnSaleStartDate"]:
            print(f"   ✨ 校验通过: putOnSaleStartDate 已更新 ({p1['putOnSaleStartDate']})")
        else:
            print(f"{Colors.RED}   💀 校验失败: 时间未更新{Colors.RESET}")

    # 使用中文搜英文缓存，测试语义复用
    run_test_case("海外文本搜 (中搜英)", payload, "Tiktok上最近一个月连衣裙销量", checks)


if __name__ == "__main__":
    print(f"{Colors.BOLD}🚀 开始全接口覆盖测试... Target: {BASE_URL}{Colors.RESET}")
    
    test_douyi_main()
    test_zhiyi_general()
    test_zhiyi_shop()
    test_zhiyi_hot()
    test_abroad_text()
    
    print(f"\n{Colors.BOLD}🎉 所有测试执行完毕。请仔细检查上方每个接口的 [校验通过] 状态。{Colors.RESET}")