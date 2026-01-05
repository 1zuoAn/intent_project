import asyncio
import json
from elasticsearch import AsyncElasticsearch

# === 配置信息 ===
ES_USER = "zhixiaoyi-agent-server-yd5"
ES_PASS = "52X5UTfQgIkBYq6q"
ES_HOST = "zhixiaoyi-agent-server-yd5.private.cn-hangzhou.es-serverless.aliyuncs.com:9200"
ES_URL = f"http://{ES_USER}:{ES_PASS}@{ES_HOST}"
TARGET_INDEX = "intent_router_v2_test"  # 你日志里的那个 Workspace ID

async def debug_es_storage():
    print(f"🔍 开始深度排查 ES 数据存储与检索问题...")
    print(f"   目标索引: {TARGET_INDEX}")
    
    client = AsyncElasticsearch(
        hosts=[ES_URL],
        verify_certs=False,
        request_timeout=10
    )

    try:
        # 1. 强制刷新 (解决 "刚存入查不到" 的最常见原因)
        print("\n1️⃣  [操作] 强制刷新索引 (Force Refresh)...")
        await client.indices.refresh(index=TARGET_INDEX)
        print("   ✅ 刷新完成。现在所有已存入的数据都应该是可见的。")

        # 2. 检查索引映射 (Mapping) - 确认 embedding 字段类型
        print("\n2️⃣  [检查] 获取索引映射结构 (Mapping)...")
        mapping = await client.indices.get_mapping(index=TARGET_INDEX)
        props = mapping[TARGET_INDEX]['mappings'].get('properties', {})
        
        # 重点检查 embedding 字段
        emb_field = props.get('embedding')
        if not emb_field:
            print("   ❌ 警告：未找到 'embedding' 字段！")
            print(f"   现有字段: {list(props.keys())}")
        else:
            print(f"   ✅ 'embedding' 字段存在。类型: {emb_field.get('type')}")
            if emb_field.get('type') != 'dense_vector':
                print(f"   ⚠️ 严重警告：类型不是 'dense_vector'，而是 '{emb_field.get('type')}'。")
                print("      这会导致 KNN 搜索失败！可能是自动创建索引时推断错了类型。")

        # 3. 暴力全量查询 (Match All) - 确认数据到底存进去没有
        print("\n3️⃣  [检查] 暴力拉取所有数据 (Match All)...")
        resp = await client.search(
            index=TARGET_INDEX,
            query={"match_all": {}},
            size=3, # 只看前3条
            _source=True 
        )
        hits = resp['hits']['hits']
        total = resp['hits']['total']['value']
        print(f"   📊 索引中总文档数: {total}")
        
        if total == 0:
            print("   ❌ 结论：ES 里是空的！根本没存进去。")
            print("      -> 问题出在 '写入' 阶段 (Save)，而不是召回阶段。")
        else:
            print(f"   ✅ 结论：ES 里有数据 ({total} 条)。")
            print("      -> 问题可能出在 '召回' 阶段 (Recall) 或者字段不匹配。")
            
            # 打印第一条数据的结构，看看长什么样
            first_doc = hits[0]['_source']
            keys = list(first_doc.keys())
            print(f"   📄 第一条数据字段预览: {keys}")
            
            # 检查是否有向量数据
            if 'embedding' in first_doc:
                vec = first_doc['embedding']
                vec_len = len(vec) if isinstance(vec, list) else "Not a list"
                print(f"      - embedding 字段长度: {vec_len}")
                
                # 4. 尝试手动 KNN 搜索 (用刚才查出来的这条向量去搜它自己)
                print("\n4️⃣  [验证] 尝试用第一条数据的向量进行 KNN 搜索...")
                knn_body = {
                    "knn": {
                        "field": "embedding",
                        "query_vector": vec, # 用自己的向量搜自己
                        "k": 3,
                        "num_candidates": 100
                    }
                }
                try:
                    knn_resp = await client.search(index=TARGET_INDEX, body=knn_body)
                    knn_hits = knn_resp['hits']['hits']
                    print(f"   🎯 KNN 搜索结果数: {len(knn_hits)}")
                    if len(knn_hits) > 0:
                        print("   ✅ KNN 搜索成功！说明索引和数据都没问题。")
                        print("      -> 如果 ReMe 搜不到，那是 ReMe 发送的 Query Embedding 有问题。")
                    else:
                        print("   ❌ KNN 搜索返回 0 条！") 
                        print("      -> 这通常意味着 mapping 类型不对，或者维度不匹配。")
                except Exception as e:
                    print(f"   ❌ KNN 搜索报错: {e}")

            else:
                print("   ❌ 严重：数据里没有 'embedding' 字段！")

    except Exception as e:
        print(f"❌ 排查过程发生错误: {e}")

    await client.close()

if __name__ == "__main__":
    asyncio.run(debug_es_storage())