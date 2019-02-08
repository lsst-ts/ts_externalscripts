"""Sphinx configuration file for an LSST stack package.

This configuration only affects single-package Sphinx documentation builds.
"""

from documenteer.sphinxconfig.stackconf import build_package_configs
import lsst.ts.salscripts

_g = globals()
_g.update(build_package_configs(
    project_name='ts_salscripts',
    version=lsst.ts.salscripts.version.__version__))
