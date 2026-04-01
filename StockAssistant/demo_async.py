#!/usr/bin/env python3
"""
异步多代理演示 - 展示并行任务执行
"""

import os
import time
for var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(var, None)

def demo_async_vs_sync():
    """对比同步和异步执行时间"""
    print("\n" + "=" * 60)
    print("⚡ 异步 vs 同步 执行对比")
    print("=" * 60)
    
    import asyncio
    from agents import AShareAgent, FundamentalAgent
    
    symbol = "000001"
    
    # ===== 同步执行 =====
    print("\n📊 同步执行 (顺序获取):")
    print("-" * 40)
    
    start_sync = time.time()
    
    print("  1. 获取技术数据...")
    agent1 = AShareAgent()
    tech_result = agent1.run(symbol)
    print(f"     完成: RSI={tech_result.get('technical', {}).get('rsi', 0):.1f}")
    
    print("  2. 获取基本面数据...")
    agent2 = FundamentalAgent()
    funda_result = agent2.run(symbol)
    score = funda_result.get('valuation', {}).get('pe', 0)
    print(f"     完成: PE={score:.2f}")
    
    sync_time = time.time() - start_sync
    print(f"\n  ⏱️ 同步总耗时: {sync_time:.2f}秒")
    
    # ===== 异步执行 =====
    print("\n📊 异步执行 (并行获取):")
    print("-" * 40)
    
    async def parallel_fetch():
        async def get_tech():
            print("  1. [异步] 获取技术数据...")
            agent = AShareAgent()
            result = agent.run(symbol)
            print(f"       完成: RSI={result.get('technical', {}).get('rsi', 0):.1f}")
            return result
        
        async def get_fundamental():
            print("  2. [异步] 获取基本面数据...")
            agent = FundamentalAgent()
            result = agent.run(symbol)
            score = result.get('valuation', {}).get('pe', 0)
            print(f"       完成: PE={score:.2f}")
            return result
        
        # 并行执行
        print("  → 同时开始两个任务...")
        results = await asyncio.gather(get_tech(), get_fundamental())
        return results
    
    start_async = time.time()
    results = asyncio.run(parallel_fetch())
    async_time = time.time() - start_async
    
    print(f"\n  ⏱️ 异步总耗时: {async_time:.2f}秒")
    
    # 对比
    print("\n" + "=" * 60)
    print("📈 性能对比:")
    print(f"   同步: {sync_time:.2f}秒")
    print(f"   异步: {async_time:.2f}秒")
    print(f"   加速: {sync_time/async_time:.1f}x")
    
    if async_time < sync_time:
        print(f"   ✅ 异步更快，节省 {sync_time - async_time:.2f}秒")
    else:
        print(f"   ⚠️ 网络延迟较大时，差异不明显")


def demo_async_workflow():
    """演示异步工作流"""
    print("\n" + "=" * 60)
    print("🚀 异步工作流演示")
    print("=" * 60)
    
    from agents import run_async_workflow
    
    print("\n执行 A股完整分析 (异步并行):")
    print("-" * 40)
    
    start = time.time()
    results = run_async_workflow("a_stock_full", "000001")
    elapsed = time.time() - start
    
    print(f"\n⏱️ 总耗时: {elapsed:.2f}秒")
    
    if results and len(results) >= 2:
        print("\n📊 并行获取结果:")
        print(f"   技术分析: {'成功' if results[0] else '失败'}")
        print(f"   基本面分析: {'成功' if results[1] else '失败'}")


if __name__ == "__main__":
    print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ 异步多代理演示
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """)
    
    demo_async_vs_sync()
    demo_async_workflow()
    
    print("\n✅ 演示完成!")
