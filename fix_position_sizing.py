import re

with open('src/openclaw/position_sizing.py', 'r') as f:
    content = f.read()

# 修復 get_position_limits_for_level 函數
old_code = '''    levels = (
        (policy.get("position_limits") or {}).get("levels")
        if isinstance(policy, Mapping)
        else None
    )
    if not isinstance(levels, Mapping):
        return defaults'''

new_code = '''    if not isinstance(policy, Mapping):
        return defaults
    
    position_limits = policy.get("position_limits")
    if not isinstance(position_limits, Mapping):
        return defaults
    
    levels = position_limits.get("levels")
    if not isinstance(levels, Mapping):
        return defaults'''

content = content.replace(old_code, new_code)

with open('src/openclaw/position_sizing.py', 'w') as f:
    f.write(content)

print("Fixed position_sizing.py")
