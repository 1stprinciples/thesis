 # mosaik_powerfacoty.py

import mosaik_powerfactory.powerfactory_tools as pftools
import powerfactory
import mosaik_api
import mosaik.exceptions

import arrow
import logging

logger = logging.getLogger('powerfactory.mosaik')

META = {
    'models': {
        'ElmNet' : {
            'public': True,
            'params': ['loc_name'],
            'attrs': [],
        },
    },
    'extra_methods': ['init_model_attributes'],
}

class PowerFactorySimulator(mosaik_api.Simulator):
    """Base Mosaik interface for Digisilent Powerfactory



    """

    def __init__(self):
        """Constructor of the PowerFactorySimulator

        Creates an instance of the PowerFactorySimulation with the default
        option set. It also starts powerfactory in engine mode.

        Returns:
            A Instance of PowerFacotrySimulator

        """
        # Init the Metadata in the Super Class
        super().__init__(META)
        # Init Power Facotry
        self.pf = powerfactory.GetApplication()
        if self.pf is None:
            raise Exception("Starting PowerFactory application in engine mode failed")
        # Hide the app to imporve speed
        self.pf.Hide()
        self.pf.EchoOff()

        # Set the default step sizes
        self.step_size = 1 #s

        # Set the default referenze time
        self._ref_date_time = None

        # Set the studdy case to none by default
        self.study_case = None

        # Set the command object to none as default
        self._command = None

    @property
    def ref_date_time(self):
        return self._ref_date_time

    @ref_date_time.setter
    def ref_date_time(self,value):
        self._ref_date_time = arrow.get(value)


    def init(self, sid, project_name , options = None): # pylint: disable=W0221
        """ Init method for the Mosaik interface

        Activates the given project and set the options to the simulator

        Args:
            sid: The simulator sid
            project_name: The name of the PowerFactory project which the
                simulator should use
            options: A dictionary of optional options for the simulator.
                Possible keys are: step_size, ref_date_time, study_case

        Returns:
            The meta dictionary of the simulator

        """
        del sid

        # Set the Simulation Options
        if options is not None:
            for attr,value in options.items():
                if value is not None:
                    # If the option is a dictionary do not replace it, update it
                    if isinstance(getattr(self,attr),dict):
                        oldvalue = getattr(self,attr)
                        oldvalue.update(value)
                        value = oldvalue

                    setattr(self,attr,value)

        # Activate project in powerfactory
        if project_name is None:
            raise Exception("You have to provide the project_name for PowerFactory")
        self.pf.ActivateProject(project_name)

        # Activate the study case
        if self.study_case is None:
            # If there is no study_case given get the current study case
            case = self.pf.GetActiveStudyCase()
            self.study_case = case.loc_name
        else:
            cases = self.pf.GetProjectFolder('study').GetChildren(0,'%s.IntCase' % self.study_case)
            if cases is None:
                raise Exception("There is no study case with the name %s in your PowerFactory project" % self.study_case)
            else:
                case = cases[0]
                case.Activate()


        # Sync the ref_case_time
        if self.ref_date_time is None:
            self.ref_date_time = self._get_case_time()
        else:
            self._set_case_time(0)

        # Get the calculation commend
        self._get_command()

        logger.debug("Simulation will be done on project: %s with study case: %s and reference date: %s",project_name, self.study_case, self.ref_date_time)

        # Extend the META dict with all relevant Models
        models = self.pf.relevant_models()
        for model in models:
            attrs =  pftools.attributes_for_model(model)
            if model == 'ElmNet':
                self.meta['models'][model]['attrs'] = attrs
            else:
                self.meta['models'][model] = {
                    'public': False,
                    'params': [],
                    'attrs': attrs,
                    }

        # this methode has to return the meta dict
        return self.meta #pylint: disable=E1101



    def create(self, num, model, loc_name): # pylint: disable=W0221
        """ Create Methods for the mosiak api

        Map entities within the PowerFactory Modell to Mosaik. It is only allowed
        to create a ElmNet Modell. Within the ElmNet enitity all relevant
        objects are added as children.

        Args:
            num: Number of entities to map. It has to be one
            model: The name of the model to map. It has to be 'ElmNet'
            loc_name: The name of the ElmNet to map

        Returns:
            The created entities
        """


        entities = []
        children_entities = []

        if model != 'ElmNet':
            raise Exception("You can only create a ElmNet Modell")

        # Get the gird and all its content
        grid = self.pf.get_grid(loc_name)
        children = grid.children_elements()

        # Create entities for all grid elements
        for child in children:
            children_entities.append({'eid': child.unique_name(),'type': child.GetClassName()})

        # Createa the gird entitie
        entities.append({'eid': grid.unique_name(), 'type': model, 'children': children_entities})
        return entities


    def step(self, mosaik_time, inputs):
        """ Step methods for the mosaik api

        It will set the inputs to the entities. And run one simulation step

        Args:
            mosaik_time: The relative simulation time in secounds
            inputs: The inputs to the elements

        Returns:
            The next relative simulation time

        """

        for eid, attrs in inputs.items():

            # Get PF element
            element = self.pf.element_with_unique_name(eid)

            # Set the attribes of the elements
            for attr, sources in attrs.items():
                new_value = sum(sources.values()) # We not care about the sources
                if new_value != element.GetAttribute(attr):
                    element.SetAttribute(attr,new_value)

        self._run_step(mosaik_time)

        #When we want to do the next simulation step
        return mosaik_time + self.step_size

    def get_data(self, outputs):
        """ Get_date method of the mosaik api

        It returns the requestet data

        Args:
            outputs: Dict of eids and attributes to output

        Returns:
            A dict of eids, attributes and corresponding values

        """

        # The outputs parameter can look like this
        # {
        #     'Load1.ElmLod': ['plini'],
        #     'Load2.ElmLod': ['plini'],
        # }

        # Init the data dictonary
        data = {}
        # Loop over the entity id for requested data
        for eid, attrs in outputs.items():
            # Get the element from the eid
            element = self.pf.element_with_unique_name(eid)
            data[eid] = {}
            # Loop over the requested attributes
            for attr in attrs:
                # Get the attribute of the element
                try:
                    data[eid][attr] = element.GetAttribute(attr)
                except AttributeError:
                    logger.error("Element %s has no Attribute %s, replacing the value with NaN",eid,attr)
                    data[eid][attr] = float('nan')

        return data


    def finalize(self):
        """ Finalize mehtode of the Simulator

        Finalize the simulator. It reset the case time in power factory to the
        ref_case_time

        """
        # Reset the case time in PowerFacotory
        self._set_case_time(0)
        self.pf.Show()


    def _set_case_time(self,mosaik_time):
        """ Private Mehtode to set the case time in PowerFactory

        It set the case time in PowerFacotory to the given relavtive simulation
        and the ref_date_time

        Args:
            mosaik_time: the current relative simualation time

        Returns:
            None

        """

        # Get the study case
        case = self.pf.GetActiveStudyCase()
        # Calculate the resulting date
        dt = self.ref_date_time.replace(seconds=+mosaik_time)
        # set the time with the unix time stamp
        case.SetStudyTime(dt.float_timestamp)


    def _get_case_time(self):
        """ Private Mehtode to get the case time from PowerFactory

        Returns the study case time of PowerFactory

        Returns:
            arrow.Arrow object with the study case time

        """
        #Get the study case
        case = self.pf.GetActiveStudyCase()
        dt_float = case.GetAttribute('iStudyTime')
        return arrow.get(dt_float).to('local')


    def _run_step(self,mosaik_time):
        """Abtract method to run one simulation step in PowerFactory
        """
        raise NotImplementedError

    def _get_command(self):
        """Abtract method to get the Command Object form PowerFactory
        """
        raise NotImplementedError


    def init_model_attributes(self,model,attrs):
        elements = self.pf.elements_of_model(model)

        for ele in elements:

            # Set the attribes of the elements
            for attr, value in attrs.items():
                ele.SetAttribute(attr,value)
