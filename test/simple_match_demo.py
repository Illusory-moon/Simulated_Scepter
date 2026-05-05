from tool.utils.minimap_util import re_get_position
position=[321,202]
position2=[612.1,605.9]
x=re_get_position(position,need_int=True,re=True)
print(f"{x[0]:.1f},{x[1]:.1f}")
print(re_get_position(position2,need_int=True))
