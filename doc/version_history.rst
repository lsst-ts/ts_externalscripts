.. py:currentmodule:: lsst.ts.externalscripts

.. _lsst.ts.externalscripts.version_history:

===============
Version History
===============

.. towncrier release notes start

v0.27.0 (2023-10-30)
====================

New Features
------------

- Update ``maintel/tma/random_walk.py`` to have timer outside the generator ``get_azel_random_walk``
- Create ``maintel/tma/random_walk_and_take_image_gencam.py`` based on ``BaseTrackTargetAndTakeImage`` and ``RandomWalk`` (`DM-38437 <https://jira.lsstcorp.org/browse/DM-38437>`_)


v0.26.1 (2023-10-06)
====================

New Features
------------

- In ``auxtel/latiss_base_align.py``, add functionality to return hexapod to its initial position in case of failures during the alignment process.. (`DM-37831 <https://jira.lsstcorp.org/browse/DM-37831>`_)
- In ``auxtel/correct_pointing``, reset offsets after slewing to avoid elevation out of range issue.
  In ``auxtel/latiss_base_align.py``, relax default focus threshold. (`DM-40852 <https://jira.lsstcorp.org/browse/DM-40852>`_)


Documentation
-------------

- Integrate towncrier for release notes and change log management (`DM-40534 <https://jira.lsstcorp.org/browse/DM-40534>`_)


Other Changes and Additions
---------------------------

- In `news_creation.yaml` remove the `--dir` parameter from towncrier check action. (`DM-40534 <https://jira.lsstcorp.org/browse/DM-40534>`_)


v0.26.0
=======

* Add new script ``make_love_uptime_tests.py``.
  This script is used to test the uptime of the LOVE system.
* Add new module ``love_manager_client.py``.
  This module is used to create a LOVE Manager client.
* In ``auxtel/correct_pointing.py``, fix bug where ``magnitude_range`` and ``radius`` were not being passed to ``find_target``.

v0.25.7
=======

* In ``auxtel/correct_pointing.py``, update default search parameters to increase chance of finding target in local catalog.
* Remove ``setup.cfg`` file and update flake8 options in ``pyproject.toml``. Update conda recipe.
* In ``auxtel/latiss_base_align.py``, reduce default focus correction threshold.


v0.25.6
=======

* In ``maintel/make_comcam_calibrations.py``, fix typo in pipeline instrument name.

v0.25.5
=======

* In ``auxtel/correct_pointing.py``, fixed bug where ``_center`` could send ``Nan`` offsets to atcs.

v0.25.4
=======

* In ``base_make_calibrations.py``, update to check for instrument ``cp_verify`` config file first.

v0.25.3
=======

* In ``auxtel/latiss_base_align.py``, update sensitiviy matrix and add hexapod_offset_scale from constants. 
* In ``auxtel/correct_pointing.py``, update default search radius to 5.0 deg. 

v0.25.2
=======

* In ``auxtel/latiss_base_align.py`` and ``auxtel/latiss_intra_extra_focal_data.py`` replace calls of look_up_table_offset with new atcs method offset_aos_lut.
* Add new ``.github/workflows/changelog.yaml`` file. 

v0.25.1
=======

* In ``auxtel/latiss_acquire.py``, fix call to ``get_next_image_data_id``.

v0.25.0
=======

* In ``random_walk.py``:
    * The ``random_walk_azel_by_time`` function now returns a dataclass
    * Replace ``.get`` calls with ``.aget`` calls 
    * Fix/improve docstring in RandomWalkData
    * Remove unused variable ```data```
    * Remove/improve log messages in ``random_walk_by_time``
    * Improve random_walk_azel_by_time docstring to explain the name ``origin``

* Add new script ``latiss_acquire.py`` for AuxTel.
  This script is used to slew to a target and center it at a specific position.
  
* In ``auxtel/correct_pointing`` and ``auxtel/latiss_base_align``, add config to search local catalog and set to HD_cwfs_stars by default. 

* In ``auxtel/latiss_wep_align.py``, remove inline method ``get_image`` and import/use new method ``get_image_sync` from ts_observing_utilities.

* Update latiss_wep_align to work with version 5 of ts_wep

* In ``auxtel/latiss_intra_extra_focal_data``, take detection image after applying offset.

* In ``auxtel/latiss_base_align.py``, implement telescope offset correction when applying tip-tilt hexapod offsets.

* Run isort.

* Update Jenkinsfile to use shared library.

* Configure package to use ts_pre_commit to manage pre_commit hooks.

v0.24.0
=======

* Add new Script ``LatissIntraExtraFocalData`` for AuxTel.
  This script is used to take intra and extra focal data with given look up table offsets.
  It uses the ``latiss_base_align.py`` module.

* In ``latiss_base_algin.py``:
    * Expand functionality of offset_hexapod() and rename to look_up_table_hexapod
    * Add slew_to_target function

v0.23.4
=======

* In ``make_base_calibrations.py``:

    * Update number and exposure times for darks.

v0.23.3
=======

* Update pre-commit hook versions.
* Run black 23.1.0.

v0.23.2
=======

* In ``make_love_stress_tests.py``:

    * Add delay to Manager clients creation.
    * Stop changing CSCs states. Now only checks if CSCs are enabled, otherwise raises an exception.

* In ``auxtel/latiss_wep_align.py``, update ``get_donut_catalog`` to include ``blend_centroid_x`` / ``blend_centroid_y`` to the donut catalog.

v0.23.1
=======

* In ``auxtel/latiss_cwfs_align.py``, update log messages with positions of sources found.

* Add new Script ``StressLOVE``.
  This scripts generates LOVE-manager clients in order to stress the system.
  It calculates a mean latency after a certain amount of messages is received.

v0.23.0
=======
* Add new Script ``RandomWalk`` for MainTel.
  This script slew and track objects on sky while performing offsets with pre-defined size in random directions.
  It also has a probability of performing larger offsets.

* Add new Script ``SerpentWalk`` for MainTel.
  This script slew and track targets on sky following an Az/El.
  For the first Az, it goes up in elevation. For the following Az, it goes down in elevation.
  This up/down pattern resembles a serpent walking on sky.
  The script also allows using a cut-off elevation angle.
  The number of targets above the cut-off elevation angle is cut in half.


v0.22.0
=======

* Add new Script ``TrackTargetSched`` for MainTel.
  This script implements a simple visit consisting of slewing to a target and start tracking.


v0.21.0
=======


* Add new Script ``CorrectPointing`` for AuxTel.
  This Script is to be used at the start of the night to correct any zero point offset in the pointing.
* In ``maintel/make_comcam_calibrations.py``, fix ``id`` of the configuration schema.
* In ``auxtel/make_latiss_calibrations``, fix ``id`` of the configuration schema.
* In ``base_make_calibrations.py``:

    * Fix ``id`` of the configuration schema.
    * Catch any exception when processing calibrations, log it and continue.
    * Catch any exception in do_verify, log it and continue.


v0.20.0
=======

* In base_make_calibrations:

  * Set do_gain_from_flat_pair to True by default.
  * Log errors instead of raising.
  * Delete RuntimeErrors related to OCPS and certification.

v0.19.1
=======

* Update unit tests for compatibility with ts_salobj 7.2.

v0.19.0
=======

* In ``python/lsst/ts/externalscripts/auxtel/build_pointing_model.py``:

  * Add new feature that allow users to select different types of grids; healpy (original) or radec (new).

  * Add rotator sequence feature.

  * Allow users to skip a number of points at the beginning of the sequence.

* Run `isort`.

v0.18.1
=======

* In ``python/lsst/ts/externalscripts/auxtel/latiss_base_align.py``:

  * Fix bug in configure method.
  * Fix small bug so the hexapod goes back to the proper position after the intra/extra movement.

* Update ``test_latiss_cwfs_align.py`` to test configuration.
* Modernize Jenkinsfile for CI job.

v0.18.0
=======

* Add new script `python/lsst/ts/externalscripts/maintel/warmup_hexapod.py`.
  This new script is used to move one of the two hexapods to its maximum position in incremental steps.

v0.17.3
=======

* In `python/lsst/ts/externalscripts/auxtel/make_latiss_calibrations.py`, add option to change the grating.

* In `python/lsst/ts/externalscripts/auxtel/make_latiss_calibrations.py`, `python/lsst/ts/externalscripts/maintel/make_comcam_calibrations.py`, and
  `python/lsst/ts/externalscripts/base_make_calibrations.py`, replace ``master calibrations`` for ``combined calibrations``.

v0.17.2
=======

* In `python/lsst/ts/externalscripts/auxtel/latiss_acquire_and_take_sequence.py`, add feasibility check before executing script.
  This will check that all TCS and LATISS controlled CSCs are enabled and that the required ATAOS corrections are enabled.

* In `python/lsst/ts/externalscripts/auxtel/latiss_base_align.py``:

  * Add feasibility check before executing script.
    This will check that all CSCs are enabled and that the required ATAOS corrections are enabled.
  * Move the target configuration step from the ``configure`` step into the ``run`` step, to prevent the script from failing and remaining in "UNCONFIGURED" state.

* In `python/lsst/ts/externalscripts/auxtel/latiss_wep_align.py` replace use of `BestEffortIsr` in type annotation with `typing.All` to support `summit_utils` as a optional package.

v0.17.1
=======

* In ``auxtel/latiss_base_align.py``, add support for loading a playlist.
  This is useful for running integration-type tests.

* In LatissBaseAlign:

  * Fix issue in ``configure`` method accessing ``self.config`` instead of ``config``.
  * Change default rotator strategy from ``SkyAuto`` to ``PhysicalSky``.

v0.17.0
=======

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
=======

* In ``LatissAcquireAndTakeSequence.configure``, replace usage of deprecated ``collections.Iterable`` with ``collections.abc.Iterable``.
* In ``LatissCWFSAlign`` fix missing space in error message.


v0.16.0
=======

* First version with documentation.
* Updated latiss_cwfs_align to handle case where the applied offsets to the ATAOS are too small for a correction to be applied.
