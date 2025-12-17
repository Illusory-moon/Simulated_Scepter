from simul import SimulatedUniverse


class IronBloodUniverse(SimulatedUniverse):
    def __init__(
            self, find, debug, speed, consumable, slow, nums=-1, bonus=False, update=0, gui=0):
        super().__init__(find, debug, speed, consumable, slow, nums, bonus, update, gui)