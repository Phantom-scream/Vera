"""Test-result parser contracts."""

from vera.parsers.base import TestResultParser
from vera.parsers.junit import JUnitXmlParser

__all__ = ["JUnitXmlParser", "TestResultParser"]
