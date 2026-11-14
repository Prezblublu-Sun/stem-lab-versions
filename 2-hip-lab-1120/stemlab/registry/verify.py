"""核对。只能发现问题；恢复靠备份。只读。

    verify_register()   登记链有没有被改，每条长得对不对
    verify_links()      手动挂接的链
    verify_item(编号)   内容和登记时还一不一致，返回现在算出的哈希
    verify_refs()       把只记位置的全核一遍
    verify_items()      把所有登记的内容全核一遍（慢）
"""
from __future__ import annotations

from stemlab.contract import Refused, chain, entries, hashing, kinds, layout, versions
from stemlab.registry import lookup, reader


def _verify_chain(title: str, path, name: str, check) -> list[str]:
    lines = reader.lines(path)
    found = chain.check_chain(lines)
    if found:
        return [f"{title}第 {found.line} 条：{found.reason}"]
    problems = []
    for number, line in enumerate(lines, start=1):
        try:
            entry = versions.upcast(name, chain.parse(line))
        except versions.CannotUpcast as error:
            problems.append(f"{title}第 {number} 条：{error}")
            continue
        problems += [f"{title}第 {number} 条：{text}" for text in check(entry)]
    return problems


def verify_register() -> list[str]:
    """登记链有没有被改。返回哪里不对，指出是哪一条；空列表就是没问题。"""
    return _verify_chain("登记链", layout.register_file(), "register", kinds.check_item)


def verify_links() -> list[str]:
    """手动挂接的链有没有被改。"""
    return _verify_chain("挂接链", layout.links_file(), "links", entries.check_link)


def verify_item(item_id: str) -> str:
    """核对一样东西的内容和登记时还一不一致。一致就返回算出的哈希；不一致就被拒，说出是哪一样。"""
    item = lookup.get(item_id)
    title = f"{item['id']}（{item['name']} 第 {item['version']} 版）"
    if item["storage"] == kinds.STORE_VALUE:
        computed = hashing.hash_json(item["content"])
    else:
        folder = lookup.content(item_id)
        if not folder.is_dir():
            raise Refused(f"{title} 的内容找不到了：{folder}")
        try:
            computed = hashing.hash_tree(folder)
        except (OSError, ValueError) as error:      # 里面多了链接，或者有读不了的地方
            raise Refused(f"{title} 的内容读不全：{error}") from None
    if computed != item["hash"]:
        raise Refused(f"{title} 的内容和登记时不一致：登记时是 {item['hash'][:12]}…，现在是 {computed[:12]}…")
    return computed


def _verify_many(items: list[dict]) -> list[str]:
    problems = []
    for item in items:
        try:
            verify_item(item["id"])
        except Refused as error:
            problems.append(str(error))
    return problems


def verify_refs() -> list[str]:
    """把只记位置的全核一遍。返回哪几样对不上。"""
    return _verify_many([item for item in reader.items() if item["storage"] == kinds.STORE_REF])


def verify_items() -> list[str]:
    """把所有登记的内容全核一遍。返回哪几样对不上。"""
    return _verify_many(reader.items())
