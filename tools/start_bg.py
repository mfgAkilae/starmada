"""start_bg.py <exe> <cwd> [args...]: start a program without activating its window.

STARTUPINFO asks for SW_SHOWNOACTIVATE, so the first window does not take the focus
from the user's programs. Prints the process id.
"""
import subprocess
import sys

si = subprocess.STARTUPINFO()
si.dwFlags = subprocess.STARTF_USESHOWWINDOW
si.wShowWindow = 4                       # SW_SHOWNOACTIVATE
p = subprocess.Popen([sys.argv[1]] + sys.argv[3:], cwd=sys.argv[2], startupinfo=si,
                     creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
print(p.pid)
