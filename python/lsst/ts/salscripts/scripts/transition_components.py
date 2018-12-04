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

        self.valid_transitions = ['start', 'enable', 'disable', 'standby']

        self.time_per_component = 10.  # Time it takes to instantiate a component
        self.time_per_transition = 5.  # Time it takes to make a transition
        self.cmd_timeout = 5.

    def configure(self, components, transition_to, settings_to_apply=None):
        """Configure script.

        Parameters
        ----------
        components : list(tuples())
            A list of tuples with the component name and index, e.g.;
            [('Electrometer', 1), ('FiberSpectrograph')]. Note that components that are
            not indexed they don't need to be passed or use index = 0.
        transition_to : list(str())
            For which states to transition to. For instance ['DISABLE', 'ENABLE'], will
            transition all components from standby to disable and to enable in a single take.
        settings_to_apply : list(str())
            The settings to apply for each component, in case transitioning from STANDBY to
            DISABLE. If an empty string is used, will read the `logevent_settingVersions` event
            and select `recommendedSettingsVersion`.

        Raises
        ------
        IOError
            If specified transition is not part of the valid_transition.
            If settings_to_apply is given but with wrong number of elements. Must either be None
            (default) or have the same size as the components.
            If components is empty or has the wrong structure.
        """
        self.log.info("Configure started")

        if len(components) == 0:
            raise IOError('Input components is empty. Must have at least one component to work.')
        elif len(transition_to) == 0:
            raise IOError('Need at least one transition to perform.')

        self.components = components
        for component in components:
            index = 0
            if len(component) < 1:
                raise IOError('Item %s has the wrong number of items. Must have at least 1 item,'
                              'the component name.' % component)
            elif len(component) > 1:
                index = int(component[1])
            self.remotes[component[0]] = Remote(importlib.import_module('SALPY_%s' % component[0]),
                                                index)

        # Check that transition_to are valid
        for transition in transition_to:
            if transition not in self.valid_transitions:
                raise IOError('Transition %s not valid. Must be one of %s' % (transition,
                                                                              self.valid_transitions))
        self.transition_to = transition_to

        if settings_to_apply is None:
            self.settings_to_apply = settings_to_apply
        elif len(settings_to_apply) == self.components:
            self.settings_to_apply = settings_to_apply
        else:
            raise IOError('Invalid entry for settings_to_apply: %s' % settings_to_apply)

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

        for i, remote in enumerate(self.remotes):
            awaitable_list = []
            for transition in self.transition_to:

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
