"""List every investigation (brain / branch) and how many findings it holds.

So brains never get orphaned (Noor): shows each isolated hive mind by name + size.

    PYTHONPATH=src python tools/list_investigations.py
"""
import sys

sys.path.insert(0, "src")

from seeker.memory.memory_map import MemoryMap   # noqa: E402


def main():
    st = MemoryMap().stats()
    ns = getattr(st, "namespaces", None) or (
        st.get("namespaces") if isinstance(st, dict) else {}) or {}
    rows = []
    for name, summ in ns.items():
        count = int(getattr(summ, "vector_count", None) or
                    (summ.get("vector_count") if isinstance(summ, dict) else 0) or 0)
        rows.append((name or "main", count))
    rows.sort(key=lambda r: -r[1])

    print("=" * 46)
    print("YOUR INVESTIGATIONS (each its own brain)")
    print("=" * 46)
    if not rows:
        print("  (none yet — run an investigation with --investigation <name>)")
    for name, count in rows:
        print(f"  {name:<28} {count:>6} findings")
    print("-" * 46)
    print(f"  {'TOTAL':<28} {sum(c for _, c in rows):>6} findings")


if __name__ == "__main__":
    main()
