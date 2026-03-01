#!/usr/bin/env python3
"""
复制 ref_package/tests/ 中的测试文件到 src/tests/ 并修改 import 路径
"""
import os
import shutil

def copy_and_fix_imports(src_dir, dst_dir):
    """复制测试文件并修复 import 路径"""
    if not os.path.exists(dst_dir):
        os.makedirs(dst_dir)
    
    test_files = [
        'test_broker.py',
        'test_drawdown_guard.py', 
        'test_eod_ingest.py',
        'test_llm_observability.py',
        'test_memory_store.py',
        'test_news_guard.py',
        'test_order_store.py',
        'test_orders.py',
        'test_position_sizing.py',
        'test_proposal_engine.py',
        'test_reflection_loop.py',
        'test_risk_engine.py',
        'test_store.py'
    ]
    
    for test_file in test_files:
        src_path = os.path.join(src_dir, test_file)
        dst_path = os.path.join(dst_dir, test_file)
        
        if not os.path.exists(src_path):
            print(f"警告: 源文件不存在: {src_path}")
            continue
            
        # 读取文件内容
        with open(src_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 修改 import 路径
        # 将 from openclaw.xxx 改为 from src.openclaw.xxx
        # 或者直接改为 from openclaw.xxx（如果 pythonpath 已设置）
        # 根据 v4_remaining_tasks.md 说明，需要修改 import
        content = content.replace('from openclaw.', 'from src.openclaw.')
        content = content.replace('import openclaw.', 'import src.openclaw.')
        
        # 写入目标文件
        with open(dst_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"已复制: {test_file}")
    
    print(f"\n总共复制了 {len(test_files)} 个测试文件")

if __name__ == '__main__':
    project_root = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.join(project_root, 'ref_package', 'tests')
    dst_dir = os.path.join(project_root, 'src', 'tests')
    
    copy_and_fix_imports(src_dir, dst_dir)
