"""Optional read-only endpoint observations, never reconfigure Wi-Fi."""
import re
import subprocess
import time

def capture():
    out=dict(timestamp_ns=time.monotonic_ns(),command=['iw','dev','wlP1p1s0','link'])
    try:
        p=subprocess.run(out['command'],text=True,capture_output=True,timeout=5)
        out.update(returncode=p.returncode,stdout=p.stdout,stderr=p.stderr,status='AVAILABLE' if p.returncode==0 else 'UNAVAILABLE')
        text=p.stdout
        for name,pattern in [('BSSID',r'Connected to ([0-9a-fA-F:]+)'),('signal_dBm',r'signal:\s*([-\d.]+) dBm'),('tx_bitrate_Mbps',r'tx bitrate:\s*([\d.]+) MBit/s')]:
            m=re.search(pattern,text);out[name]=(m.group(1) if name=='BSSID' else float(m.group(1))) if m else None
        out['connected']=True if 'Connected to ' in text else False if 'Not connected' in text else None
    except Exception as e:out.update(status='UNAVAILABLE',error=repr(e))
    return out

def compare(start,end):
    observed=any(x.get('connected') is False for x in (start,end))
    b1,b2=start.get('BSSID'),end.get('BSSID')
    return dict(start=start,end=end,endpoint_disconnected_observed=observed,
        endpoint_BSSID_changed=(b1!=b2) if b1 and b2 else None,
        intervening_disconnect_reconnect='UNOBSERVED: endpoint snapshots cannot exclude reconnects; no event timestamps inferred')
