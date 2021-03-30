##################
ts_externalscripts
##################

Non-supported SAL scripts for operating the LSST via the `lsst.ts.scriptqueue.ScriptQueue`.
Each script is a subclass of `lsst.ts.scriptqueue.ScriptBase`.

Supported SAL scripts go in ``ts_standardscripts``.

Put common code and complicated implementations in ``python/lsst/ts/externalscripts``
(or the equivalent location in ``ts_standardscripts``),
and the actual scripts in ``scripts`` in the desired hierarchy.

This code uses ``pre-commit`` to maintain ``black`` formatting and ``flake8`` compliance.
To enable this, run the following commands once (the first removes the previous pre-commit hook)::

    git config --unset-all core.hooksPath
    pre-commit install
