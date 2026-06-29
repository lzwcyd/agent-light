"""PyInstaller 入口 shim。

直接用 agent_light/main.py 作入口会把它当顶层脚本运行，模块内的相对
导入（from .detector ...）找不到父包而失败。这里用绝对导入调用 main()。
"""

from agent_light.main import main

if __name__ == "__main__":
    main()
