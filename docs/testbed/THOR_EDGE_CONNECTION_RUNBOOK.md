# Thor–Edge connection and evidence runbook

This runbook records the operator-verified connection directions for this testbed session. Reuse the roles and ordering for Edge preflight, Block B, hybrid, and controller campaigns; substitute only that campaign's frozen namespace, plan, and commands. It does not authorize a workload or a system-setting change. Preserve every failed attempt in its original namespace; use a newly frozen namespace for any later attempt.

## Endpoints and distinct roles

| Role | Endpoint | Connection role |
| --- | --- | --- |
| Thor | `thor`, `192.168.0.189`, SSH `ainet@192.168.0.189` | Edge → Thor SSH/SCP and ICMP passed in operator terminals |
| Edge WSL | `CY415AINET`, currently `192.168.0.6` | Thor → Edge IP ping; Edge hosts inference listener |
| Inference | Thor → current frozen Edge IP, presently `192.168.0.6:5000` TCP | Frozen client/server protocol after listener readiness |

Thor → Edge SSH/SCP on port 22 failed with `No route to host` in this session. Use **Edge → Thor SSH/SCP** for file and evidence transfer. The behavior of SSH port 22 does not establish the behavior of inference port 5000. Thor's current route and L2 neighbor evidence can exist even when Edge does not answer ICMP echo; a failed ping alone is neither a route failure nor a capacity result.

## Endpoint freshness before every network campaign

Edge WSL/DHCP addressing may change. The historical Edge IP `192.168.0.7` became stale; Final02's pre-execution reachability check failed before CPU pin or scientific workload. Treat IPs in older documents as historical, never as permanent configuration.

Before freezing each plan, obtain the current endpoint on **Edge** and record operator evidence:

```bash
hostname
hostname -I
ip -br addr
ip route
```

Use the operator-verified IPv4 address explicitly in the plan and an `EDGE_ENDPOINT_MANIFEST.json` with hostname, Thor IP, subnet, inference port, provenance, and timestamp scope. Before CPU pin, compare the current Edge address with the frozen plan and manifest. On any mismatch, **stop**: do not pin CPU or start a workload; correct the endpoint, regenerate the plan SHA and entire bundle, and verify the regenerated hashes. Thor requires `ip route get <edge_ip>` to succeed. It records `ip neigh show <edge_ip>` and `ping -c 2 -W 1 <edge_ip>` as diagnostics only. ICMP failure alone never blocks CPU pin. These checks do not test port 5000. Check listener readiness from exact Edge server `LISTENING` stdout and Edge-local `ss -ltnp | grep ':5000'`; never create an active protocol probe.

## Final02 operator sequence

The concrete Final02 commands live in [DEPLOYMENT_THOR.md](../../results/timely_capacity_campaign/v2_2/edge_preflight_final02/DEPLOYMENT_THOR.md) and [DEPLOYMENT_EDGE.md](../../results/timely_capacity_campaign/v2_2/edge_preflight_final02/DEPLOYMENT_EDGE.md). The corrected Final02 plan SHA-256 is `4d4e5e4db784691fc188f15b0feb51c5710eb0a90db3b527f5048c2feb14b52f`; the earlier `b9c8b2b478d1740c677ad57a65f3ba66f7a4fb015cb0bf7e0369e6a18cb427ea` is preserved as endpoint-stale evidence and must not be used for launch.

1. After rechecking the Edge endpoint locally, on Thor before CPU pin run `python3 -B scripts/timely_capacity_campaign/edge_preflight_final02/run_thor.py check`. It requires frozen artifacts, a fresh namespace, CPU-evidence freshness, and a route to `192.168.0.6`. Neighbor and ICMP records are diagnostic. Stop on a **hard check failure**; an ICMP-only warning does not block CPU pin or create an attempt marker.
2. On Edge, create the fresh `/tmp/edge_preflight_final02_bundle` directory, pull the bundle from Thor, and verify `SHA256SUMS`:

   ```bash
   test ! -e /tmp/edge_preflight_final02_bundle || { echo 'STOP: bundle exists' >&2; exit 1; }
   mkdir /tmp/edge_preflight_final02_bundle
   scp ainet@192.168.0.189:/home/ainet/research/thor-mec-rate-dvfs-gate/results/timely_capacity_campaign/v2_2/edge_preflight_final02/edge_bundle/\* /tmp/edge_preflight_final02_bundle/
   cd /tmp/edge_preflight_final02_bundle
   sha256sum -c SHA256SUMS
   ```

3. The user pins Thor CPU using the frozen `CPU_PIN_COMMANDS.sh`, then records current `CPU_PIN_READBACK.json` PASS through `run_thor.py cpu-pinned`. No CPU pin before steps 1–2 pass. Codex does not run `sudo` or change CPU settings.

   ```bash
   # Thor terminal; user runs this after the Edge bundle SHA check
   cd /home/ainet/research/thor-mec-rate-dvfs-gate
   sudo bash results/timely_capacity_campaign/v2_2/edge_preflight_final02/CPU_PIN_COMMANDS.sh
   python3 -B scripts/timely_capacity_campaign/edge_preflight_final02/run_thor.py cpu-pinned
   ```

4. On Edge, launch the frozen base server with the exact engine, cache, session plan, and SHA command in `DEPLOYMENT_EDGE.md`. Wait for exact stdout `LISTENING 5000: 8 BASE sessions`, then record Edge-local `ss -ltnp | grep ':5000'`. This reads the Edge socket table and opens no protocol connection. The server command must not be shortened or replaced with a health-check session.
5. On Thor, create the fresh `operator_evidence` directory. On Edge, push `edge_base_stdout.txt` and `edge_base_ss.txt` to Thor; then on Thor run `listener-confirmed --stage BASE`. Only after PASS may Thor invoke `base` once.

   ```bash
   # Thor terminal, before Edge transfer
   mkdir /home/ainet/research/thor-mec-rate-dvfs-gate/results/timely_capacity_campaign/v2_2/edge_preflight_final02/operator_evidence

   # Edge terminal, after exact LISTENING and Edge-local ss checks
   scp /tmp/edge_preflight_final02_bundle/edge_base_stdout.txt /tmp/edge_preflight_final02_bundle/edge_base_ss.txt ainet@192.168.0.189:/home/ainet/research/thor-mec-rate-dvfs-gate/results/timely_capacity_campaign/v2_2/edge_preflight_final02/operator_evidence/
   ```

6. If the frozen E88 selector yields a non-`NONE` branch, Edge pulls the exact selection file from Thor, launches only the selected extension session, and repeats the stdout/Edge-local `ss` evidence push before Thor `listener-confirmed --stage EXTENSION` and `extension`:

   ```bash
   # Edge terminal; require a fresh destination
   test ! -e /tmp/edge_preflight_final02_bundle/extension_selection.json || { echo 'STOP: selection exists' >&2; exit 1; }
   scp ainet@192.168.0.189:/home/ainet/research/thor-mec-rate-dvfs-gate/results/timely_capacity_campaign/v2_2/edge_preflight_final02/extension_selection.json /tmp/edge_preflight_final02_bundle/extension_selection.json
   scp /tmp/edge_preflight_final02_bundle/edge_extension_stdout.txt /tmp/edge_preflight_final02_bundle/edge_extension_ss.txt ainet@192.168.0.189:/home/ainet/research/thor-mec-rate-dvfs-gate/results/timely_capacity_campaign/v2_2/edge_preflight_final02/operator_evidence/
   ```

7. After success, failure, or interruption, the user restores Thor CPU with the frozen `CPU_RESTORE_COMMANDS.sh` and records `CPU_RESTORE_READBACK.json` PASS before analysis. Do not re-run an exclusive readback action if its file exists.

   ```bash
   # Thor terminal; user-run restore
   cd /home/ainet/research/thor-mec-rate-dvfs-gate
   sudo bash results/timely_capacity_campaign/v2_2/edge_preflight_final02/CPU_RESTORE_COMMANDS.sh
   python3 -B scripts/timely_capacity_campaign/edge_preflight_final02/run_thor.py cpu-restored
   ```
8. Thor creates fresh `received_edge_base` and, only if E88 ran, `received_edge_extension` directories. Edge pushes its raw server output into them. Keep run-ID subdirectory names and both hosts' originals:

   ```bash
   # Thor terminal, after CPU restore PASS
   mkdir /home/ainet/research/thor-mec-rate-dvfs-gate/results/timely_capacity_campaign/v2_2/edge_preflight_final02/received_edge_base
   # If E88 ran, also run:
   mkdir /home/ainet/research/thor-mec-rate-dvfs-gate/results/timely_capacity_campaign/v2_2/edge_preflight_final02/received_edge_extension

   # Edge terminal
   cd ~/research/thor-mec-inference
   scp -r results/timely_capacity_campaign/v2_2/edge_preflight_final02/edge_base_final02/* ainet@192.168.0.189:/home/ainet/research/thor-mec-rate-dvfs-gate/results/timely_capacity_campaign/v2_2/edge_preflight_final02/received_edge_base/
   # If E88 ran, also run:
   scp -r results/timely_capacity_campaign/v2_2/edge_preflight_final02/edge_extension_final02/* ainet@192.168.0.189:/home/ainet/research/thor-mec-rate-dvfs-gate/results/timely_capacity_campaign/v2_2/edge_preflight_final02/received_edge_extension/
   ```

   Thor runs the frozen analyzer only after CPU restore PASS and the required server output transfer. Do not merge server output into Thor run directories.

## Readiness and failure handling

Never use `nc`, `telnet`, `curl :5000`, `socket.create_connection`, a dummy HELLO, a synthetic session, a warmup request, or dummy inference to probe readiness. A probe can consume frozen server session state. The two readiness observations are the exact server `LISTENING` stdout line and Edge-local `ss` LISTEN row. Thor's inference connection occurs only during the approved workload, after `listener-confirmed` PASS.

| Observation | Interpretation and action |
| --- | --- |
| `NETWORK_ICMP_UNAVAILABLE` with route PASS | ICMP echo diagnostic only; proceed to the independent listener evidence gate. No capacity result. |
| `PRE_EXECUTION_ROUTE_FAILURE` | `ip route get <edge_ip>` failed or did not name the planned destination. Hard stop before CPU pin, attempt marker or workload. |
| `No route to host` on SSH | Route or that SSH direction's connectivity problem; no capacity result. Do not switch to an unverified transfer direction. |
| `INVALID_PRE_WORKLOAD_NETWORK_CONNECT` | Actual inference connection refused after listener evidence: no capacity result; preserve the run and stop. Final01 refused before active start. |
| Timeout | Route, firewall, or listener state needs separate diagnosis; never automatically classify as capacity failure. |
| `INVALID_PROTOCOL_SESSION` / HELLO mismatch | TCP establishment succeeded but protocol metadata/session failed; no capacity result. Inspect frozen session ordering. |
| INVALID before active start | Preserve raw evidence; do not use TIR or throughput as a scientific performance result. |

On a failed attempt, keep the namespace and all Thor/Edge evidence unchanged; do not retry, resume, or overwrite it. A fresh attempt requires a separately prepared namespace and frozen plan. A listener observation is a point-in-time check, so any subsequent connection failure is still recorded as INVALID rather than an Edge-capacity result.
