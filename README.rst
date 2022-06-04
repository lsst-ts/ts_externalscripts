##################
ts_externalscripts
##################

Non-supported SAL scripts for operating the LSST via the `lsst.ts.scriptqueue.ScriptQueue`.
Supported SAL scripts go in ``ts_standardscripts``.

`Documentation <https://ts-externalscripts.lsst.io>`_

This code uses ``pre-commit`` to maintain ``black`` formatting and ``flake8`` compliance.
To enable this, run the following commands once (the first removes the previous pre-commit hook)::

    git config --unset-all core.hooksPath
    pre-commit install
