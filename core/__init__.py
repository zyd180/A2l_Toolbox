#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""核心功能模块包"""

from .elf_parser import parse_elf_symbols
from .map_parser import parse_map_symbols
from .a2l_parser import (
    extract_a2l_variables,
    get_a2l_blocks,
    extract_a2l_content,
    build_function_blocks,
    write_content_only,
    insert_into_header,
    get_calibration_objects,
)
from .sync_engine import sync_model_a2l
from .dcm_handler import parse_dcm, build_a2l_index, dcm_to_hex
from .hex_handler import (
    encode_raw,
    load_intel_hex,
    save_intel_hex,
    read_calibration_value,
    write_calibration_value,
)

__all__ = [
    'parse_elf_symbols',
    'parse_map_symbols',
    'extract_a2l_variables',
    'get_a2l_blocks',
    'extract_a2l_content',
    'build_function_blocks',
    'write_content_only',
    'insert_into_header',
    'get_calibration_objects',
    'sync_model_a2l',
    'parse_dcm',
    'build_a2l_index',
    'dcm_to_hex',
    'encode_raw',
    'load_intel_hex',
    'save_intel_hex',
    'read_calibration_value',
    'write_calibration_value',
]