Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W {
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
    [StructLayout(LayoutKind.Sequential)] public struct R { public int L, T, Rr, B; }
}
"@
$r = New-Object W+R
[W]::GetWindowRect([IntPtr]1971054, [ref]$r) | Out-Null
"browser window size={0}x{1} pos=({2},{3})" -f ($r.Rr-$r.L), ($r.B-$r.T), $r.L, $r.T
# 控制面板窗口（同进程的其它可见窗口）
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class W2 {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr h);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int c);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out Rect r);
    public delegate bool EnumProc(IntPtr h, IntPtr l);
    [StructLayout(LayoutKind.Sequential)] public struct Rect { public int L, T, R, B; }
}
"@
$found = @()
$cb = [W2+EnumProc]{
    param($h, $l)
    $op = 0
    [W2]::GetWindowThreadProcessId($h, [ref]$op) | Out-Null
    if ($op -eq 16076 -and [W2]::IsWindowVisible($h)) {
        $len = [W2]::GetWindowTextLength($h)
        $sb = New-Object System.Text.StringBuilder ($len + 2)
        [W2]::GetWindowText($h, $sb, $sb.Capacity) | Out-Null
        $rc = New-Object W2+Rect
        [W2]::GetWindowRect($h, [ref]$rc) | Out-Null
        $script:found += ("{0}  size={1}x{2} pos=({3},{4})" -f $sb.ToString(), ($rc.R-$rc.L), ($rc.B-$rc.T), $rc.L, $rc.T)
    }
    return $true
}
[W2]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
$found
