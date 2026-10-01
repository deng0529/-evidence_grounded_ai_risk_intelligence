"""Offline M7 tests using production M2/M3/M4/M5/M6 fixture pipelines."""

from tests.m2.conftest import api, database, offline, storage  # noqa: F401
from tests.m3.conftest import ixbrl  # noqa: F401
