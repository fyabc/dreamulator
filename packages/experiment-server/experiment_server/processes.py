"""Native process identity on Windows/Linux; no shell PID killing or token ambiguity."""
import json,os,subprocess,sys
from pathlib import Path


def identity(pid):
    if sys.platform=='win32':
        if not isinstance(pid,int) or pid<=0:return None
        # Numeric PID only, no user command interpolation. CIM CreationDate protects PIDreuse.
        script=f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}'; if ($p) {{ @{{pid=[int]$p.ProcessId; start_ticks=$p.CreationDate.ToUniversalTime().ToString('o'); command=$p.CommandLine; state='R'}} | ConvertTo-Json -Compress }}"
        r=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',script],capture_output=True,encoding='utf-8',errors='replace',timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode:raise ValueError('Windows进程身份查询失败，不能判断进程结束。')
        if not r.stdout.strip():return None
        return json.loads(r.stdout)
    try:
        raw=Path(f'/proc/{pid}/stat').read_text();tail=raw[raw.rfind(')')+2:].split()
        return {'start_ticks':tail[19],'state':tail[0],'cmdline':Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')}
    except (FileNotFoundError,ProcessLookupError):return None


def matches(actual,handle,root):
    if not actual or actual['state']=='Z' or actual['start_ticks']!=handle['start_ticks']:return False
    if 'command' in actual:
        command=actual['command'] or ''
        return 'experiment_server.worker' in command and str(root) in command and handle['token'] in command
    return b'experiment_server.worker' in actual['cmdline'] and str(root).encode() in actual['cmdline'] and handle['token'].encode() in actual['cmdline']
