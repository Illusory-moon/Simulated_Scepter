"""测试小程序兼容入口；实际评估后端位于 ``tool.countdown_evaluator``。"""

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from tool.countdown_evaluator import *  # noqa: F401,F403
from tool.countdown_evaluator import __all__  # noqa: F401
