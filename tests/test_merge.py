from typing import Any, Tuple

import pytest

from omegaconf import MISSING, DictConfig, OmegaConf, ValidationError, _utils, nodes
from omegaconf.errors import ReadonlyConfigError

from . import ConcretePlugin, ConfWithMissingDict, Group, Plugin, User, Users


@pytest.mark.parametrize(  # type: ignore
    "inputs, expected",
    [
        # # dictionaries
        ([{}, {"a": 1}], {"a": 1}),
        ([{"a": None}, {"b": None}], {"a": None, "b": None}),
        ([{"a": 1}, {"b": 2}], {"a": 1, "b": 2}),
        ([{"a": {"a1": 1, "a2": 2}}, {"a": {"a1": 2}}], {"a": {"a1": 2, "a2": 2}}),
        ([{"a": 1, "b": 2}, {"b": 3}], {"a": 1, "b": 3}),
        (({"a": 1, "b": 2}, {"b": {"c": 3}}), {"a": 1, "b": {"c": 3}}),
        (({"b": {"c": 1}}, {"b": 1}), {"b": 1}),
        (({"list": [1, 2, 3]}, {"list": [4, 5, 6]}), {"list": [4, 5, 6]}),
        (({"a": 1}, {"a": nodes.IntegerNode(10)}), {"a": 10}),
        (({"a": 1}, {"a": nodes.IntegerNode(10)}), {"a": nodes.IntegerNode(10)}),
        (({"a": nodes.IntegerNode(10)}, {"a": 1}), {"a": 1}),
        (({"a": nodes.IntegerNode(10)}, {"a": 1}), {"a": nodes.IntegerNode(1)}),
        # lists
        (([1, 2, 3], [4, 5, 6]), [4, 5, 6]),
        (([[1, 2, 3]], [[4, 5, 6]]), [[4, 5, 6]]),
        (([1, 2, {"a": 10}], [4, 5, {"b": 20}]), [4, 5, {"b": 20}]),
        # Interpolations
        (
            ({"data": 123, "reference": "${data}"}, {"data": 456}),
            {"data": 456, "reference": 456},
        ),
        (({"missing": "${data}"}, {"missing": 123}), {"missing": 123}),
        (
            ({"missing": 123}, {"missing": "${data}"}, {"missing": 456}),
            {"missing": 456},
        ),
        # Structured configs
        (({"user": User}, {}), {"user": User(name=MISSING, age=MISSING)}),
        (({"user": User}, {"user": {}}), {"user": User(name=MISSING, age=MISSING)}),
        (
            ({"user": User}, {"user": {"name": "Joe"}}),
            {"user": User(name="Joe", age=MISSING)},
        ),
        (
            ({"user": User}, {"user": {"name": "Joe", "age": 10}}),
            {"user": User(name="Joe", age=10)},
        ),
        ([{"users": Users}], {"users": {"name2user": {}}}),
        ([Users], {"name2user": {}}),
        ([Users, {"name2user": {}}], {"name2user": {}}),
        (
            [Users, {"name2user": {"joe": User}}],
            {"name2user": {"joe": {"name": MISSING, "age": MISSING}}},
        ),
        (
            [Users, {"name2user": {"joe": User(name="joe")}}],
            {"name2user": {"joe": {"name": "joe", "age": MISSING}}},
        ),
        (
            [Users, {"name2user": {"joe": {"name": "joe"}}}],
            {"name2user": {"joe": {"name": "joe", "age": MISSING}}},
        ),
        ([ConfWithMissingDict, {"dict": {"foo": "bar"}}], {"dict": {"foo": "bar"}}),
        ([{}, ConfWithMissingDict], {"dict": "???"}),
        ([{"user": User}, {"user": Group}], pytest.raises(ValidationError)),
        ([Plugin, ConcretePlugin], ConcretePlugin),
    ],
)
def test_merge(inputs: Any, expected: Any) -> None:
    configs = [OmegaConf.create(c) for c in inputs]

    if isinstance(expected, (dict, list)) or _utils.is_structured_config(expected):
        merged = OmegaConf.merge(*configs)
        assert merged == expected
        # test input configs are not changed.
        # Note that converting to container without resolving to avoid resolution errors while comparing
        for i in range(len(inputs)):
            input_i = OmegaConf.create(inputs[i])
            orig = OmegaConf.to_container(input_i, resolve=False)
            merged2 = OmegaConf.to_container(configs[i], resolve=False)
            assert orig == merged2
    else:
        with expected:
            OmegaConf.merge(*configs)


def test_primitive_dicts() -> None:
    c1 = {"a": 10}
    c2 = {"b": 20}
    merged = OmegaConf.merge(c1, c2)
    assert merged == {"a": 10, "b": 20}


@pytest.mark.parametrize(  # type: ignore
    "a_, b_, expected", [((1, 2, 3), (4, 5, 6), [4, 5, 6])]
)
def test_merge_no_eq_verify(
    a_: Tuple[int], b_: Tuple[int], expected: Tuple[int]
) -> None:
    a = OmegaConf.create(a_)
    b = OmegaConf.create(b_)
    c = OmegaConf.merge(a, b)
    # verify merge result is expected
    assert expected == c


def test_merge_with_1() -> None:
    a = OmegaConf.create()
    b = OmegaConf.create(dict(a=1, b=2))
    a.merge_with(b)
    assert a == b


def test_merge_with_2() -> None:
    a = OmegaConf.create()
    assert isinstance(a, DictConfig)
    a.inner = {}
    b = OmegaConf.create(
        """
    a : 1
    b : 2
    """
    )
    a.inner.merge_with(b)  # type: ignore
    assert a.inner == b


def test_3way_dict_merge() -> None:
    c1 = OmegaConf.create("{a: 1, b: 2}")
    c2 = OmegaConf.create("{b: 3}")
    c3 = OmegaConf.create("{a: 2, c: 3}")
    c4 = OmegaConf.merge(c1, c2, c3)
    assert {"a": 2, "b": 3, "c": 3} == c4


def test_merge_list_list() -> None:
    a = OmegaConf.create([1, 2, 3])
    b = OmegaConf.create([4, 5, 6])
    a.merge_with(b)
    assert a == b


@pytest.mark.parametrize(  # type: ignore
    "base, merge, exception",
    [
        ({}, [], TypeError),
        ([], {}, TypeError),
        ([1, 2, 3], None, ValueError),
        (dict(a=10), None, ValueError),
    ],
)
def test_merge_error(base: Any, merge: Any, exception: Any) -> None:
    base = OmegaConf.create(base)
    merge = None if merge is None else OmegaConf.create(merge)
    with pytest.raises(exception):
        OmegaConf.merge(base, merge)


def test_into_readonly_dict() -> None:
    cfg = OmegaConf.create({"foo": "bar"})
    OmegaConf.set_readonly(cfg, True)
    with pytest.raises(ReadonlyConfigError):
        OmegaConf.merge(cfg, {"zoo": "foo"})


def test_into_readonly_list() -> None:
    cfg = OmegaConf.create([1, 2, 3])
    OmegaConf.set_readonly(cfg, True)
    with pytest.raises(ReadonlyConfigError):
        OmegaConf.merge(cfg, [4, 5, 6])


def test_parent_maintained() -> None:
    c1 = OmegaConf.create(dict(a=dict(b=10)))
    c2 = OmegaConf.create(dict(aa=dict(bb=100)))
    c3 = OmegaConf.merge(c1, c2)
    assert isinstance(c1, DictConfig)
    assert isinstance(c2, DictConfig)
    assert isinstance(c3, DictConfig)
    assert id(c1.a._get_parent()) == id(c1)
    assert id(c2.aa._get_parent()) == id(c2)
    assert id(c3.a._get_parent()) == id(c3)
