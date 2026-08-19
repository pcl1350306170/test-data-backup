# -*- coding: utf-8 -*-
try:
    import flowlauncher
    import os
    print("flowlauncher at:", os.path.dirname(flowlauncher.__file__))
except ImportError:
    print("flowlauncher NOT installed in this interpreter")
