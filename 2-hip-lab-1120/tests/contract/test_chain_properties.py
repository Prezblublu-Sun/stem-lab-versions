"""链的属性测试：任意内容接成的链都核得过；改任何一个字节、删中间任何一条、换任何两条的顺序，都指得出是哪一条；
末尾整条删掉，链自己查不出，备份时记下的链头查得出。属性测试是什么，见 tests/properties.py。"""
from __future__ import annotations

from hypothesis import example, given
from hypothesis import strategies as st

from stemlab.contract import chain
from tests import properties as p


def lines_of(bodies) -> list[bytes]:
    """把一串内容接成链，返回各行（不带行尾的 LF），和链文件切出来的一样。"""
    head, lines = chain.GENESIS, []
    for body in bodies:
        entry = chain.link(body, head)
        head = chain.Head(entry["seq"], entry["this"])
        lines.append(chain.dumps(entry)[:-1])
    return lines


CHAINS = st.lists(p.BODIES, min_size=1, max_size=8).map(lines_of)
LONGER = st.lists(p.BODIES, min_size=2, max_size=8).map(lines_of)


@given(CHAINS)
def test_any_chain_made_by_link_checks_out(lines):
    assert chain.check_chain(lines) is None
    assert chain.head_of(lines).seq == len(lines)
    for number, line in enumerate(lines, start=1):
        assert chain.extends(lines, chain.Head(number, chain.parse(line)["this"])), "链是它自己任何一个链头的延长"


@given(CHAINS, st.data())
def test_changing_any_one_byte_points_at_that_line(lines, data):
    index = data.draw(st.integers(0, len(lines) - 1))
    position = data.draw(st.integers(0, len(lines[index]) - 1))
    value = data.draw(st.integers(0, 255).filter(lambda byte: byte != lines[index][position]))
    changed = list(lines)
    changed[index] = lines[index][:position] + bytes([value]) + lines[index][position + 1:]
    found = chain.check_chain(changed)
    assert found is not None and found.line == index + 1, found


@given(LONGER, st.data())
def test_dropping_a_line_before_the_last_points_at_where_it_was(lines, data):
    index = data.draw(st.integers(0, len(lines) - 2))
    found = chain.check_chain(lines[:index] + lines[index + 1:])
    assert found is not None and found.line == index + 1, found


@given(LONGER, st.data())
def test_swapping_any_two_lines_points_at_the_first_of_them(lines, data):
    first = data.draw(st.integers(0, len(lines) - 2))
    second = data.draw(st.integers(first + 1, len(lines) - 1))
    swapped = list(lines)
    swapped[first], swapped[second] = lines[second], lines[first]
    found = chain.check_chain(swapped)
    assert found is not None and found.line == first + 1, found


@given(CHAINS)
def test_dropping_the_tail_is_caught_only_by_a_recorded_head(lines):
    head = chain.head_of(lines)
    assert chain.check_chain(lines[:-1]) is None, "末尾整条删掉，链自己查不出：这是已知的，靠备份时记下的链头"
    assert not chain.extends(lines[:-1], head)


@given(CHAINS, st.data())
def test_the_line_at_a_recorded_head_must_still_be_there_unchanged(lines, data):
    index = data.draw(st.integers(0, len(lines) - 1))
    head = chain.Head(index + 1, chain.parse(lines[index])["this"])
    garbled = list(lines)
    garbled[index] = data.draw(st.binary(max_size=40).filter(lambda raw: raw != lines[index]))
    assert not chain.extends(garbled, head)


GARBAGE = st.one_of(st.binary(max_size=60), p.BODIES.map(lambda body: chain.dumps(body)[:-1]), CHAINS.map(lambda lines: lines[0]))


@given(st.lists(GARBAGE, max_size=6))
@example([b'{"a":1e999}'])                      # 读得出、却写不回 JSON 的数（无穷大）
@example([b"[1,2]"])
def test_checking_any_bytes_never_crashes_and_points_inside_the_chain(lines):
    found = chain.check_chain(lines)
    assert found is None or 1 <= found.line <= len(lines)


@given(p.BODIES)
def test_the_fixed_bytes_do_not_depend_on_key_order_and_read_back_the_same(body):
    reordered = dict(reversed(list(body.items())))
    assert chain.dumps(body) == chain.dumps(reordered)
    assert chain.parse(chain.dumps(body)[:-1]) == body


@given(CHAINS, st.binary(max_size=30).filter(lambda raw: b"\n" not in raw))
def test_a_half_written_last_line_is_cut_off_and_nothing_else(lines, tail):
    found, cut = chain.split(b"".join(line + b"\n" for line in lines) + tail)
    assert found == lines and cut == len(tail)
