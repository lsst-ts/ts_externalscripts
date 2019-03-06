#!/usr/bin/env python

import importlib
import asyncio

from lsst.ts.scriptqueue.base_script import BaseScript
from lsst.ts.salobj import Remote


__all__ = ["TransitionComponents"]


class TransitionComponents(BaseScript):
    """ This script is capable of sending state transition commands to a series of components
    specified in a configuration file. It can make a single state transition or a series of
    transitions.

    It will dynamically load remotes to talk to those components.
    """

    def __init__(self, index, descr=""):
        super().__init__(index=index, descr=descr,
                         remotes_dict={})
        self.components = []
        self.transition_to = []
        self.settings_to_apply = []

        self.remotes = {}

        self.valid_transitions = ['enterControl', 'start', 'enable',
                                  'disable', 'standby', 'exitControl']

        self.time_per_component = 10.  # Time it takes to instantiate a component
        self.time_per_transition = 5.  # Time it takes to make a transition
        self.cmd_timeout = 5.

    async def configure(self, components, transition_to, settings_to_apply=None):
        """Configure script.

        Parameters
        ----------
        components : `str`
            A comma separated list of components to work on. Indexed components can be
            specified after a colon, e.g.; ComponentA,ComponentB:1,ComponentB:2
        transition_to : `str`
            A comma separated list of commands to transition the components to the
            desired state, e.g.; start,enable
        settings_to_apply : `str`
            A comma separated list of settings to apply for each component, in case transitioning
            from STANDBY to DISABLE. If an empty string is used, will read the `logevent_settingVersions`
            event and select `recommendedSettingsVersion`.

            For three components when the second does not need a setting;

            default,,Default1

            or for three components when the last does not need a setting;

            default,Default1,


        Raises
        ------
        IOError
            If specified transition is not part of the valid_transition.
            If settings_to_apply is given but with wrong number of elements. Must either be None
            (default) or have the same size as the components.
            If components is empty or has the wrong structure.
        """
        self.log.info("Configure started")

        self.components = components.split(",")
        for component in self.components:
            split_component = component.split(":")
            if len(split_component) > 1:
                component_name = split_component[0].strip()
                index = int(split_component[1])
            else:
                component_name = component.strip()
                index = 0

            self.remotes[component] = Remote(importlib.import_module('SALPY_%s' % component_name),
                                             index,
                                             include=self.valid_transitions)

            await asyncio.sleep(0.)  # Give control back to event loop

        # Check that transition_to are valid
        self.transition_to = []
        for transition in transition_to.split(","):
            if transition.strip() not in self.valid_transitions:
                raise IOError('Transition %s not valid. Must be one of %s' % (transition,
                                                                              self.valid_transitions))
            else:
                self.transition_to.append(transition.strip())

        if settings_to_apply is not None:
            self.settings_to_apply = [setting.strip() for setting in settings_to_apply.split(",")]

        if len(self.settings_to_apply) != len(self.components):
            raise RuntimeError(f"Setting to apply ({len(self.settings_to_apply)}) "
                               f"must have same size of components ({len(self.components)}).")

        self.log.info("Configure completed")

    def set_metadata(self, metadata):
        """Compute estimated duration based on number of components plus number of
        state transitions.

        Parameters
        ----------
        metadata : SAPY_Script.Script_logevent_metadataC
        """
        duration = len(self.components)*(self.time_per_component +
                                         len(self.transition_to)*self.time_per_transition)
        metadata.duration = duration

    async def run(self):
        """Run script."""

        # await self.checkpoint("start")

        for transition in self.transition_to:
            awaitable_list = []
            for i, remote in enumerate(self.remotes):
                # await self.checkpoint(f"{remote}: {transition}")
                cmd_attr = getattr(self.remotes[remote], f'cmd_{transition}')
                topic = cmd_attr.DataType()
                if transition == 'start' and self.settings_to_apply is not None:
                    topic.settingsToApply = self.settings_to_apply[i]
                # adds command to a list
                awaitable_list.append(cmd_attr.start(topic, timeout=self.cmd_timeout))
            await asyncio.gather(*awaitable_list)


if __name__ == '__main__':
    TransitionComponents.main(descr="Drive  state transition for components.")
