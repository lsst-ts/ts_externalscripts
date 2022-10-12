.. py:currentmodule:: lsst.ts.externalscripts

.. _lsst.ts.externalscripts.version_history:

===============
Version History
===============

v0.19.1
-------

* Update unit tests for compatibility with ts_salobj 7.2.

v0.19.0
-------

* In ``python/lsst/ts/externalscripts/auxtel/build_pointing_model.py``:

  * Add new feature that allow users to select different types of grids; healpy (original) or radec (new).

  * Add rotator sequence feature.

  * Allow users to skip a number of points at the beginning of the sequence.

* Run `isort`.

v0.18.1
-------

* In ``python/lsst/ts/externalscripts/auxtel/latiss_base_align.py``:

  * Fix bug in configure method.
  * Fix small bug so the hexapod goes back to the proper position after the intra/extra movement.

* Update ``test_latiss_cwfs_align.py`` to test configuration.
* Modernize Jenkinsfile for CI job.

v0.18.0
-------

* Add new script `python/lsst/ts/externalscripts/maintel/warmup_hexapod.py`.
  This new script is used to move one of the two hexapods to its maximum position in incremental steps.

v0.17.3
-------

* In `python/lsst/ts/externalscripts/auxtel/make_latiss_calibrations.py`, add option to change the grating.

* In `python/lsst/ts/externalscripts/auxtel/make_latiss_calibrations.py`, `python/lsst/ts/externalscripts/maintel/make_comcam_calibrations.py`, and
  `python/lsst/ts/externalscripts/base_make_calibrations.py`, replace ``master calibrations`` for ``combined calibrations``.

v0.17.2
-------

* In `python/lsst/ts/externalscripts/auxtel/latiss_acquire_and_take_sequence.py`, add feasibility check before executing script.
  This will check that all TCS and LATISS controlled CSCs are enabled and that the required ATAOS corrections are enabled.

* In `python/lsst/ts/externalscripts/auxtel/latiss_base_align.py``:

  * Add feasibility check before executing script.
    This will check that all CSCs are enabled and that the required ATAOS corrections are enabled.
  * Move the target configuration step from the ``configure`` step into the ``run`` step, to prevent the script from failing and remaining in "UNCONFIGURED" state.

* In `python/lsst/ts/externalscripts/auxtel/latiss_wep_align.py` replace use of `BestEffortIsr` in type annotation with `typing.All` to support `summit_utils` as a optional package.

v0.17.1
-------

* In ``auxtel/latiss_base_align.py``, add support for loading a playlist.
  This is useful for running integration-type tests.

* In LatissBaseAlign:

  * Fix issue in ``configure`` method accessing ``self.config`` instead of ``config``.
  * Change default rotator strategy from ``SkyAuto`` to ``PhysicalSky``.

v0.17.0
-------

* Add new metaclass, ``LatissBaseAlign``, which contains the generic actions required to execute a curvature wavefront error measurement, abstracting the computation part.
  The meta script performs the following actions:

    * slew to a selected target,
    * acquire intra/extra focal data by offsetting the hexapod in z,
    * run a meta function that computes the wavefront errors,
    * de-rotate the wavefront errors,
    * apply a sensitivity matrix to compute hexapod and telescope offsets,
    * apply comma and focus correction to the hexapod and pointing offsets.

  Therefore child implementations are only left to implement the function that computes the wavefront errors.

* In ``LatissCWFSAlign``, use new meta script ``LatissBaseAlign``.
  This basically removes all the code that was moved from ``LatissCWFSAlign`` into ``LatissBaseAlign``.

* Add unit tests for new ``LatissWEPAlign`` script.

* Add new ``LatissWEPAlign`` script that implements ``LatissBaseAlign`` script by using the wavefront estimation pipeline task.
  This is the same code we will use for the main telescope and is designed as a DM pipeline task, rather than a standalone python code as CWFS.
  Note that the code is developed to use most of the processing done by the cwfs version using, for instance, ``BestEfforIsr`` to rapidly process the raw frames and  ``QuickFrameMeasurementTask`` to find the donuts.
  The data is then passed along to the pipeline task for processing.
  Also, note that the processing is done in parallel in a separate python process.
  This guarantees that the main processing (driving the Script) is kept free of load.
  The amount of data passed from one process to another is rather small in this case, only the pipeline task result and the quick frame measurements are returned.

* In LatissCWFSAlign unit test:

  * rename run_cwfs -> run_align
  * rename sensitivity_matrix -> matrix_sensitivity
  * rename total_coma_x_offset -> offset_total_coma_x
  * rename total_coma_y_offset -> offset_total_coma_y
  * rename total_focus_offset -> offset_total_focus
  * update access to results for dict to new ``LatissAlignResults`` dataclass
  * remove ``__all__``
  * add missing line on license header.


v0.16.1
-------

* In ``LatissAcquireAndTakeSequence.configure``, replace usage of deprecated ``collections.Iterable`` with ``collections.abc.Iterable``.
* In ``LatissCWFSAlign`` fix missing space in error message.


v0.16.0
-------

* First version with documentation.
* Updated latiss_cwfs_align to handle case where the applied offsets to the ATAOS are too small for a correction to be applied.
