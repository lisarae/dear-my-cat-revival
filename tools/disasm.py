"""Annotated ARM64 disassembly of Dear My Cat's IL2CPP methods.

Labels calls, string literals and metadata with the names from Il2CppDumper,
so you can see which JSON keys a reply handler reads.

usage:
  python3 tools/disasm.py --so libil2cpp.so --script dump/script.json "Name substring"
  options: --max N (instructions per method), --exact (match the full name)
needs:  python3 -m pip install capstone pyelftools
"""
import argparse, json, sys, bisect, pickle, os
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from elftools.elf.elffile import ELFFile

_ap = argparse.ArgumentParser()
_ap.add_argument("name")
_ap.add_argument("--so", required=True, help="path to libil2cpp.so (arm64)")
_ap.add_argument("--script", required=True, help="path to Il2CppDumper's script.json")
_ap.add_argument("--max", type=int, default=4000)
_ap.add_argument("--exact", action="store_true")
ARGS = _ap.parse_args()
SO = ARGS.so
CACHE = ARGS.script + ".sym.pkl"

if os.path.exists(CACHE):
    meth, data, rel = pickle.load(open(CACHE, "rb"))
else:
    d = json.load(open(ARGS.script))
    meth = {m["Address"]: m["Name"] for m in d["ScriptMethod"]}
    data = {}
    for s in d["ScriptString"]:
        data[s["Address"]] = 'STR "%s"' % s["Value"][:80]
    for s in d["ScriptMetadata"]:
        data[s["Address"]] = "META " + s["Name"]
    for s in d["ScriptMetadataMethod"]:
        data[s["Address"]] = "MMETH " + s["Name"]
    # relative relocations: slot -> target (for vtable / pointer loads)
    rel = {}
    with open(SO, "rb") as f:
        elf = ELFFile(f)
        for sec in elf.iter_sections():
            if sec.name in (".rela.dyn",):
                for r in sec.iter_relocations():
                    if r["r_info_type"] == 1027:
                        rel[r["r_offset"]] = r["r_addend"]
    pickle.dump((meth, data, rel), open(CACHE, "wb"))

addrs = sorted(meth)
raw = open(SO, "rb").read()

def file_off(va):
    # libil2cpp text: VA==offset for first segment; data segment differs
    with open(SO, "rb") as f:
        elf = ELFFile(f)
        for seg in elf.iter_segments():
            if seg["p_type"] == "PT_LOAD" and seg["p_vaddr"] <= va < seg["p_vaddr"] + seg["p_filesz"]:
                return va - seg["p_vaddr"] + seg["p_offset"]
    return None

def method_range(a):
    i = bisect.bisect_right(addrs, a)
    end = addrs[i] if i < len(addrs) else a + 0x400
    return a, min(end, a + 0x4000)

def label(t):
    if t in meth:
        return meth[t]
    if t in data:
        return data[t]
    return None

def dis(name_sub, maxn=4000, exact=False):
    hits = [(a, n) for a, n in meth.items() if (n == name_sub if exact else name_sub in n)]
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    for a, n in sorted(hits)[:6]:
        s, e = method_range(a)
        off = file_off(s)
        print("=" * 80)
        print(hex(s), n)
        regs = {}
        cnt = 0
        for ins in md.disasm(raw[off:off + (e - s)], s):
            cnt += 1
            if cnt > maxn:
                break
            note = ""
            ops = ins.op_str
            if ins.mnemonic == "adrp":
                r, imm = ops.split(", #")
                regs[r] = int(imm, 16)
            elif ins.mnemonic in ("ldr", "add") and "#" in ops:
                parts = [p.strip() for p in ops.replace("[", "").replace("]", "").split(",")]
                src = parts[1]
                if src in regs:
                    try:
                        imm = int(parts[2].lstrip("#"), 16) if parts[2].startswith("#0x") else int(parts[2].lstrip("#"))
                    except Exception:
                        imm = None
                    if imm is not None:
                        t = regs[src] + imm
                        l = label(t)
                        if l is None and t in rel:
                            l = label(rel[t]) or ("-> " + hex(rel[t]))
                        if l:
                            note = "  ; " + l
            elif ins.mnemonic in ("bl", "b"):
                try:
                    t = int(ops.lstrip("#"), 16)
                    l = label(t)
                    if l:
                        note = "  ; " + l
                except ValueError:
                    pass
            print("  %x: %-7s %-40s%s" % (ins.address, ins.mnemonic, ops, note))

if __name__ == "__main__":
    dis(ARGS.name, ARGS.max, ARGS.exact)
