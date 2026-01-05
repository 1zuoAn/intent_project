import requests
import time

BASE_URL = "http://localhost:8000"

def test_classify(query, preferred=""):
    print(f"🔍 Testing Query: '{query}'")
    resp = requests.post(f"{BASE_URL}/classify", json={
        "query": query,
        "preferred_entity": preferred
    })
    
    if resp.status_code != 200:
        print(f"❌ API Error: {resp.text}")
        return "ERROR", False

    data = resp.json()
    category = data.get('category', 'Unknown')
    memory_used = data.get('memory_used', False)
    
    print(f"   -> Result: 【{category}】")
    print(f"   -> Memory Used: {memory_used}")
    
    context = data.get('retrieved_context', '')
    if context and "暂无" not in context and len(context) > 5:
        print(f"   -> Context Snippet: {context[:50]}...")
    
    return category, memory_used

def send_feedback(query, correct_category):
    print(f"\n📢 Sending Feedback: '{query}' should be '{correct_category}'")
    requests.post(f"{BASE_URL}/feedback", json={
        "query": query,
        "correct_category": correct_category,
        "reason": "意图分流到店铺的基本定义是查询**商铺主体（Store Entity）**层面的数据（非商品层面的查询才有效），还有硬性条件是仅限于淘宝/知衣平台或者没有明确指出其他平台，也默认为淘宝平台，若明确出现其他平台，则需要分流到聊天机器人（告知用户目前智能体暂不支持该平台）"
    })
    print("   -> Feedback sent. Waiting for background processing...")

def main():
    target_query = """老钱风麂皮绒夹克推荐"""
    expected_category = "聊天机器人" 
    
    # print("\n=== Phase 1: 初始测试 (Expect Failure) ===")
    initial_cat, _ = test_classify(target_query)
    
    # if initial_cat != expected_category:
    # print("\n=== Phase 2: 注入记忆 (Feedback) ===")
    # send_feedback(target_query, expected_category)
        # time.sleep(30)
        # print("\n=== Phase 3: 记忆验证 (Polling) ===")
        # # 轮询机制：给后台最多 20 秒时间处理
        # max_retries = 10
        # success = False
        
        # for i in range(max_retries):
        #     print(f"\n⏳ 尝试 #{i+1} ...")
        #     cat, mem_used = test_classify(target_query)
            
        #     # 只有当分类正确 且 用到了记忆 才算成功
        #     if cat == expected_category and mem_used:
        #         print(f"\n🎉🎉🎉 验证成功！在第 {i+1} 次尝试时生效。")
        #         success = True
        #         break
            
        #     if i < max_retries - 1:
        #         time.sleep(2) # 每次等2秒
        
        # if not success:
        #     print("\n❌ 最终失败。可能是 Embedding 没写入，或 LLM 总结超时。")
    # else:
    #     print("⚠️ 初始测试居然直接对了？请换个更难的 Query。")

if __name__ == "__main__":
    main()