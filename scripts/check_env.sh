#!/usr/bin/env bash

# 이 스크립트는 시스템 상태를 변경하지 않고 재현성에 필요한 환경 정보만 수집한다.
set -uo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
readonly OUTPUT_DIR="${REPO_ROOT}/results/environment"
readonly FILE_TIMESTAMP="$(date '+%Y%m%d_%H%M%S_%N')"
readonly OUTPUT_FILE="${OUTPUT_DIR}/environment_${FILE_TIMESTAMP}.txt"

if ! mkdir -p -- "${OUTPUT_DIR}"; then
    printf '[FATAL] cannot create output directory: %s\n' "${OUTPUT_DIR}" >&2
    exit 1
fi

# 기존 결과를 덮어쓰지 않도록 noclobber로 출력 파일을 배타적으로 생성한다.
if ! (set -o noclobber; : > "${OUTPUT_FILE}") 2>/dev/null; then
    printf '[FATAL] cannot create output file without overwriting: %s\n' "${OUTPUT_FILE}" >&2
    exit 1
fi

exec > >(tee --append -- "${OUTPUT_FILE}") 2>&1

required_failures=0

section() {
    printf '\n===== %s =====\n' "$1"
}

# 필수 명령의 실패를 기록한 뒤에도 나머지 정보를 수집해 진단 자료를 남긴다.
run_required() {
    local label="$1"
    shift
    printf '\n--- %s [required] ---\n' "${label}"
    "$@"
    local status=$?
    if (( status != 0 )); then
        printf '[ERROR] required command failed: %s (exit=%d)\n' "${label}" "${status}"
        required_failures=$((required_failures + 1))
    fi
}

# optional 조회 실패는 원문 오류와 종료 코드를 보존하고 unavailable로 명시한다.
run_optional() {
    local label="$1"
    shift
    printf '\n--- %s [optional] ---\n' "${label}"
    if ! command -v -- "$1" >/dev/null 2>&1; then
        printf '[UNAVAILABLE] command not found: %s\n' "$1"
        return 0
    fi
    "$@"
    local status=$?
    if (( status != 0 )); then
        printf '[UNAVAILABLE] optional command failed: %s (exit=%d)\n' "${label}" "${status}"
    fi
}

section "Timestamp / 시간"
run_required "local timestamp" date '+%Y-%m-%dT%H:%M:%S%z'
run_required "UTC timestamp" date -u '+%Y-%m-%dT%H:%M:%SZ'

section "General / 일반"
run_required "hostname" hostname
run_required "uname -a" uname -a
run_required "kernel version" uname -r
run_required "architecture" uname -m

section "Jetson Platform / Jetson 플랫폼"
printf '\n--- /etc/nv_tegra_release [required] ---\n'
if [[ -r /etc/nv_tegra_release ]]; then
    command cat /etc/nv_tegra_release
    status=$?
    if (( status != 0 )); then
        printf '[ERROR] required file read failed: /etc/nv_tegra_release (exit=%d)\n' "${status}"
        required_failures=$((required_failures + 1))
    fi
else
    printf '[ERROR] required file unavailable: /etc/nv_tegra_release\n'
    required_failures=$((required_failures + 1))
fi
run_optional "JetPack package version" dpkg-query -W -f='${binary:Package}\t${Version}\n' nvidia-jetpack
run_optional "current nvpmodel (query only)" nvpmodel -q
run_optional "jetson_clocks --show (query only)" jetson_clocks --show
printf '\n--- tegrastats path [optional] ---\n'
if command -v tegrastats >/dev/null 2>&1; then
    command -v tegrastats
else
    printf '[UNAVAILABLE] command not found: tegrastats\n'
fi

section "CUDA / TensorRT / GPU"
printf '\n--- CUDA information [optional] ---\n'
if [[ -r /usr/local/cuda/version.json ]]; then
    command cat /usr/local/cuda/version.json
elif [[ -r /usr/local/cuda/version.txt ]]; then
    command cat /usr/local/cuda/version.txt
else
    printf '[UNAVAILABLE] /usr/local/cuda/version.json and version.txt are not readable\n'
fi
printf '\n--- nvcc path and version [optional] ---\n'
if command -v nvcc >/dev/null 2>&1; then
    command -v nvcc
    run_optional "nvcc version" nvcc --version
else
    printf '[UNAVAILABLE] command not found: nvcc\n'
fi
run_optional "TensorRT installed packages" dpkg-query -W -f='${binary:Package}\t${Version}\n' 'libnvinfer*' 'tensorrt*'
run_optional "TensorRT Python runtime" python3 -c 'import tensorrt; print(tensorrt.__version__)'
printf '\n--- trtexec path [optional] ---\n'
if command -v trtexec >/dev/null 2>&1; then
    command -v trtexec
    printf '\n--- trtexec version banner [optional] ---\n'
    # 이 배포판은 --version을 독립 옵션으로 처리하지 않으므로 --help의 원문 banner만 사용한다.
    trtexec --help 2>&1 | sed -n '1p'
    trtexec_status=${PIPESTATUS[0]}
    if (( trtexec_status != 0 )); then
        printf '[UNAVAILABLE] trtexec help query failed (exit=%d)\n' "${trtexec_status}"
    fi
else
    printf '[UNAVAILABLE] command not found: trtexec\n'
fi
run_optional "nvidia-smi" nvidia-smi

section "Software / 소프트웨어"
run_required "Python version" python3 --version
printf '\n--- Python executable path [required] ---\n'
if ! command -v python3; then
    printf '[ERROR] required command not found: python3\n'
    required_failures=$((required_failures + 1))
fi
run_required "Git version" git --version
printf '\n--- Git executable path [required] ---\n'
if ! command -v git; then
    printf '[ERROR] required command not found: git\n'
    required_failures=$((required_failures + 1))
fi

section "System Resources / 시스템 자원"
run_required "RAM information" free -h
run_required "disk usage" df -h

section "Collection Status / 수집 상태"
printf 'output_file=%s\n' "${OUTPUT_FILE}"
if (( required_failures > 0 )); then
    printf '[FAILED] required_failures=%d\n' "${required_failures}"
    exit 1
fi
printf '[OK] required_failures=0\n'
