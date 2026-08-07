#!/usr/bin/env python3
"""
查看 Chroma 记忆数据库内容的脚本
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

def view_memory():
    print("=" * 60)
    print("Chroma 记忆数据库浏览器")
    print("=" * 60)
    
    try:
        # 初始化记忆系统
        from memory import get_memory_manager
        manager = get_memory_manager()
        
        if not manager.is_ready:
            print("\n📦 正在初始化记忆系统...")
            manager.initialize()
        
        # 获取所有记忆
        all_memories = manager.get_all_memories()
        
        print(f"\n📊 数据库统计:")
        print(f"   总记忆数: {len(all_memories)}")
        print(f"   存储路径: {manager._store._storage_path}")
        
        if all_memories:
            # 按类型分组
            from collections import defaultdict
            by_type = defaultdict(list)
            for m in all_memories:
                mem_type = m['metadata'].get('type', 'unknown')
                by_type[mem_type].append(m)
            
            print(f"\n📝 记忆内容:")
            print("-" * 60)
            
            # 显示各类型
            type_names = {
                'fact': '📋 事实 (Fact)',
                'preference': '❤️ 偏好 (Preference)',
                'event': '📅 事件 (Event)',
                'context': '💬 上下文 (Context)',
                'skill': '🎯 技能 (Skill)',
            }
            
            for mem_type, memories in sorted(by_type.items()):
                print(f"\n【{type_names.get(mem_type, mem_type)}】({len(memories)} 条)")
                print("-" * 60)
                
                for i, mem in enumerate(memories, 1):
                    meta = mem['metadata']
                    created = meta.get('created_at', 'unknown')
                    content = mem['content']
                    field = meta.get('field', '-')
                    importance = meta.get('importance', 0.5)
                    access = meta.get('access_count', 0)
                    print(f"  {i}. [{field:8s}] {content}")
                    print(f"     ID: {mem['id'][:12]}... | 重要性 {importance:.0%} | 访问 {access}次")
                    print(f"     创建: {created}")
            
            print("\n" + "-" * 60)
            print(f"✓ 共 {len(all_memories)} 条记忆")
        else:
            print("\n📭 数据库为空，没有任何记忆")
            
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(view_memory())
