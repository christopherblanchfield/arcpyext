# coding=utf-8

# Python 2/3 compatibility
# pylint: disable=wildcard-import,unused-wildcard-import,wrong-import-order,wrong-import-position
from __future__ import (absolute_import, division, print_function, unicode_literals)
from future.builtins.disabled import *
from future.builtins import *
from future.standard_library import install_aliases
install_aliases()
# pylint: enable=wildcard-import,unused-wildcard-import,wrong-import-order,wrong-import-position

from .arc_py_ext_error import ArcPyExtError

class ChangeDataSourcesError(ArcPyExtError):
    """description of class"""

    def __init__(self, message, errors = None):
        super(ChangeDataSourcesError, self).__init__(message)
        self._errors = errors

    @property
    def errors(self):
        return self._errors