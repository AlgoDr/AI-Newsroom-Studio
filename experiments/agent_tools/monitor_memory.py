#!/usr/bin/env python3
"""
monitor_memory.py -- run this in a SEPARATE terminal tab while the Wan2.1
generation command runs in another. Samples system memory every second
and reports the peak, so you get a real number instead of eyeballing
Activity Monitor's graph.

Usage:
    python monitor_memory.py

Stop with Ctrl+C once generation finishes -- it'll print the peak and
average memory pressure observed during the run.

Requires: pip install psutil
"""
import time
import psutil
import sys

def main():
    print("Monitoring system memory. Start your Wan2.1 generation now.")
    print("Press Ctrl+C when generation finishes.\n")

    samples = []
    swap_samples = []
    start = time.time()

    try:
        while True:
            vm = psutil.virtual_memory()
            swap = psutil.swap_memory()
            used_gb = vm.used / (1024 ** 3)
            avail_gb = vm.available / (1024 ** 3)
            swap_used_gb = swap.used / (1024 ** 3)

            samples.append(used_gb)
            swap_samples.append(swap_used_gb)

            elapsed = time.time() - start
            print(f"\r[{elapsed:6.1f}s] Used: {used_gb:5.2f} GB | "
                  f"Available: {avail_gb:5.2f} GB | "
                  f"Swap: {swap_used_gb:5.2f} GB", end="", flush=True)

            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Peak memory used:    {max(samples):.2f} GB")
        print(f"Average memory used: {sum(samples)/len(samples):.2f} GB")
        print(f"Peak swap used:      {max(swap_samples):.2f} GB")
        if max(swap_samples) > 0.5:
            print("\n⚠️  Significant swap usage detected -- this run likely")
            print("   felt slow/laggy due to disk swapping, not just")
            print("   compute time. A model that swaps heavily isn't a")
            print("   good fit for sustained daily use on this hardware.")
        else:
            print("\n✅ Minimal swap usage -- memory pressure stayed")
            print("   manageable throughout this run.")
        print("=" * 60)


if __name__ == "__main__":
    try:
        import psutil
    except ImportError:
        print("Missing dependency. Run: pip install psutil")
        sys.exit(1)
    main()