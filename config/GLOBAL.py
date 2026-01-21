# 延迟导入，避免循环导入
PRINT_TO_UI = None
IMAGE_TO_UI = None

# 延迟初始化，仅在需要时才创建实例
_key_mouse_manager_instance = None

def get_key_mouse_manager():
    global _key_mouse_manager_instance
    if _key_mouse_manager_instance is None:
        from utils.key_mouse_manager import KeyMouseManager
        _key_mouse_manager_instance = KeyMouseManager()
    return _key_mouse_manager_instance

key_mouse_manager = get_key_mouse_manager()