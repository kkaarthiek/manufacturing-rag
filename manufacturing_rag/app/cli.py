"""
CLI (spec Section 8).  STATUS: IMPLEMENTED.

  python -m manufacturing_rag.app.cli eval [--strict]      run the gate board
  python -m manufacturing_rag.app.cli ask "question" [--hosted] [--agentic]
                                                          answer a question end-to-end
"""

from __future__ import annotations

import sys

from ..eval.harness import run as run_eval


def _ask(argv):
    hosted = "--hosted" in argv
    agentic = "--agentic" in argv
    q = " ".join(a for a in argv if not a.startswith("--"))
    if not q:
        print('usage: ask "your question" [--hosted] [--agentic]')
        return 2
    from .system import System
    print(f"[building index | mode={'hosted' if hosted else 'offline'} ...]")
    sysm = System(hosted=hosted)
    a = sysm.answer(q, mode="agentic" if agentic else "deterministic")
    print("\n" + "=" * 70)
    print(f"Q: {q}")
    print(f"STATUS: {a.status}")
    print(f"ANSWER: {a.text}")
    if a.claims:
        cites = sorted({c for cl in a.claims for c in (cl.citations or [])})
        print(f"CITES : {cites}")
        print(f"CLAIM : {[(cl.ctype, cl.value, cl.verified) for cl in a.claims]}")
    if a.missing:
        print(f"MISSING: {a.missing}")
    if a.trace.get("subtasks"):
        print("PLAN  :")
        for s in a.trace["subtasks"]:
            print(f"    {s['step']}  [verified={s.get('verified')}]")
    print("=" * 70)
    return 0


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    cmd = argv[0] if argv else "eval"
    if cmd == "eval":
        return run_eval(strict="--strict" in argv, hosted="--hosted" in argv)
    if cmd == "ask":
        return _ask(argv[1:])
    print(f"unknown command: {cmd}  (try: eval | ask)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
