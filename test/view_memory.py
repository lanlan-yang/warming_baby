#!/usr/bin/env python3
"""
查看 Chroma 记忆数据库内容的脚本

直接读取 ChromaDB 文件，不需要 embedding API，
即使 API Key 错误或没网也能查看已有记忆。
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
        from core.paths import get_app_dir
        storage_path = str(get_app_dir() / "memory")

        import chromadb
        from chromadb.config import Settings

        client = chromadb.PersistentClient(
            path=storage_path,
            settings=Settings(anonymized_telemetry=False)
        )

        # 列出所有集合
        collections = client.list_collections()
        print(f"\n📊 存储路径: {storage_path}")
        print(f"   集合数: {len(collections)}")

        if not collections:
            print("\n📭 没有任何集合，数据库为空")
            return 0

        for col_info in collections:
            col_name = col_info.name if hasattr(col_info, 'name') else str(col_info)
            print(f"\n{'=' * 60}")
            print(f"集合: {col_name}")
            print(f"{'=' * 60}")

            col = client.get_collection(name=col_name)
            count = col.count()
            print(f"记忆数: {count}")

            if count == 0:
                print("  (空集合)")
                continue

            results = col.get(include=["documents", "metadatas"])

            from collections import defaultdict
            by_type = defaultdict(list)
            for i, (doc, meta) in enumerate(zip(results["documents"], results["metadatas"])):
                mem_type = (meta or {}).get('type', 'unknown')
                by_type[mem_type].append({
                    "id": results["ids"][i],
                    "content": doc,
                    "metadata": meta or {},
                })

            type_names = {
                'fact': '📋 事实',
                'preference': '❤️ 偏好',
                'event': '📅 事件',
                'context': '💬 上下文',
                'skill': '🎯 技能',
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

            print(f"\n  ✓ 共 {count} 条记忆")

    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(view_memory())
