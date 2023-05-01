from enum import Enum
from pathlib import Path
from typing import Tuple, Union

from codegen import capitalize_first_symbol, format_code
from codegen import get_code_intent as _
from codegen import join_code, write_code
from codegen.models.builder import (
    LexDB,
    build_data_models,
    build_params_models,
    build_response_models,
)
from lexicon import models
from nsid import NSID

_MODELS_OUTPUT_DIR = Path(__file__).parent.parent.parent.joinpath('xrpc_client', 'models')
_PARAMS_MODELS_FILENAME = 'params.py'
_DATA_MODELS_FILENAME = 'data.py'
_RESPONSE_MODELS_FILENAME = 'responses.py'


_PARAMS_SUFFIX = 'Params'
_INPUT_SUFFIX = 'Data'
_OPTIONS_SUFFIX = 'Options'
_OUTPUT_SUFFIX = 'Response'


class ModelType(Enum):
    PARAMS = 'params'
    DATA = 'data'
    OPTIONS = 'options'
    RESPONSE = 'response'


def get_params_model_name(method_name: str) -> str:
    return f'{capitalize_first_symbol(method_name)}{_PARAMS_SUFFIX}'


def get_data_model_name(method_name: str) -> str:
    return f'{capitalize_first_symbol(method_name)}{_INPUT_SUFFIX}'


def get_options_model_name(method_name: str) -> str:
    return f'{capitalize_first_symbol(method_name)}{_OPTIONS_SUFFIX}'


def get_response_model_name(method_name: str) -> str:
    return f'{capitalize_first_symbol(method_name)}{_OUTPUT_SUFFIX}'


def _get_model_imports(model_type: ModelType) -> str:
    model_imports = {
        model_type.PARAMS: 'ParamsModelBase',
        model_type.DATA: 'DataModelBase',
        model_type.OPTIONS: 'OptionsModelBase',
        model_type.RESPONSE: 'ResponseModelBase',
    }

    lines = [
        # isort formatted
        'from dataclasses import dataclass',
        # TODO(MarshalX): track and import only used hints? isort can't delete unused imports. mb add ruff
        'from typing import Any, List, Optional, Union',
        '',
        f"from xrpc_client.models.base import {model_imports.get(model_type)}",
    ]

    return join_code(lines)


def _get_model_class_def(name: str, model_type: ModelType) -> str:
    lines = ['@dataclass']

    if model_type is ModelType.PARAMS:
        lines.append(f'class {get_params_model_name(name)}(ParamsModelBase):')
    elif model_type is ModelType.DATA:
        lines.append(f'class {get_data_model_name(name)}(DataModelBase):')
    elif model_type is ModelType.OPTIONS:
        lines.append(f'class {get_options_model_name(name)}(OptionsModelBase):')
    elif model_type is ModelType.RESPONSE:
        lines.append(f'class {get_response_model_name(name)}(ResponseModelBase):')

    return join_code(lines)


_LEXICON_TYPE_TO_PRIMITIVE_TYPEHINT = {
    models.LexString: 'str',
    models.LexInteger: 'int',
    models.LexBoolean: 'bool',
}


def _get_optional_typehint(type_hint, *, optional: bool) -> str:
    if optional:
        return f'Optional[{type_hint}] = None'
    else:
        return type_hint


def _get_model_field_typehint(field_name: str, field_type_def, *, optional: bool) -> Tuple[bool, str]:
    field_type = type(field_type_def)

    if field_type == models.LexUnknown:
        # TODO(MarshalX): it's record. think about it
        return True, _get_optional_typehint('Any', optional=optional)

    type_hint = _LEXICON_TYPE_TO_PRIMITIVE_TYPEHINT.get(field_type)
    if type_hint:
        return True, _get_optional_typehint(type_hint, optional=optional)

    if field_type is models.LexArray:
        failed_type_name, items_type_hint = _get_model_field_typehint(field_name, field_type_def.items, optional=False)
        return failed_type_name, _get_optional_typehint(f'List[{items_type_hint}]', optional=optional)

    # TODO(MarshalX): implement not implemented types
    #  models.LexRef
    #  models.LexRefUnion
    #  models.LexBlob. Note: HERE IS SHOULD BE STRANGE TYPE CALLED BlobRef instead of LexBlob...
    print('IMPLEMENT', field_type)

    return field_type.__name__, _get_optional_typehint('Any', optional=optional)


def _get_req_fields_set(lex_obj) -> set:
    required_fields = set()
    if lex_obj.required:
        required_fields = set(lex_obj.required)

    return required_fields


def _get_model(properties: dict, required_fields: set) -> str:
    fields = []
    optional_fields = []

    for field_name, field_type in properties.items():
        is_optional = field_name not in required_fields
        failed_type_name, type_hint = _get_model_field_typehint(field_name, field_type, optional=is_optional)

        comment = ''
        if failed_type_name is not True:
            comment = f'{_(1)}# FIXME {failed_type_name} instead of Any'

        field_def = f'{_(1)}{field_name}: {type_hint}{comment}'
        if is_optional:
            optional_fields.append(field_def)
        else:
            fields.append(field_def)

    # TODO(MarshalX): sort each group of fields by alphabet?

    fields.extend(optional_fields)
    return join_code(fields)


def _get_model_parameters(parameters: models.LexXrpcParameters) -> str:
    return _get_model(parameters.properties, _get_req_fields_set(parameters))


def _get_model_schema(schema: models.LexObject) -> str:
    return _get_model(schema.properties, _get_req_fields_set(schema))


def _get_model_ref(name: str, ref: models.LexRef) -> str:
    # TODO(MarshalX): impl proper type

    # FIXME(MarshalX): there is class name collision with type alias.
    #  we need generate returning type hint with respect this moment
    #  collision occurs here:
    #  - com.atproto.admin.getRepo
    #  - com.atproto.sync.getRepo
    return f'{get_response_model_name(name)}Ref: Any = None    # FIXME LexRef'


def _get_model_raw_data(name: str) -> str:
    return f'{name}: Union[str, bytes]'


def _generate_params_model(nsid: NSID, definition: Union[models.LexXrpcProcedure, models.LexXrpcQuery]) -> str:
    lines = [_get_model_class_def(nsid.name, ModelType.PARAMS)]

    if definition.parameters:
        lines.append(_get_model_parameters(definition.parameters))

    return join_code(lines)


def _generate_xrpc_body_model(nsid: NSID, body: models.LexXrpcBody, model_type: ModelType) -> str:
    lines = []
    if body.schema:
        if isinstance(body.schema, models.LexObject):
            lines.append(_get_model_class_def(nsid.name, model_type))
            lines.append(_get_model_schema(body.schema))
        elif isinstance(body.schema, models.LexRef):
            lines.append(_get_model_ref(nsid.name, body.schema))
    else:
        if model_type is ModelType.DATA:
            model_name = get_data_model_name(nsid.name)
        elif model_type is ModelType.RESPONSE:
            model_name = get_response_model_name(nsid.name)
        else:
            raise ValueError('Wrong type or not implemented')

        lines.append(_get_model_raw_data(model_name))

    return join_code(lines)


def _generate_data_model(nsid: NSID, input_body: models.LexXrpcBody) -> str:
    return _generate_xrpc_body_model(nsid, input_body, ModelType.DATA)


def _generate_response_model(nsid: NSID, output_body: models.LexXrpcBody) -> str:
    return _generate_xrpc_body_model(nsid, output_body, ModelType.RESPONSE)


def _generate_params_models(lex_db: LexDB) -> None:
    lines = [_get_model_imports(ModelType.PARAMS)]

    for nsid, defs in lex_db.items():
        definition = defs['main']
        if definition.parameters:
            lines.append(_generate_params_model(nsid, definition))

    write_code(_MODELS_OUTPUT_DIR.joinpath(_PARAMS_MODELS_FILENAME), join_code(lines))
    format_code(_MODELS_OUTPUT_DIR.joinpath(_PARAMS_MODELS_FILENAME))


def _generate_data_models(lex_db: LexDB) -> None:
    lines = [_get_model_imports(ModelType.DATA)]

    for nsid, defs in lex_db.items():
        definition = defs['main']
        if definition.input:
            lines.append(_generate_data_model(nsid, definition.input))

    write_code(_MODELS_OUTPUT_DIR.joinpath(_DATA_MODELS_FILENAME), join_code(lines))
    format_code(_MODELS_OUTPUT_DIR.joinpath(_DATA_MODELS_FILENAME))


def _generate_response_models(lex_db: LexDB) -> None:
    lines = [_get_model_imports(ModelType.RESPONSE)]

    for nsid, defs in lex_db.items():
        definition = defs['main']
        if definition.output:
            lines.append(_generate_response_model(nsid, definition.output))

    write_code(_MODELS_OUTPUT_DIR.joinpath(_RESPONSE_MODELS_FILENAME), join_code(lines))
    format_code(_MODELS_OUTPUT_DIR.joinpath(_RESPONSE_MODELS_FILENAME))


def generate_models():
    _generate_params_models(build_params_models())
    _generate_data_models(build_data_models())
    _generate_response_models(build_response_models())


if __name__ == '__main__':
    generate_models()
