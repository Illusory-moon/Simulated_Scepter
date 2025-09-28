from simul import SimulatedUniverse


class IronBloodUniverse(SimulatedUniverse):
    def __init__(
            self, find, debug, speed, consumable, slow, nums=-1, unlock=False, bonus=False, update=0, gui=0):
        super().__init__(find, debug, speed, consumable, slow, nums, unlock, bonus, update, gui)