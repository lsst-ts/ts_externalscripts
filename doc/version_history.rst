.. py:currentmodule:: lsst.ts.externalscripts

.. _lsst.ts.externalscripts.version_history:

===============
Version History
===============

.. towncrier release notes start

v0.30.0 (2025-03-18)
====================

New Features
------------

- Update the implementation of the ignore feature in all scripts to use the ``RemoteGroup.disable_checks_for_components`` method.

  Updated scripts:
  - ``base_parameter_march.py``
  - ``base_take_ptc_flats.py``
  - ``maintel/tma/random_walk.py``
  - ``maintel/tma/random_walk_and_take_image_gencam.py``
  - ``maintel/tma/serpent_walk.py``
  - ``base_take_twilight_flats.py`` (`DM-47619 <https://rubinobs.atlassian.net/browse/DM-47619>`_)
- Add a `short_long_slews.py` script.
  This script moves the Simonyi Telescope with short and long slews around each grid position provided by the user. (`DM-47627 <https://rubinobs.atlassian.net/browse/DM-47627>`_)
- Move make_love_stress_tests received messages log from debug to info level. (`DM-47890 <https://rubinobs.atlassian.net/browse/DM-47890>`_)
- Update BaseMakeCalibrations.callpipetask to remove a call to ack.print_vars. (`DM-47890 <https://rubinobs.atlassian.net/browse/DM-47890>`_)


Bug Fixes
---------

- Remove outdated config overrides in BaseMakeCalibrations. (`DM-45831 <https://rubinobs.atlassian.net/browse/DM-45831>`_)
- BaseMakeCalibrations.call_pipetask would fail to find pipeline if a subset was supplied. (`DM-48380 <https://rubinobs.atlassian.net/browse/DM-48380>`_)
- BaseMakeCalibrations.call_pipetask did not have the updated location for default pipelines. (`DM-48380 <https://rubinobs.atlassian.net/browse/DM-48380>`_)
- BaseMakeCalibrations.call_pipetask and BaseMakeCalibrations.verify_calib use a string representation of a tuple for the exposure_ids.  This adds a trailing comma if the tuple has only one element, causing a syntax error. (`DM-48380 <https://rubinobs.atlassian.net/browse/DM-48380>`_)


Performance Enhancement
-----------------------

- Improve compatibility with kafka. (`DM-47627 <https://rubinobs.atlassian.net/browse/DM-47627>`_)
- Improve the warmup_hexapod.py to recover from the failure and change the step size in the runtime. (`DM-48447 <https://rubinobs.atlassian.net/browse/DM-48447>`_)
- Improve the warmup_hexapod.py to mute/unmute the alarm. (`DM-48531 <https://rubinobs.atlassian.net/browse/DM-48531>`_)
- Improve the warmup_hexapod.py to add a verification stage. (`DM-48608 <https://rubinobs.atlassian.net/browse/DM-48608>`_)


Other Changes and Additions
---------------------------

- - Following the split of the `ts_standardscripts` repository into `maintel` and `auxtel`:

    - Import statements were revised to use `from lsst.ts.maintel.standardscripts` instead of `from lsst.ts.standardscripts.maintel`.
    - Jenkinsfile content was updated to include the new paths for `maintel` and `auxtel` standard scripts.

  - A few scripts have been refactored to comply with the latest `flake8 <https://flake8.pycqa.org/en/latest/>`_ hook guidelines. (`DM-47627 <https://rubinobs.atlassian.net/browse/DM-47627>`_)
- Fixed unit tests for LatissIntraExtraFocalData to work with new take_image command procedure. (`DM-47667 <https://rubinobs.atlassian.net/browse/DM-47667>`_)


v0.29.0 (2024-12-05)
====================

New Features
------------

- Use the new method ``ATCS.assert_ataos_corrections_enabled`` in auxtel scripts (`DM-38823 <https://rubinobs.atlassian.net/browse/DM-38823>`_)
- Add twilight flat script for AuxTel, ComCam, and LSSTCam. (`DM-40956 <https://rubinobs.atlassian.net/browse/DM-40956>`_)
- Introduced `base_parameter_march.py`: Base class for running for taking sensitivity matrices and parameter marches. (`DM-45761 <https://rubinobs.atlassian.net/browse/DM-45761>`_)
- Introduced `parameter_march_comcam.py`: Script for taking parameter march images with Simonyi Telescope using LSSTComCam. (`DM-45761 <https://rubinobs.atlassian.net/browse/DM-45761>`_)
- Introduced `parameter_march_lsstcam.py`: Script for taking parameter march images with Simonyi Telescope using LSSTCam. (`DM-45761 <https://rubinobs.atlassian.net/browse/DM-45761>`_)
- Extend TCS readiness check to other image types beyond OBJECT, such as:
  ENGTEST, CWFS and ACQ.

  Configure TCS synchronization to the following script:

  - auxtel/build_pointing_model.py
  - auxtel/correct_pointing.py
  - auxtel/latiss_acquire.py (`DM-46179 <https://rubinobs.atlassian.net/browse/DM-46179>`_)
- Update BaseMakeCalibrations.callpipetask to remove a call to ack.print_vars. (`DM-46458 <https://rubinobs.atlassian.net/browse/DM-46458>`_)
- In ``maintel/warmup_hexapod.py``, add 5s to the step time delay for metadata estimation. (`DM-46636 <https://rubinobs.atlassian.net/browse/DM-46636>`_)
- Point calibration scripts to Sasquatch-enabled Butler repo for LATISS and LSSTComCam. (`DM-46754 <https://rubinobs.atlassian.net/browse/DM-46754>`_)
- Create take_rotated_comcam.py script.
  The script takes a ComCam aos sequence at different rotation angles. (`DM-46969 <https://rubinobs.atlassian.net/browse/DM-46969>`_)
- Add darks at the end of the twilight flats. (`DM-46978 <https://rubinobs.atlassian.net/browse/DM-46978>`_)
- In base_parameter_march, use offset_rot instead of slewing to a new target every time.. (`DM-46978 <https://rubinobs.atlassian.net/browse/DM-46978>`_)
- Update BaseMakeCalibrations to trigger cp_verify and don't wait for it to finish.

  - Refactor run_block to handle calibration and verification concurrently
    using asyncio
  - Added helper methods (process_images, process_verification,
    process_calibration) to reduce code duplication
  - Manage background tasks with a list, including timeout handling and
    cancellation if not completed in time
  - Add configuration option `background_task_timeout` to control
    background task timeouts
  - Added unit test for BaseMakeCalibrations in
    `tests/test_base_make_calibrations.py` (`DM-4721 <https://rubinobs.atlassian.net/browse/DM-4721>`_)
- In maintel/tma/random_walk_and_take_image_gencam.py, add get_instrument_name method. (`DM-47381 <https://rubinobs.atlassian.net/browse/DM-47381>`_)
- In base_take_twilight_flats.py:
  - Make rotator angle configurable.
  - Allow ignoring mtdome.
  - increase number of darks at end of twilight base_take_twilight_flats.
  - increase consdb polling timeout.
  - add option to give twilight flats a pointing. (`DM-47381 <https://rubinobs.atlassian.net/browse/DM-47381>`_)
- In maintel/take_twilight_flats_comcam.py:
  - Add nounwrap az wrap strategy.
  - Fix table name in ConsDB for sky counts. (`DM-47641 <https://rubinobs.atlassian.net/browse/DM-47641>`_)
- In love_manager_client and moke_love_stress_tests, make sure LoveManagerClient uses a child logging from the script. (`DM-47641 <https://rubinobs.atlassian.net/browse/DM-47641>`_)
- In base_take_twilight_flats.py, change logic for high counts at sunset. (`DM-47641 <https://rubinobs.atlassian.net/browse/DM-47641>`_)


Bug Fixes
---------

- Update BaseMakeCalibrations.take_image_type to correctly handle setting group_id whith the latest version of BaseScript. (`DM-46201 <https://rubinobs.atlassian.net/browse/DM-46201>`_)
- Fixing call to RA in parameter_march_comcam.py. (`DM-46978 <https://rubinobs.atlassian.net/browse/DM-46978>`_)
- In base_parameter_march.py, wait for tracking to start to continue. (`DM-46978 <https://rubinobs.atlassian.net/browse/DM-46978>`_)
- Fixing signs in intra/extra focal images. (`DM-46978 <https://rubinobs.atlassian.net/browse/DM-46978>`_)
- In maintel/parameter_march_comcam, wait for extra visit to be ingested before requesting OCSP processing. (`DM-47381 <https://rubinobs.atlassian.net/browse/DM-47381>`_)


Performance Enhancement
-----------------------

- Fix signs and make rotation optional in parameter_march.py (`DM-47364 <https://rubinobs.atlassian.net/browse/DM-47364>`_)


v0.28.1 (2024-08-27)
====================

New Features
------------

- In `auxtel` add a SAL Script (`wep_checkout.py`) to perform daytime checkout of the wep code. (`DM-41644 <https://rubinobs.atlassian.net/browse/DM-41644>`_)
- Update unit tests for BaseBlockScript to work with the latest version of salobj that adds support for block to BaseScript. (`DM-45637 <https://rubinobs.atlassian.net/browse/DM-45637>`_)


Performance Enhancement
-----------------------

- * Update latiss_wep_align.py to use ts_wep v10 (`DM-41643 <https://rubinobs.atlassian.net/browse/DM-41643>`_)
- In auxtel/latiss_acquire_and_take_sequence.py, increase blind offset lower limit position. (`DM-45467 <https://rubinobs.atlassian.net/browse/DM-45467>`_)
- In take_comcam_guider_image, log roi_spec. (`DM-45467 <https://rubinobs.atlassian.net/browse/DM-45467>`_)


Documentation
-------------

- Fix ``ts_externalscripts`` doc page to correctly show ``ts_externalscripts`` instead of ``ts_standardscripts``. (`DM-41364 <https://rubinobs.atlassian.net/browse/DM-41364>`_)


v0.28.0 (2024-07-30)
====================

New Features
------------

- Add new TakeComCamGuiderImage script, designed to test ComCam guider mode. (`DM-45401 <https://rubinobs.atlassian.net/browse/DM-45401>`_)
- Add new TakePTCFlatsComcam script to take PTC flats with ComCam while scanning electrometer. (`DM-45406 <https://rubinobs.atlassian.net/browse/DM-45406>`_)


Bug Fixes
---------

- In ``take_ptc_flats_comcam`` add ``StateTransition`` usage to Camera instance. (`DM-45232 <https://rubinobs.atlassian.net/browse/DM-45232>`_)
- In ``base_make_calibrations.py``, fix issue with ``take_image_type`` method trying to set ``self.group_id``.

  This is a class property and cannot be changed.
  Instead, use a local variable.Add your info here (`DM-45232 <https://rubinobs.atlassian.net/browse/DM-45232>`_)
- In ``take_ptc_flats_comcam`` add a setup_instrument to change filter.

  This is needed because ComCam is still returning an error when we tell it to select a filter that is already selected. (`DM-45232 <https://rubinobs.atlassian.net/browse/DM-45232>`_)
- In take_ptc_flats_comcam.py, fix issue with take_image_type method trying to set self.group_id. (`DM-45232 <https://rubinobs.atlassian.net/browse/DM-45232>`_)
- In ``take_ptc_flats_comcam`` remove default value from schema. (`DM-45232 <https://rubinobs.atlassian.net/browse/DM-45232>`_)


v0.27.6 (2024-07-15)
====================

New Features
------------

- In base_make_calibrations enable block metadata. (`DM-44231 <https://rubinobs.atlassian.net/browse/DM-44231>`_)
- In auxtel/correct_pointing.py, add feature to limit max number of iterations. (`DM-44231 <https://rubinobs.atlassian.net/browse/DM-44231>`_)
- In ``base_make_calibrations.py``, add metadata keywords (program, reason, note and group_id) to take_image call. (`DM-45220 <https://rubinobs.atlassian.net/browse/DM-45220>`_)


Bug Fixes
---------

- Update auxtel/latiss_wep_align to use camera from lsst obs package instead of getting it from the butler. (`DM-44824 <https://rubinobs.atlassian.net/browse/DM-44824>`_)
- Update pipeline paths, filenames, and subset names to reflect upstream changes in `cp_pipe` and `cp_verify`. (`DM-44873 <https://rubinobs.atlassian.net/browse/DM-44873>`_)


Documentation
-------------

- Update version history notes and towncrier ticket links to use cloud jira project. (`DM-44192 <https://rubinobs.atlassian.net/browse/DM-44192>`_)


v0.27.5 (2024-05-02)
====================

New Features
------------

- In auxtel/correct_pointing.py, add option to pass instrument filter to configuration. (`DM-44131 <https://rubinobs.atlassian.net/browse/DM-44131>`_)


v0.27.4 (2024-02-12)
====================

Performance Enhancement
-----------------------

- In ``/auxtel/latiss_wep_align.py``, change how the source selection is checked when running wep.
  Instead of relying on the intra-focal image as the basis, compute the distance to the boresight and either use the source detected (if it is close enough to the bore sight) or use the source detected for the other image.
  It will also raise an exception if both sources are too far from the boresight.

  In ``auxtel/latiss_base_align.py``, add gains when converting from wavefront error to hexapod correction. (`DM-42690 <https://rubinobs.atlassian.net/browse/DM-42690>`_)


v0.27.3 (2024-02-02)
====================

New Features
------------

- In ``auxtel/latiss_base_align.py`` added `self.next_supplemented_group_id()` call so that intra and extra focal images have the same group id.
  (`DM-41684 <https://rubinobs.atlassian.net/browse/DM-41684>`_) (`DM-41684 <https://rubinobs.atlassian.net/browse/DM-41684>`_)


v0.27.2 (2023-12-14)
====================

New Features
------------

- In ``auxtel/correct_pointing.py``, add config to reset the AOS offsets. (`DM-41870 <https://rubinobs.atlassian.net/browse/DM-41870>`_)


Bug Fixes
---------

- Fixed a bug in `latiss_base_align.py` module when trying to flush the `ataos.evt_detailedState` event before resetting resetting the hexapod to its initial position.
  That flush was not needed, redundant and it was causing an error. (`DM-41718 <https://rubinobs.atlassian.net/browse/DM-41718>`_)
- In ``auxtel/latiss_acquire_and_take_sequence.py``, add floor to y-value of final blind offset position to prevent target landing off of detector. (`DM-41870 <https://rubinobs.atlassian.net/browse/DM-41870>`_)


v0.27.1 (2023-11-29)
====================

Bug Fixes
---------

- * Fix ``make_love_uptime_tests`` to use proper dict keys format (`DM-41266 <https://rubinobs.atlassian.net/browse/DM-41266>`_)


Other Changes and Additions
---------------------------

- * In ``love_manager_client``, ``make_love_stress_tests`` and ``make_love_uptime_tests`` change location attribute to be an URL instead of a domain
  * In ``love_manager_client`` remove ``command_url``
  * In ``make_love_stress_tests`` and ``make_love_uptime_tests`` make both ``USER_USERNAME`` and ``USER_USER_PASS`` environment variables required (`DM-41536 <https://rubinobs.atlassian.net/browse/DM-41536>`_)


v0.27.0 (2023-10-30)
====================

New Features
------------

- Update ``maintel/tma/random_walk.py`` to have timer outside the generator ``get_azel_random_walk``
- Create ``maintel/tma/random_walk_and_take_image_gencam.py`` based on ``BaseTrackTargetAndTakeImage`` and ``RandomWalk`` (`DM-38437 <https://rubinobs.atlassian.net/browse/DM-38437>`_)


v0.26.1 (2023-10-06)
====================

New Features
------------

- In ``auxtel/latiss_base_align.py``, add functionality to return hexapod to its initial position in case of failures during the alignment process.. (`DM-37831 <https://rubinobs.atlassian.net/browse/DM-37831>`_)
- In ``auxtel/correct_pointing``, reset offsets after slewing to avoid elevation out of range issue.
  In ``auxtel/latiss_base_align.py``, relax default focus threshold. (`DM-40852 <https://rubinobs.atlassian.net/browse/DM-40852>`_)


Documentation
-------------

- Integrate towncrier for release notes and change log management (`DM-40534 <https://rubinobs.atlassian.net/browse/DM-40534>`_)


Other Changes and Additions
---------------------------

- In `news_creation.yaml` remove the `--dir` parameter from towncrier check action. (`DM-40534 <https://rubinobs.atlassian.net/browse/DM-40534>`_)


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
