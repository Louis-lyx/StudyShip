from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import CanonicalTheoryBinding, TheoryModule, TheorySection, TheorySource, utcnow


SOURCE_CODE = "OPENDSA-THEORY"
REPOSITORY_URL = "https://github.com/OpenDSA/OpenDSA"
CDN_ROOT = "https://cdn.jsdelivr.net/gh/OpenDSA/OpenDSA@master/RST/en"

# One OpenDSA text module may support several local concepts.  The local textbook
# outline still decides which concepts enter a course.
POINT_MODULES: dict[str, list[str]] = {
    "DS.CONCEPT": ["Background/IntroDSA"],
    "DS.LOGICAL": ["Background/IntroDSA", "Design/ADT"],
    "DS.ADT": ["Design/ADT"],
    "DS.ALGORITHM": ["AlgAnal/AnalIntro"],
    "DS.COMPLEXITY": ["AlgAnal/AnalAsymptotic", "AlgAnal/AnalSpace"],
    "DS.LINEAR.DEF": ["List/ListIntro", "List/ListADT"],
    "DS.SEQLIST": ["List/ListArray"],
    "DS.LINKED": ["List/ListLinked"],
    "DS.DLINKED": ["List/ListDouble"],
    "DS.STACK.DEF": ["List/StackArray"],
    "DS.STACK.IMPL": ["List/StackArray", "List/StackLinked"],
    "DS.QUEUE.DEF": ["List/Queue"],
    "DS.QUEUE.IMPL": ["List/Queue", "List/QueueLinked"],
    "DS.STACK.APP": ["List/StackRecur"],
    "DS.STRING": ["Development/StringSearchKMP"],
    "DS.KMP": ["Development/StringSearchKMP"],
    "DS.ARRAY": ["List/ListArray"],
    "DS.SPARSE": ["SearchStruct/Sparse"],
    "DS.TREE.DEF": ["Binary/BinaryTreeIntro"],
    "DS.BTREE.PROPERTY": ["Binary/BinaryTree", "Binary/BinaryTreeFullThm", "Binary/CompleteTree"],
    "DS.BTREE.TRAVERSE": ["Binary/BinaryTreeTraversal"],
    "DS.BST": ["Binary/BST"],
    "DS.HEAP": ["Binary/Heaps"],
    "DS.HUFFMAN": ["Binary/Huffman"],
    "DS.GRAPH.DEF": ["Graph/GraphIntro"],
    "DS.GRAPH.STORE": ["Graph/GraphImpl"],
    "DS.DFS": ["Graph/GraphTraversal"],
    "DS.BFS": ["Graph/GraphTraversal"],
    "DS.MST": ["Graph/MCST", "Graph/Kruskal"],
    "DS.SHORTEST": ["Graph/GraphShortest", "Graph/Floyd"],
    "DS.TOPO": ["Graph/GraphTopsort"],
    "DS.SEARCH.SEQ": ["Searching/UnsortedSearch", "Searching/SortedSearch"],
    "DS.SEARCH.BINARY": ["Searching/BinarySearch"],
    "DS.BALANCED": ["SearchStruct/BalancedTree", "SearchStruct/AVL"],
    "DS.BTREE": ["Indexing/BTree"],
    "DS.HASH": ["Hashing/HashIntro", "Hashing/HashFunc", "Hashing/OpenHash"],
    "DS.INSERTSORT": ["Sorting/InsertionSort"],
    "DS.BUBBLE": ["Sorting/BubbleSort"],
    "DS.SELECT": ["Sorting/SelectionSort"],
    "DS.SHELL": ["Sorting/Shellsort"],
    "DS.QUICK": ["Sorting/Quicksort"],
    "DS.HEAPSORT": ["Sorting/Heapsort"],
    "DS.MERGE": ["Sorting/Mergesort"],
    "DS.SORT.COMPARE": ["Sorting/SortNotation", "Sorting/SortSumm"],
    "DS.DATA.TERMS": ["Background/IntroDSA"],
    "DS.ADT.REP": ["Design/ADT"],
    "DS.ALG.REQUIREMENTS": ["AlgAnal/AnalIntro"],
    "DS.ALG.EFFICIENCY": ["AlgAnal/AnalPrelim", "AlgAnal/AnalAsymptotic"],
    "DS.LIST.TYPE": ["List/ListADT"],
    "DS.SEQLIST.REP": ["List/ListArray"],
    "DS.LINKED.REP": ["List/ListLinked"],
    "DS.CIRCULAR": ["List/ListDouble"],
    "DS.POLYNOMIAL": ["List/ListElement"],
    "DS.STACK.CONVERT": ["List/StackArray"],
    "DS.STACK.PAREN": ["List/StackArray"],
    "DS.STACK.LINEEDIT": ["List/StackArray"],
    "DS.STACK.MAZE": ["RecurTutor/RecIntro"],
    "DS.STACK.EXPR": ["List/StackArray"],
    "DS.RECURSION.IMPL": ["List/StackRecur", "RecurTutor/RecIntro"],
    "DS.EVENT.SIM": ["List/Queue"],
    "DS.STRING.FIXED": ["Development/StringSearchKMP"],
    "DS.STRING.HEAP": ["Development/StringSearchKMP"],
    "DS.STRING.BLOCK": ["Development/StringSearchKMP"],
    "DS.STRING.NAIVE": ["Development/StringSearchKMP"],
    "DS.STRING.EDITOR": ["Development/StringSearchKMP"],
    "DS.STRING.INDEX": ["Development/StringSearchKMP"],
    "DS.ARRAY.DEF": ["List/ListArray"],
    "DS.ARRAY.SEQ": ["List/ListArray"],
    "DS.MATRIX.SPECIAL": ["SearchStruct/Sparse"],
    "DS.MATRIX.SPARSE": ["SearchStruct/Sparse"],
    "DS.GLIST.DEF": ["Binary/RecursiveDS"],
    "DS.GLIST.STORE": ["Binary/RecursiveDS"],
    "DS.GLIST.RECUR": ["Binary/RecursiveDS", "RecurTutor/RecIntro"],
    "DS.GLIST.POLY": ["Binary/RecursiveDS"],
    "DS.THREADED": ["Binary/BinaryTreeTraversal"],
    "DS.TREE.STORE": ["General/SequentialRep"],
    "DS.FOREST.CONVERT": ["General/GenTreeIntro"],
    "DS.FOREST.TRAVERSE": ["General/GenTreeIntro"],
    "DS.TREE.EQUIV": ["General/UnionFind"],
    "DS.BACKTRACK": ["RecurTutor/RecIntro", "Binary/BinaryTreeTraversal"],
    "DS.TREE.COUNT": ["Binary/BinaryTreeFullThm"],
    "DS.GRAPH.ARRAY": ["Graph/GraphImpl"],
    "DS.GRAPH.ADJLIST": ["Graph/GraphImpl"],
    "DS.GRAPH.ORTHO": ["Graph/GraphImpl"],
    "DS.GRAPH.MULTILIST": ["Graph/GraphImpl"],
    "DS.GRAPH.COMPONENT": ["Graph/GraphTraversal"],
    "DS.GRAPH.SCC": ["Graph/GraphTraversal"],
    "DS.GRAPH.ARTICULATION": ["Graph/GraphTraversal"],
    "DS.CRITICAL": ["Graph/GraphTopsort"],
    "DS.MEM.FREELIST": ["MemManage/MemmanIntro", "MemManage/Dynamic"],
    "DS.MEM.ALLOC": ["MemManage/FirstFit", "MemManage/BestFit", "MemManage/WorstFit"],
    "DS.MEM.BOUNDARY": ["MemManage/SequentialFit"],
    "DS.MEM.BUDDY.ALLOC": ["MemManage/Buddy"],
    "DS.MEM.BUDDY.FREE": ["MemManage/Buddy"],
    "DS.MEM.GC": ["MemManage/Garbage"],
    "DS.MEM.COMPACT": ["MemManage/Garbage"],
    "DS.MEM.PERF": ["MemManage/MMPerformance"],
    "DS.SEARCH.ORDERED": ["Searching/SortedSearch", "Searching/BinarySearch"],
    "DS.SEARCH.STATICTREE": ["SearchStruct/BalancedTree"],
    "DS.SEARCH.INDEXSEQ": ["Indexing/LinearIndexing"],
    "DS.TRIE": ["Binary/TreeTrie"],
    "DS.HASH.FUNC": ["Hashing/HashFunc", "Hashing/HashFuncExamp"],
    "DS.HASH.COLLISION": ["Hashing/OpenHash", "Hashing/BucketHash"],
    "DS.HASH.ANALYSIS": ["Hashing/HashAnal"],
    "DS.SORT.OVERVIEW": ["Sorting/InSort", "Sorting/SortNotation"],
    "DS.TREESELECT": ["Sorting/SelectionSort"],
    "DS.RADIX.MULTI": ["Sorting/RadixSort"],
    "DS.RADIX.LINKED": ["Sorting/RadixSort"],
    "DS.SORT.STABILITY": ["Sorting/SortSumm"],
    "DS.EXT.ACCESS": ["Files/Secondary", "Files/Diskdrive"],
    "DS.EXT.MERGE": ["Files/ExternalSort"],
    "DS.EXT.REPLACE": ["Files/ExternalSort"],
    "DS.EXT.OPTIMAL": ["Files/ExternalSort"],
    "DS.FILE.CONCEPT": ["Files/FileProc"],
    "DS.FILE.SEQUENTIAL": ["Files/FileProc"],
    "DS.FILE.INDEXED": ["Indexing/IndexIntro", "Indexing/LinearIndexing"],
    "DS.FILE.ISAM": ["Indexing/ISAM"],
    "DS.FILE.VSAM": ["Indexing/ISAM"],
    "DS.FILE.HASH": ["Hashing/HashIntro"],
    "DS.FILE.MULTIKEY": ["Indexing/IndexIntro"],
}


def required_modules() -> list[str]:
    return sorted({module for modules in POINT_MODULES.values() for module in modules})


def _inline(text: str) -> str:
    text = re.sub(r":\w+(?::\w+)?:`([^`]+)`", r"\1", text)
    text = re.sub(r"`([^`<]+)\s*<[^>]+>`_", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*|\*([^*]+)\*", lambda m: m.group(1) or m.group(2), text)
    text = text.replace("|---|", "").replace("|--|", "")
    return text.rstrip()


def parse_rst(raw: str, fallback_title: str) -> tuple[str, list[dict], str]:
    """Extract readable theory blocks while skipping AV/exercise-only directives."""
    lines = raw.replace("\r\n", "\n").splitlines()
    sections: list[dict] = []
    title = fallback_title.rsplit("/", 1)[-1]
    current = {"title": title, "level": 1, "lines": []}
    saw_heading = False
    skip_indent: int | None = None
    adornments = "=-~^\"'`:+*#<>_"
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if skip_indent is not None:
            if not stripped or indent > skip_indent:
                i += 1
                continue
            skip_indent = None
        if stripped.startswith(".. "):
            directive = stripped[3:].split("::", 1)[0].strip().lower()
            if directive in {"avembed", "inlineav", "extrtoolembed", "odsalink", "odsascript",
                             "showhidecontent", "topic", "todo", "raw", "image", "figure"}:
                skip_indent = indent
                i += 1
                continue
            # Other directives often contain useful prose or code in their body.
            i += 1
            continue
        if stripped.startswith(":") and ":" in stripped[1:]:
            i += 1
            continue
        if i + 1 < len(lines):
            underline = lines[i + 1].strip()
            if stripped and len(underline) >= max(3, len(stripped) - 2) and len(set(underline)) == 1 \
                    and underline[0] in adornments:
                if any(part.strip() for part in current["lines"]) or saw_heading:
                    sections.append(current)
                level = {"=": 1, "-": 2, "~": 3, "^": 4}.get(underline[0], 3)
                current = {"title": _inline(stripped), "level": level, "lines": []}
                if not saw_heading:
                    title = current["title"]
                saw_heading = True
                i += 2
                continue
        if stripped.startswith(".. _") or stripped.startswith(".. index::"):
            i += 1
            continue
        current["lines"].append(_inline(line))
        i += 1
    if current["lines"] or not sections:
        sections.append(current)
    clean_sections = []
    for section in sections:
        body = "\n".join(section["lines"])
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        if body or section["title"] == title:
            clean_sections.append({"title": section["title"], "level": section["level"], "body": body})
    plain = "\n\n".join(f"{s['title']}\n{s['body']}".strip() for s in clean_sections)
    return title[:300], clean_sections, plain


def import_opendsa_theory(db: Session, source_root: Path) -> dict:
    rst_root = source_root / "RST" / "en"
    source = db.scalar(select(TheorySource).where(TheorySource.code == SOURCE_CODE))
    if not source:
        source = TheorySource(code=SOURCE_CODE, name="OpenDSA 理论正文", version="master",
                              repository_url=REPOSITORY_URL)
        db.add(source); db.flush()
    imported = missing = 0
    module_rows: dict[str, TheoryModule] = {}
    for module_key in required_modules():
        path = rst_root / f"{module_key}.rst"
        if not path.is_file():
            missing += 1
            continue
        raw = path.read_text(encoding="utf-8", errors="replace")
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        row = db.scalar(select(TheoryModule).where(
            TheoryModule.source_id == source.id, TheoryModule.module_key == module_key))
        title, sections, plain = parse_rst(raw, module_key)
        if not row:
            row = TheoryModule(source_id=source.id, module_key=module_key, title=title,
                               source_path=str(path), source_url=f"{CDN_ROOT}/{module_key}.rst")
            db.add(row); db.flush()
        row.title = title
        row.source_path = str(path)
        row.content_hash = digest
        row.raw_rst = raw
        row.plain_text = plain
        row.imported_at = utcnow()
        db.execute(delete(TheorySection).where(TheorySection.module_id == row.id))
        for order, section in enumerate(sections):
            db.add(TheorySection(module_id=row.id, sort_order=order, **section))
        module_rows[module_key] = row
        imported += 1
    db.flush()
    db.execute(delete(CanonicalTheoryBinding).where(
        CanonicalTheoryBinding.module_id.in_([m.id for m in module_rows.values()] or [-1])))
    for point_key, modules in POINT_MODULES.items():
        for order, module_key in enumerate(modules):
            if module_key in module_rows:
                db.add(CanonicalTheoryBinding(canonical_point_key=point_key,
                                              module_id=module_rows[module_key].id,
                                              sort_order=order, is_primary=order == 0))
    source.module_count = imported
    source.imported_at = utcnow()
    source.status = "ready" if not missing else "partial"
    source.message = f"已导入 {imported} 个理论模块；缺少 {missing} 个源文件"
    db.commit()
    return {"source": source.name, "status": source.status, "modules": imported,
            "missing": missing, "message": source.message}


def theory_for_canonical_point(db: Session, canonical_key: str) -> list[dict]:
    rows = db.execute(
        select(CanonicalTheoryBinding, TheoryModule)
        .join(TheoryModule, TheoryModule.id == CanonicalTheoryBinding.module_id)
        .where(CanonicalTheoryBinding.canonical_point_key == canonical_key)
        .order_by(CanonicalTheoryBinding.sort_order)
    ).all()
    result = []
    for binding, module in rows:
        sections = db.scalars(select(TheorySection).where(
            TheorySection.module_id == module.id).order_by(TheorySection.sort_order)).all()
        result.append({"module_key": module.module_key, "title": module.title,
                       "source_url": module.source_url, "is_primary": binding.is_primary,
                       "sections": [{"title": s.title, "level": s.level, "body": s.body}
                                    for s in sections]})
    return result
