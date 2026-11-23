# -*- coding: utf-8 -*-
"""龙之谷金币查价器。"""

import io
import sys

# PyInstaller 以 --windowed 方式打包时，sys.stdout / sys.stderr 会被置为 None。
# 第三方库（curl_cffi 在部分错误路径、以及 SSL 相关的告警）会往标准输出写东西，
# 此时会抛 AttributeError: 'NoneType' object has no attribute 'write'，
# 表现为 DD373 抓取失败而其他平台正常。这里换成空缓冲，行为与直接运行一致。
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

__version__ = "1.5.0"
