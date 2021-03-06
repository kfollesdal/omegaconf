import copy
from dataclasses import dataclass
from enum import Enum
from typing import (
    AbstractSet,
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    MutableMapping,
    Optional,
    Tuple,
    Type,
    Union,
)

from ._utils import (
    _is_interpolation,
    get_structured_config_data,
    get_type_of,
    is_primitive_dict,
    is_structured_config,
    is_structured_config_frozen,
)
from .base import Container, ContainerMetadata, Node
from .basecontainer import BaseContainer
from .errors import (
    KeyValidationError,
    MissingMandatoryValue,
    ReadonlyConfigError,
    UnsupportedInterpolationType,
    UnsupportedValueType,
    ValidationError,
)
from .nodes import EnumNode, ValueNode


@dataclass
class DictConfigMetadata(ContainerMetadata):
    object_type: Optional[Type[Any]] = None
    annotated_type: Optional[Type[Any]] = None
    key_type: Any = Any


class DictConfig(BaseContainer, MutableMapping[str, Any]):

    _metadata: DictConfigMetadata

    def __init__(
        self,
        content: Union[Dict[str, Any], Any],
        key: Any = None,
        parent: Optional[Container] = None,
        annotated_type: Optional[Type[Any]] = None,
        is_optional: bool = True,
        key_type: Any = Any,
        element_type: Any = Any,
    ) -> None:
        super().__init__(
            parent=parent,
            metadata=DictConfigMetadata(
                key=key,
                optional=is_optional,
                element_type=element_type,
                object_type=None,
                key_type=key_type,
            ),
        )

        if is_structured_config(annotated_type):
            self._metadata.annotated_type = annotated_type
        if is_structured_config(content) or is_structured_config(annotated_type):
            self._set_value(content)
            if is_structured_config_frozen(content) or is_structured_config_frozen(
                annotated_type
            ):
                self._set_flag("readonly", True)

        else:
            self._set_value(content)
            if isinstance(content, DictConfig):
                metadata = copy.deepcopy(content._metadata)
                metadata.key = key
                metadata.optional = is_optional
                metadata.element_type = element_type
                metadata.object_type = None
                metadata.key_type = key_type
                self.__dict__["_metadata"] = metadata

    def __deepcopy__(self, memo: Dict[int, Any] = {}) -> "DictConfig":
        res = DictConfig({})
        for k, v in self.__dict__.items():
            res.__dict__[k] = copy.deepcopy(v, memo=memo)
        res._re_parent()
        return res

    def __copy__(self) -> "DictConfig":
        res = DictConfig(content={}, element_type=self._metadata.element_type)
        for k, v in self.__dict__.items():
            res.__dict__[k] = copy.copy(v)
        res._re_parent()
        return res

    def copy(self) -> "DictConfig":
        return copy.copy(self)

    def _validate_get(self, key: Union[int, str, Enum]) -> None:
        is_typed = self._metadata.object_type is not None
        is_struct = self._get_flag("struct") is True
        if key not in self.__dict__["_content"]:
            if is_typed:
                # do not raise an exception if struct is explicitly set to False
                if self._get_node_flag("struct") is False:
                    return
                # Or if type is a subclass if dict
                assert self._metadata.object_type is not None
                if issubclass(self._metadata.object_type, dict):
                    return
            if is_typed or is_struct:
                if is_typed:
                    assert self._metadata.object_type is not None
                    msg = f"Accessing unknown key in {self._metadata.object_type.__name__} : {self._get_full_key(key)}"
                else:
                    msg = "Accessing unknown key in a struct : {}".format(
                        self._get_full_key(key)
                    )
                raise AttributeError(msg)

    def _validate_set(self, key: Any, value: Any) -> None:
        target = self.get_node(key)

        if value == "???":
            return

        if target is not None:
            if target._get_flag("readonly"):
                raise ReadonlyConfigError(self._get_full_key(key))
        else:
            if self._get_flag("readonly"):
                raise ReadonlyConfigError(self._get_full_key(key))

        if target is None:
            return

        def is_typed(c: Any) -> bool:
            return isinstance(c, DictConfig) and c._metadata.object_type is not None

        def get_type(c: Any) -> Optional[Type[Any]]:
            if is_structured_config(c):
                return get_type_of(c)
            if isinstance(c, DictConfig):
                t = c._metadata.object_type
                assert t is None or isinstance(t, type)
                return t
            else:
                return type(c)

        if not is_typed(target):
            return
        target_type = get_type(target)
        value_type = get_type(value)

        # target must be optional by now. no need to check the type of value if None.
        if value is None:
            return

        if (
            target_type is not None
            and value_type is not None
            and not issubclass(value_type, target_type)
        ):
            raise ValidationError(
                f"Invalid type assigned : {value_type.__name__} "
                f"is not a subclass of {target_type.__name__}. value: {value}"
            )

    def _validate_and_normalize_key(self, key: Any) -> Union[str, Enum]:
        return self._s_validate_and_normalize_key(self._metadata.key_type, key)

    @staticmethod
    def _s_validate_and_normalize_key(key_type: Any, key: Any) -> Union[str, Enum]:
        if key_type is Any:
            for t in (str, Enum):
                try:
                    return DictConfig._s_validate_and_normalize_key(key_type=t, key=key)
                except KeyValidationError:
                    pass
            raise KeyValidationError(
                f"Key {key} (type {type(key).__name__}) is incompatible with {key_type}"
            )

        if key_type == str:
            if not isinstance(key, str):
                raise KeyValidationError(
                    f"Key {key} is incompatible with {key_type.__name__}"
                )
            return key

        try:
            ret = EnumNode.validate_and_convert_to_enum(key_type, key)
            assert ret is not None
            return ret
        except ValidationError as e:
            raise KeyValidationError(
                f"Key {key} is incompatible with {key_type.__name__} : {e}"
            )

    def __setitem__(self, key: Union[str, Enum], value: Any) -> None:
        try:
            self.__set_impl(key, value)
        except AttributeError as e:
            raise KeyError(str(e))

    def __set_impl(self, key: Union[str, Enum], value: Any) -> None:
        key = self._validate_and_normalize_key(key)

        try:
            self._set_item_impl(key, value)
        except UnsupportedValueType as ex:
            raise UnsupportedValueType(
                f"'{type(value).__name__}' is not a supported type (key: {self._get_full_key(key)}) : {ex}"
            )

    # hide content while inspecting in debugger
    def __dir__(self) -> Iterable[str]:
        if self._is_missing() or self._is_none():
            return []
        return self.__dict__["_content"].keys()  # type: ignore

    def __setattr__(self, key: str, value: Any) -> None:
        """
        Allow assigning attributes to DictConfig
        :param key:
        :param value:
        :return:
        """
        self.__set_impl(key, value)

    def __getattr__(self, key: str) -> Any:
        """
        Allow accessing dictionary values as attributes
        :param key:
        :return:
        """
        # PyCharm is sometimes inspecting __members__, be sure to tell it we don't have that.
        if key == "__members__":
            raise AttributeError()

        return self.get(key=key, default_value=None)

    def __getitem__(self, key: Union[str, Enum]) -> Any:
        """
        Allow map style access
        :param key:
        :return:
        """
        try:
            return self.get(key=key, default_value=None)
        except AttributeError as e:
            raise KeyError(str(e))

    def get(self, key: Union[str, Enum], default_value: Any = None) -> Any:
        key = self._validate_and_normalize_key(key)
        node = self.get_node_ex(key=key, default_value=default_value)
        return self._resolve_with_default(
            key=key, value=node, default_value=default_value,
        )

    def get_node(self, key: Union[str, Enum]) -> Node:
        return self.get_node_ex(key)

    def get_node_ex(
        self,
        key: Union[str, Enum],
        default_value: Any = None,
        validate_access: bool = True,
    ) -> Node:
        value: Node = self.__dict__["_content"].get(key)
        if validate_access:
            try:
                self._validate_get(key)
            except (KeyError, AttributeError):
                if default_value is not None:
                    value = default_value
                else:
                    raise
        else:
            if default_value is not None:
                value = default_value
        return value

    __marker = object()

    def pop(self, key: Union[str, Enum], default: Any = __marker) -> Any:
        key = self._validate_and_normalize_key(key)
        if self._get_flag("readonly"):
            raise ReadonlyConfigError(self._get_full_key(key))
        value = self._resolve_with_default(
            key=key,
            value=self.__dict__["_content"].pop(key, default),
            default_value=default,
        )
        if value is self.__marker:
            raise KeyError(key)
        return value

    def keys(self) -> Any:
        if self._is_missing() or self._is_interpolation() or self._is_none():
            return list()
        return self.__dict__["_content"].keys()

    def __contains__(self, key: object) -> bool:
        """
        A key is contained in a DictConfig if there is an associated value and
        it is not a mandatory missing value ('???').
        :param key:
        :return:
        """

        key = self._validate_and_normalize_key(key)
        try:
            node: Optional[Node] = self.get_node(key)
        except (KeyError, AttributeError):
            node = None

        if node is None:
            return False
        else:
            try:
                self._resolve_with_default(key, node, None)
                return True
            except UnsupportedInterpolationType:
                # Value that has unsupported interpolation counts as existing.
                return True
            except (MissingMandatoryValue, KeyError):
                return False

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def items(self) -> AbstractSet[Tuple[str, Any]]:
        return self.items_ex(resolve=True, keys=None)

    def items_ex(
        self, resolve: bool = True, keys: Optional[List[str]] = None
    ) -> AbstractSet[Tuple[str, Any]]:
        # Using a dictionary because the keys are ordered
        items: Dict[Tuple[str, Any], None] = {}
        for key in self.keys():
            if resolve:
                value = self.get(key)
            else:
                value = self.__dict__["_content"][key]
                if isinstance(value, ValueNode):
                    value = value._value()
            if keys is None or key in keys:
                items[(key, value)] = None

        return items.keys()

    def __eq__(self, other: Any) -> bool:
        if other is None:
            return self.__dict__["_content"] is None
        if is_primitive_dict(other) or is_structured_config(other):
            return DictConfig._dict_conf_eq(self, DictConfig(other))
        if isinstance(other, DictConfig):
            return DictConfig._dict_conf_eq(self, other)
        return NotImplemented

    def __ne__(self, other: Any) -> bool:
        x = self.__eq__(other)
        if x is not NotImplemented:
            return not x
        return NotImplemented

    def __hash__(self) -> int:
        return hash(str(self))

    def _promote(self, type_or_prototype: Type[Any]) -> None:
        """
        Retypes a node.
        This should only be used in rare circumstances, where you want to dynamically change
        the runtime structured-type of a DictConfig.
        It will change the type and add the additional fields based on the input class or object
        """
        if type_or_prototype is None:
            return
        if not is_structured_config(type_or_prototype):
            raise ValueError("Expected structured config class")

        from omegaconf import OmegaConf

        proto: DictConfig = OmegaConf.structured(type_or_prototype)
        type_ = proto._metadata.object_type
        # remove the type to prevent assignment validation from rejecting the promotion.
        proto._metadata.object_type = None
        self.merge_with(proto)
        # restore the type.
        self._metadata.object_type = type_

    def _set_value(self, value: Any) -> None:
        from omegaconf import OmegaConf

        self._metadata.object_type = self._metadata.annotated_type
        type_ = (
            self._metadata.object_type
            if self._metadata.object_type is not None
            else DictConfig
        )
        if OmegaConf.is_none(value):
            if not self._is_optional():
                assert isinstance(type_, type)
                raise ValidationError(
                    f"Cannot assign {type_.__name__}=None (field is not Optional)"
                )
            self.__dict__["_content"] = None
        elif _is_interpolation(value):
            self.__dict__["_content"] = value
        elif value == "???":  # missing
            self.__dict__["_content"] = "???"
        else:
            is_structured = is_structured_config(value)
            if is_structured:
                _type = get_type_of(value)
                value = get_structured_config_data(value)

            self._metadata.object_type = None
            self.__dict__["_content"] = {}

            for k, v in value.items():
                self.__setitem__(k, v)

            if is_structured:
                self._metadata.object_type = _type

    @staticmethod
    def _dict_conf_eq(d1: "DictConfig", d2: "DictConfig") -> bool:

        d1_none = d1.__dict__["_content"] is None
        d2_none = d2.__dict__["_content"] is None
        if d1_none and d2_none:
            return True
        if d1_none != d2_none:
            return False

        assert isinstance(d1, DictConfig)
        assert isinstance(d2, DictConfig)
        if len(d1) != len(d2):
            return False
        for k, v in d1.items_ex(resolve=False):
            if k not in d2.__dict__["_content"]:
                return False
            if not BaseContainer._item_eq(d1, k, d2, k):
                return False

        return True
