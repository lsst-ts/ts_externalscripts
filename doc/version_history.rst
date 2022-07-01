.. py:currentmodule:: lsst.ts.externalscripts

.. _lsst.ts.externalscripts.version_history:

===============
Version History
===============


v0.16.1
-------

* In ``LatissAcquireAndTakeSequence.configure``, replace usage of deprecated ``collections.Iterable`` with ``collections.abc.Iterable``.
* In ``LatissCWFSAlign`` fix missing space in error message.


v0.16.0
-------

* First version with documentation.
* Updated latiss_cwfs_align to handle case where the applied offsets to the ATAOS are too small for a correction to be applied.
