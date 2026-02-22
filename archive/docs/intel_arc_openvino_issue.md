# Intel Arc GPU (Pro B60) & OpenVINO / OpenCL Compatibility Issues on Linux

**Context**: Attempting to run the Hugging Face `OpenVINO/whisper-large-v3-fp16-ov` transcription model via `optimum-intel` on an Intel Arc Pro B60 GPU using Ubuntu 24.04.

## System Environment (Collected 2026-02-21)

| Component | Details |
|---|---|
| GPU | Intel Arc Pro B60 (BMG-G21, device ID `e211`, stepping B0) |
| Virtualization | QEMU/KVM (Q35+ICH9), GPU passed through via Proxmox VE |
| Host Kernel | `6.19.2-061902-generic` |
| Kernel GPU Driver | `xe` (bound to `0000:01:00.0`) |
| GuC Firmware | `xe/bmg_guc_70.bin` v70.44.1 (loaded); **v70.49.4 recommended** but not present |
| HuC Firmware | `xe/bmg_huc.bin` v8.2.10 |
| DMC Firmware | `i915/bmg_dmc.bin` v2.6 |
| `linux-firmware` pkg | `20240318.git3b128b60-0ubuntu2.23` (outdated — missing recommended GuC firmware) |
| `intel-opencl-icd` | `24.39.31294.20-1032~24.04` (stable, downgraded from `26.01`) |
| `libigc1` | `1.0.17791.16-1032~24.04` |
| `libigdfcl1` | `1.0.17791.16-1032~24.04` |
| `intel-level-zero-gpu` | `1.3.29735.27-914~24.04` |
| `libze1` | `1.26.2-1~24.04~ppa1` |
| `openvino` | `2025.4.1` |
| DRI nodes | `/dev/dri/card1`, `/dev/dri/renderD128` |

## 1. The Core Dump Issue (`Abort was called at 15 line`)

When initially running `optimum-intel` with OpenVINO on the Intel Arc GPU, the Python process instantly crashed with a core dump:
```
Abort was called at 15 line in file: ./shared/source/gmm_helper/resource_info.cpp
Aborted (core dumped)
```

**Root Cause**: This is a known incompatibility tracked in `intel/compute-runtime#861`. The system had updated its OpenCL components (`intel-opencl-icd`) via a third-party PPA (`ppa:kobuk-team/intel-graphics`) to version `26.01`. This bleeding-edge version bundled an incompatible graphics memory management library (`libigc2` instead of `libigc1`). Because of this library mismatch, *any* process attempting to initialize the OpenCL runtime on the GPU (including the simple diagnostic command `clinfo`) hit an assertion failure in the memory allocator (`resource_info.cpp`) and aborted.

## 2. The Deadlock Issue

To fix the core dump, we downgraded the GPU compute runtime back to the official stable Intel repositories via APT:
```bash
sudo apt-get install --allow-downgrades -y intel-opencl-icd=24.39... libigc1=1.0... libigdfcl1=1.0... intel-level-zero-gpu=1.3...
```

This successfully fixed `clinfo` (it no longer aborted). However, when we attempted to initialize the OpenVINO backend (`OVModelForSpeechSeq2Seq`) using these restored, stable `24.39` drivers, the Python process entered a permanent **deadlock**. 
- The process sat indefinitely at 0% CPU utilization.
- It never crashed, but it never loaded the model weights onto the GPU memory.
- It could not be interrupted cleanly without sending a SIGKILL.

**Root Cause**: While the memory allocation assertion (`resource_info.cpp`) was avoided by using the stable driver, the underlying state of the Linux kernel driver (`i915` / `xe`) combined with the specific execution context of the Intel Arc GPU on this machine (which is being virtualized/passed-through on Proxmox VE) seemingly causes the OpenCL/Level-Zero backend to hang when establishing compute queues for OpenVINO.

## 3. Conclusion & Fallback

The combination of Ubuntu 24.04, third-party graphics PPAs, and Intel Arc Pro B60 passthrough creates an environment where the OpenCL/Level-Zero compute stack is currently broken for OpenVINO. It fluctuates between explicit aborts (PPA updates) and silent deadlocks (stable drivers).

As a result, GPU acceleration via OpenVINO is currently a dead end on this specific machine state.

**Workaround**: The `smart-subtitle` pipeline has been successfully reverted to use `faster-whisper` (CTranslate2) on the host CPU. While inference is significantly slower lacking GPU acceleration, it avoids the proprietary OpenCL compute stack entirely and functions stably.

## 4. Additional Diagnostics (Collected 2026-02-21)

### Critical: GPU Not Visible to OpenCL or OpenVINO

`clinfo` confirms **the Arc B60 GPU is completely absent from the OpenCL platform** — only the CPU iGPU (Ultra 7 265K) is enumerated:

```
CL_DEVICE_TYPE_GPU  →  No devices found in platform
```

OpenVINO confirms the same — only `CPU` is available:
```python
>>> ov.Core().available_devices
['CPU']
```

The GPU render node exists at `/dev/dri/renderD128` and the xe kernel driver initializes successfully (display works), but the Intel compute runtime (`intel-opencl-icd`) cannot reach the discrete GPU through the QEMU passthrough layer. The user is in both `video` and `render` groups, so permissions are not the issue.

**This is a deeper problem than a software version mismatch** — the compute ICD itself does not enumerate the passthrough GPU as a valid compute device at all.

### `linux-firmware` Update Not Possible via APT
```
apt-cache policy linux-firmware
  Installed: 20240318.git3b128b60-0ubuntu2.23
  Candidate: 20240318.git3b128b60-0ubuntu2.23   ← same version, no update available
```
Ubuntu Noble's APT repos do not have a newer `linux-firmware` package. Getting GuC 70.49.4 requires either a manual firmware file installation or a PPA.

### GuC Firmware Version Mismatch
The kernel xe driver logs a warning at every boot:
```
GuC firmware (70.49.4) is recommended, but only (70.44.1) was found in xe/bmg_guc_70.bin
Consider updating your linux-firmware pkg
```
The installed `linux-firmware` package (`20240318`) is too old to include the recommended GuC firmware. The `xe` driver accepts the older version but this could contribute to instability in compute workloads. **Potential fix**: update `linux-firmware` to a newer version from the Ubuntu mainline or Intel's firmware repo.

### `libze1` Version Mismatch
The `libze1` package (`1.26.2`) comes from a PPA (`ppa1` suffix) and is **newer** than the `intel-level-zero-gpu` compute runtime (`1.3.29735.27`). These are from different sources and could be mismatched. The Level Zero userspace loader (`libze1`) and the compute runtime backend should ideally be co-versioned.

### Virtualization Context
The GPU is passed through via Proxmox VE (QEMU/KVM, Q35 chipset). The `xe` driver initializes successfully for display (framebuffer visible), but compute queue initialization for OpenCL/Level-Zero may rely on MMIO or interrupt behaviors that differ in a passthrough VM vs. bare metal. This is a known gap area for Arc on QEMU passthrough.

### Fused-Off Compute Engines
Boot logs show `ccs2` and `ccs3` (Copy/Compute Slices) fused off on GT0, and multiple video engines fused off on GT1. This is expected for the Arc Pro B60 SKU but worth noting for any bug report.

## 5. Recommended Next Steps

### To Fix (Try in Order)

1. **Manually install newer GuC firmware** — APT has no update; install directly from upstream:
   ```bash
   # Download bmg_guc_70.bin for v70.49.4 from linux-firmware git
   # https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git
   sudo cp bmg_guc_70.bin /lib/firmware/xe/
   sudo update-initramfs -u
   sudo reboot
   ```

2. **Align `libze1` with compute-runtime source** — `libze1` is from a PPA while the rest is from Intel's official repo; unify the source:
   ```bash
   # Pin or reinstall libze1 from Intel's official intel-graphics PPA (stable tier)
   apt-cache policy libze1
   ```

3. **Test bare-metal (non-QEMU)** — Boot the GPU on bare metal Ubuntu to confirm whether the issue is passthrough-specific or driver-wide. This is the single most useful data point for a bug report.

### For the Bug Report

File against `intel/compute-runtime` (not a kernel issue — xe driver init is fine):

- **Title**: `[Arc Pro B60 / BMG] GPU not enumerated by OpenCL ICD under QEMU/KVM passthrough (xe driver, 24.39 runtime)`
- **Reference**: `intel/compute-runtime#861` (related core dump issue)
- **Key facts to include**:
  - `clinfo` shows OpenCL 3.0 platform present but `CL_DEVICE_TYPE_GPU` returns "No devices found"
  - xe driver initializes display successfully (`/dev/dri/card1`, `renderD128` present)
  - User is in `render` and `video` groups — not a permissions issue
  - `intel-level-zero-gpu` `1.3.29735` + `libze1` `1.26.2` from different sources (possible mismatch)
  - GuC firmware mismatch: loaded 70.44.1, recommended 70.49.4
  - QEMU Q35+ICH9 passthrough on Proxmox VE
- **Attach**: output of `journalctl -k -b | grep "xe 0000:01:00.0"` and full `clinfo` output
