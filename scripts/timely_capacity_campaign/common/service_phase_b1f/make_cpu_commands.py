"""Render user-run shell commands from actual per-policy snapshot; never execute."""
import shlex


def render(state,restore=False):
    q=shlex.quote
    lines=['#!/usr/bin/env bash','# GENERATED ONLY. Codex must not execute this script.',
           'set -euo pipefail',
           '[[ "$EUID" -eq 0 ]] || { echo "Run this script manually with authorized privileges" >&2; exit 1; }',
           'check() { local actual; actual=$(cat -- "$1"); [[ "$actual" == "$2" ]] || { echo "Readback mismatch: $1 ($actual != $2)" >&2; return 1; }; }',
           'policies=(/sys/devices/system/cpu/cpufreq/policy[0-9]*)',
           '[[ "${policies[*]}" == '+q(' '.join(sorted(r['path'] for r in state['policies'])))+' ]] || { echo "Policy set changed" >&2; exit 1; }',
           'check /sys/devices/system/cpu/online '+q(state['online'])]
    for r in state['policies']:
        f=r['fields'];path=r['path']
        if not all(str(f[k]).isdigit() for k in ('scaling_min_freq','scaling_max_freq')):raise ValueError('Missing/non-integer policy frequency')
        if 'performance' not in f['scaling_available_governors'].split():raise ValueError('Performance governor unavailable')
        for key in ('affected_cpus','related_cpus'):lines+=['check '+q(path+'/'+key)+' '+q(f[key])]
    if not restore:
        lines+=['# Verify ALL original controls before the first write. Abort on stale snapshot.']
        for r in state['policies']:
            for key in ('scaling_governor','scaling_min_freq','scaling_max_freq'):
                lines+=['check '+q(r['path']+'/'+key)+' '+q(r['fields'][key])]
        lines+=['# If any write fails, run CPU_RESTORE_COMMANDS.sh manually; do not launch a workload.']
        for r in state['policies']:
            for key,value in [('scaling_governor','performance'),('scaling_min_freq',r['fields']['scaling_max_freq'])]:
                lines+=["printf '%s\n' "+q(value)+' > '+q(r['path']+'/'+key)]
        for r in state['policies']:
            for key,value in [('scaling_governor','performance'),('scaling_min_freq',r['fields']['scaling_max_freq']),('scaling_max_freq',r['fields']['scaling_max_freq'])]:
                lines+=['check '+q(r['path']+'/'+key)+' '+q(value)]
    else:
        lines+=['# Restore every policy even if a previous write failed; report any failure.', 'restore_failed=0']
        for r in state['policies']:
            for key in ('scaling_min_freq','scaling_max_freq','scaling_governor'):
                lines+=["printf '%s\n' "+q(r['fields'][key])+' > '+q(r['path']+'/'+key)+' || restore_failed=1']
        for r in state['policies']:
            for key in ('scaling_min_freq','scaling_max_freq','scaling_governor'):
                lines+=['check '+q(r['path']+'/'+key)+' '+q(r['fields'][key])+' || restore_failed=1']
        lines+=['[[ "$restore_failed" -eq 0 ]] || { echo "Restore FAILED; inspect all policies" >&2; exit 1; }']
    lines+=['echo '+q('CPU original settings restored' if restore else 'CPU policy controls pinned; verify current-frequency readback before workload')]
    return '\n'.join(lines)+'\n'
