.. py:currentmodule:: lsst.ts.externalscripts

#######################
lsst.ts.externalscripts
#######################

Organizes external Scripts for testing purposes.

Using ts_externalscripts
========================
scriptqueue and script CSC must be running.

.. code:: bash

   request_script.py -l #Lists available scripts
   request_script.py -- show # shows what's on the queue

Developing/writing ts_externalscripts
=====================================
External Scripts are testing integration of CSCs.
Each script has a particular purpose.
Naming convention follows this.
Primary action/purpose is the subpackage name.
module name is script.
class name is PrimaryCSCAction.
Example would be externalscripts.characterization.scripts import LaserCharacterization.



API Reference
=============

.. automodapi:: lsst.ts.externalscripts.scripts
   :no-inheritance-diagram:


.. automodapi:: lsst.ts.externalscripts.coordination
   :no-inheritance-diagram:

.. automodapi:: lsst.ts.externalscripts.characterization
   :no-inheritance-diagram:
